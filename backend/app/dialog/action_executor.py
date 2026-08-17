"""Action Executor — 对话意图执行器

将对话引擎识别的意图转化为实际操作，直接调用服务层（非HTTP自调）。

可执行的意图（Phase 1）:
    - emp_upload_invoice: 上传发票（base64图片）
    - emp_no_receipt: 无票报销
    - emp_query_invoices: 查询用户发票列表
    - emp_query_status: 查询报销单进度
    - emp_submit_reimbursement: 创建+提交报销单
    - emp_confirm_category: 确认费用分类
    - emp_confirm_project: 确认项目归属
    - emp_modify_field: 修改发票字段
    - admin_approve: 审核通过发票
    - admin_reject: 审核驳 development
    - admin_query_pending: 查询待审批报销单
    - admin_query_detail: 查询报销单详情
    - self_insight_pending: 查询未提交票据

尚未实现的意图（Phase 2+）:
    - insight_*: 需要 Insight Engine
    - admin_batch_approve: 需要批量操作扩展
    - common_human_handoff: 需要通知服务
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_sessionmaker
from app.config import settings
from app.models.invoice import Invoice, InvoiceStatus, ReceiptType
from app.models.reimbursement import Reimbursement, ReimbursementStatus, ReimbursementTravelDay
from app.models.employee import Employee
from app.services.invoice_service import InvoiceService
from app.services.reimbursement_service import (
    create_reimbursement,
    submit_reimbursement,
    get_reimbursement_or_404,
)
from app.services.cycle_engine import cycle_display, current_cycle_key, cycle_key_of, billing_cycle
from app.services.subsidy_engine import recompute_all, load_holidays, day_type, subsidy_rate
from app.dialog.models import DialogContext, UserRole
from app.dialog.insight_engine import get_insight_engine

logger = logging.getLogger(__name__)


class ActionExecutor:
    """对话意图执行器 — 调用后端服务层完成实际操作"""

    def __init__(self):
        self._sessionmaker = None  # 延迟初始化，避免无数据库环境下导入失败

    def _ensure_sessionmaker(self):
        """延迟获取数据库 sessionmaker"""
        if self._sessionmaker is None:
            self._sessionmaker = get_async_sessionmaker()
        return self._sessionmaker

    async def execute(
        self,
        intent_name: str,
        context: DialogContext,
        attachment_data: Optional[dict] = None,
    ) -> dict[str, Any]:
        """执行意图对应的操作

        Args:
            intent_name: 意图名称
            context: 对话上下文（含已填充槽位）
            attachment_data: 附件数据 {"base64": "...", "file_type": "jpg"}

        Returns:
            {"text": "用户可见的回复文本", "data": {...}}
        """
        # 洞察类意图 → 委托给 InsightEngine
        if intent_name.startswith("insight_") or intent_name.startswith("self_insight_"):
            sm = self._ensure_sessionmaker()
            async with sm() as db:
                engine = get_insight_engine()
                return await engine.execute(intent_name, context, db)

        # admin_query_person → 功能等同 insight_person（管理员视角的人员报销查询）
        if intent_name == "admin_query_person":
            sm = self._ensure_sessionmaker()
            async with sm() as db:
                engine = get_insight_engine()
                return await engine.execute("insight_person", context, db)

        handler = self._get_handler(intent_name)
        if not handler:
            return {
                "text": f"功能「{intent_name}」正在开发中，敬请期待。",
                "data": {"not_implemented": True},
            }

        try:
            sm = self._ensure_sessionmaker()
            async with sm() as db:
                result = await handler(context, db, attachment_data)
                return result
        except Exception as e:
            logger.exception("Action execution failed: intent=%s error=%s", intent_name, e)
            return {
                "text": f"操作执行失败：{e}",
                "data": {"error": str(e)},
            }

    def _get_handler(self, intent_name: str):
        """根据意图名称获取对应的处理函数"""
        handlers = {
            # 员工提单类
            "emp_upload_invoice": self._handle_upload_invoice,
            "emp_fill_invoice_desc": self._handle_fill_invoice_desc,
            "emp_batch_describe": self._handle_batch_describe,
            "emp_batch_modify": self._handle_batch_modify,
            "emp_no_receipt": self._handle_no_receipt,
            "emp_submit_reimbursement": self._handle_submit_reimbursement,
            "emp_modify_field": self._handle_modify_field,
            "emp_confirm_category": self._handle_confirm_category,
            "emp_confirm_project": self._handle_confirm_project,
            "emp_delete_invoice": self._handle_delete_invoice,
            "emp_mark_travel_day": self._handle_mark_travel_day,
            # 查询类
            "emp_query_invoices": self._handle_query_invoices,
            "emp_query_status": self._handle_query_status,
            "emp_query_my_reimbursement": self._handle_query_my_reimbursement,
            # 员工越权查询拦截 — LLM 判定后由本处统一回复
            "emp_permission_denied": self._handle_permission_denied,
            # 管理员操作
            "admin_approve": self._handle_admin_approve,
            "admin_reject": self._handle_admin_reject,
            "admin_query_pending": self._handle_admin_pending,
            "admin_query_detail": self._handle_admin_detail,
            "admin_query_cycle_summary": self._handle_admin_cycle_summary,
            "admin_mark_reimbursed": self._handle_admin_mark_reimbursed,
            "admin_aggregate_invoices": self._handle_admin_aggregate_invoices,
        }
        return handlers.get(intent_name)

    # ============================================================
    # 员工提单类
    # ============================================================

    async def _handle_upload_invoice(
        self, ctx: DialogContext, db: AsyncSession, attachment: Optional[dict]
    ) -> dict:
        """上传发票 — base64图片/PDF/OFD → InvoiceService.process_upload"""
        if not attachment or not attachment.get("base64"):
            return {"text": "请发送发票图片，我将为您自动识别和处理。", "data": {}}

        file_data = base64.b64decode(attachment["base64"])
        file_type = attachment.get("file_type", "jpg")

        # 发票类型：优先用前端传入的，否则留空让 InvoiceService 走 LLM Vision 自动识别
        receipt_type = ctx.slots.get("receipt_type")
        receipt_type_val = receipt_type.value if receipt_type and receipt_type.filled else ""

        # 费用用途：优先用前端弹窗传入的 user_description，
        # 否则回退到用户在聊天框输入的文本（ctx.current_text）
        user_desc = ctx.user_description or ctx.current_text or ""
        has_purpose = bool(user_desc)

        # 当前发票索引（0-based，基于已上传数量）
        current_invoice_index = len(ctx.batch_invoice_ids)

        # 检测并解析批量描述（如"第一张是打车费，第二张是快递费"）
        # 设计：新前端流程会为每张发票都携带同一份 purpose 文本，
        # 因此只在第一张（batch_desc_map 为空时）解析一次，后续张直接用缓存。
        # existing_count 用于"这两张"等相对指代的偏移（分次说明场景）
        if has_purpose and not ctx.batch_desc_map:
            existing_count = len(ctx.batch_invoice_ids)
            new_map = await self._parse_batch_description(user_desc, existing_count=existing_count)
            if new_map:
                ctx.batch_desc_map.update({str(k): v for k, v in new_map.items()})
                logger.info(
                    f"Initial batch description parsed, {len(ctx.batch_desc_map)} entries: {ctx.batch_desc_map}"
                )
        elif has_purpose and ctx.batch_desc_map:
            # batch_desc_map 已有缓存但当前索引缺失（如分次说明："第一张打车费" + "这两张餐费"）
            # 尝试增量解析本次说明，补充未覆盖的索引
            if str(current_invoice_index) not in ctx.batch_desc_map:
                existing_count = len(ctx.batch_invoice_ids)
                incremental = await self._parse_batch_description(user_desc, existing_count=existing_count)
                if incremental:
                    # 仅合并新索引，不覆盖已有
                    for k, v in incremental.items():
                        if str(k) not in ctx.batch_desc_map:
                            ctx.batch_desc_map[str(k)] = v
                    logger.info(
                        f"Incremental batch description merged, total {len(ctx.batch_desc_map)} entries: {ctx.batch_desc_map}"
                    )

        # 优先从持久化的批量描述映射取当前发票的描述
        cached_desc = ctx.batch_desc_map.get(str(current_invoice_index))
        if cached_desc:
            user_desc = cached_desc
            logger.info(f"Invoice #{current_invoice_index + 1} using cached batch description: {user_desc}")

        service = InvoiceService(db)
        try:
            invoice = await service.process_upload(
                file_data=file_data,
                file_type=file_type,
                receipt_type=receipt_type_val,
                user_id=ctx.user_id,
                user_description=user_desc,
            )
        except Exception as e:
            logger.exception("Invoice upload failed")
            error_msg = str(e) or "未知错误"
            text = (
                "❌ 发票识别失败\n\n"
                "| 项目 | 内容 |\n"
                "|------|------|\n"
                f"| 状态 | 识别失败 |\n"
                f"| 原因 | {error_msg} |\n"
            )
            return {"text": text, "data": {"error": error_msg}}

        # 清除临时字段（仅当次请求有效）
        ctx.user_description = None

        # 添加到批量列表
        if invoice.id not in ctx.batch_invoice_ids:
            ctx.batch_invoice_ids.append(invoice.id)

        # 设置待处理发票ID，供后续描述补充使用
        ctx.pending_invoice_id = invoice.id

        # 格式化结果为 Markdown 表格
        # 注：user_description 是用户填的用途，expense_date 是出差日期（费用发生日期）
        # 两者是后续自动生成报销单的核心依据，必须确保完整
        has_expense_date = bool(invoice.expense_date)
        table_rows = [
            ("发票编号", f"#{invoice.id}"),
            ("发票类型", invoice.receipt_type.value if invoice.receipt_type else "未知"),
            ("单号", invoice.invoice_number or "—"),
            ("销售方", invoice.seller_name or "未知"),
            ("金额（含税）", f"¥{invoice.total_with_tax or '未知'}"),
            ("税额", f"¥{invoice.tax_amount or '—'}"),
            ("开票时间", invoice.issue_date or "—"),
            ("费用分类", invoice.fee_subcategory or "—"),
            ("用途", invoice.user_description or "待补充"),
            ("出差日期", invoice.expense_date or "待补充"),
            ("状态", f"{self._status_emoji(invoice)} {self._status_text(invoice)}"),
            ("验真", f"{self._verify_emoji(invoice)} {self._verify_text(invoice)}"),
        ]

        # 添加警告信息
        warnings = []
        if invoice.duplicate_status and invoice.duplicate_status.value == "DUPLICATE":
            warnings.append("⚠️ 此发票可能为重复发票")
        if invoice.diff_conflicts:
            warnings.append("⚠️ OCR与LLM识别存在差异，请核实")
        # 用途/出差日期缺失提醒（自动生成报销单的核心字段，必须完整）
        missing_fields = []
        if not invoice.user_description:
            missing_fields.append("用途")
        if not has_expense_date:
            missing_fields.append("出差日期")
        if missing_fields:
            warnings.append(
                f"⚠️ 请补充：{'、'.join(missing_fields)}（这两项是后续自动生成报销单的核心依据）"
            )

        # 构造表格
        text = "✅ 发票已上传并识别\n\n"
        text += "| 项目 | 内容 |\n"
        text += "|------|------|\n"
        for label, value in table_rows:
            text += f"| {label} | {value} |\n"

        if warnings:
            text += "\n" + "\n".join(warnings) + "\n"

        text += f"\n已添加到批量提交列表（当前 {len(ctx.batch_invoice_ids)} 张）\n"

        # 如果前端已提供用途描述，不再 follow_up 追问
        if has_purpose:
            if ctx.role == UserRole.EMPLOYEE:
                text += "继续上传可发送更多发票。报销单将按周期自动生成与归集。"
            else:
                text += "继续上传可发送更多发票，输入「完成」提交报销。"
            # 追加当前批量发票的 Markdown 汇总表格
            md_table = await self._build_batch_summary_table(ctx, db)
            if md_table:
                text += "\n\n" + md_table
            return {
                "text": text,
                "data": {"invoice_id": invoice.id},
            }

        # 无用途 → follow_up 追问，并附带当前 batch 发票摘要，帮助用户对应“第几张”
        text += "请按序号描述每张发票的用途（如“1 打车费，2 餐费”），可回复「跳过」跳过"
        # 追加当前批量发票的 Markdown 汇总表格
        md_table = await self._build_batch_summary_table(ctx, db)
        if md_table:
            text += "\n\n" + md_table

        # 构造供前端展示的可识别摘要
        batch_summary = await self._build_batch_invoice_summaries(ctx, db)
        return {
            "text": text,
            "data": {
                "invoice_id": invoice.id,
                "follow_up": {
                    "state": "waiting_purpose",
                    "intent": "emp_fill_invoice_desc",
                    "prompt": "请按序号描述每张发票的用途（如“1 打车费，2 餐费”）",
                    "pending_invoice_id": invoice.id,
                    "batch_summary": batch_summary,
                },
            },
        }

    async def _handle_fill_invoice_desc(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """为刚上传的发票补充用途描述/出差日期，支持按索引批量补描述

        用户回复"出差时间8月1日，项目投标费"时，LLM 会拆分为：
        - purpose="项目投标费"
        - expense_date="2026-08-01"
        两个参数同时传入。本 handler 同时写入 user_description 和 expense_date。
        """
        purpose_slot = ctx.slots.get("purpose")
        if not purpose_slot or not purpose_slot.filled:
            return {"text": "请描述这笔费用的用途。", "data": {}}

        purpose_text = str(purpose_slot.value).strip()

        # 出差日期（可选参数，LLM 识别到日期时填入）
        expense_date_slot = ctx.slots.get("expense_date")
        expense_date_raw = (
            str(expense_date_slot.value).strip()
            if expense_date_slot and expense_date_slot.filled
            else None
        )
        parsed_date = self._parse_expense_date(expense_date_raw) if expense_date_raw else None

        # 1. 尝试按索引批量解析（如 "1 打车费，2 餐费"）
        indexed_map = self._parse_indexed_descriptions(purpose_text)
        if indexed_map and ctx.batch_invoice_ids:
            return await self._apply_indexed_descriptions(
                ctx, db, indexed_map, purpose_text, parsed_date
            )

        # 2. 单张发票兜底：按 pending_invoice_id 更新
        invoice_id = ctx.pending_invoice_id
        if not invoice_id:
            return {"text": "没有待描述的发票，请先上传发票图片。", "data": {}}

        result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()
        if not invoice:
            ctx.pending_invoice_id = None
            return {"text": f"未找到发票 #{invoice_id}。", "data": {}}

        invoice.user_description = purpose_text
        date_updated = False
        if parsed_date:
            invoice.expense_date = parsed_date
            invoice.expense_date_source = "note"  # 用户口述的日期
            date_updated = True
        await db.commit()

        # 清除待处理标记
        ctx.pending_invoice_id = None

        text_parts = [f"已为发票 #{invoice_id} 添加用途描述"]
        text_parts.append(f"用途：{purpose_text}")
        if date_updated:
            text_parts.append(f"出差日期：{parsed_date.isoformat()}")
        text_parts.append(f"已添加到批量提交列表（当前 {len(ctx.batch_invoice_ids)} 张）")
        text = "\n\n".join(text_parts) + "\n"
        # 追加 Markdown 汇总表格
        md_table = await self._build_batch_summary_table(ctx, db)
        if md_table:
            text += "\n" + md_table + "\n"
        if ctx.role == UserRole.EMPLOYEE:
            text += "继续上传可发送更多发票。报销单将按周期自动生成与归集。"
        else:
            text += "继续上传可发送更多发票，输入「完成」提交报销。"
        return {"text": text, "data": {"invoice_id": invoice_id}}

    @staticmethod
    def _parse_expense_date(raw: str | None) -> Optional[date]:
        """解析用户口述的出差日期为 date 对象

        支持格式：
        - 2026-08-01 / 2026/8/1 / 2026年8月1日
        - 8月1日 / 8-1 / 8/1（缺省年份补当前年份）
        - 20260801（紧凑 8 位）
        解析失败返回 None（不写入 expense_date，避免脏数据）
        """
        if not raw:
            return None
        import re
        from datetime import date as date_cls

        s = raw.strip()

        # 1. YYYY-MM-DD / YYYY/M/D / YYYY年M月D日
        m = re.match(r"^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?$", s)
        if m:
            try:
                return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None

        # 2. 紧凑 8 位 YYYYMMDD
        m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
        if m:
            try:
                return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None

        # 3. M月D日 / M-D / M/D（缺省年份补当前年份）
        m = re.match(r"^(\d{1,2})[-/月](\d{1,2})日?$", s)
        if m:
            try:
                from datetime import date as date_cls2
                today = date_cls2.today()
                return date_cls2(today.year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                return None

        return None

    def _parse_indexed_descriptions(self, text: str) -> dict[int, str] | None:
        """解析 "1 打车费，2 餐费" 这类按索引描述

        返回 {1: "打车费", 2: "餐费"}；若无法解析返回 None。
        """
        if not text:
            return None

        # 支持中英文逗号、分号、换行分隔
        # 格式：序号 + 分隔 + 描述，如 "1 打车费", "1. 打车费", "1=打车费"
        parts = re.split(r"[，,；;\n]", text)
        result: dict[int, str] = {}
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # 匹配：1 描述 / 1.描述 / 1=描述 / 1 - 描述
            m = re.match(r"^(\d+)\s*[\.:\-=\s]\s*(.+)$", part)
            if not m:
                m = re.match(r"^(\d+)\s+(.+)$", part)
            if not m:
                # 某一段不符合索引格式，整体视为非索引描述
                return None
            idx = int(m.group(1))
            desc = m.group(2).strip()
            if idx < 1 or not desc:
                return None
            result[idx] = desc

        return result if result else None

    async def _apply_indexed_descriptions(
        self,
        ctx: DialogContext,
        db: AsyncSession,
        indexed_map: dict[int, str],
        original_text: str,
        parsed_date: Optional[date] = None,
    ) -> dict:
        """应用按索引描述到 batch 发票

        parsed_date 非空时，同时回填到每张发票的 expense_date。
        """
        if not ctx.batch_invoice_ids:
            return {"text": "没有待描述的发票，请先上传发票图片。", "data": {}}

        # 按 batch 顺序查询发票
        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(ctx.batch_invoice_ids))
        )
        invoice_map = {inv.id: inv for inv in result.scalars().all()}
        ordered = [invoice_map[i] for i in ctx.batch_invoice_ids if i in invoice_map]

        updated: list[tuple[int, int, str]] = []  # (batch_index, invoice_id, desc)
        not_found: list[int] = []
        for idx, desc in indexed_map.items():
            if idx > len(ordered):
                not_found.append(idx)
                continue
            inv = ordered[idx - 1]
            inv.user_description = desc
            if parsed_date:
                inv.expense_date = parsed_date
                inv.expense_date_source = "note"
            updated.append((idx, inv.id, desc))

        await db.commit()

        # 清除待处理标记
        ctx.pending_invoice_id = None

        # 构建回复
        lines = ["✅ 已按序号添加用途描述"]
        if parsed_date:
            lines.append(f"📅 出差日期：{parsed_date.isoformat()}（已应用到所有发票）")
        lines.append("")
        for batch_idx, inv_id, desc in updated:
            lines.append(f"  {batch_idx}. 发票 #{inv_id} → {desc}")
        if not_found:
            lines.append(f"\n⚠️ 以下序号超出范围，未找到对应发票：{', '.join(str(i) for i in not_found)}")

        md_table = await self._build_batch_summary_table(ctx, db)
        if md_table:
            lines.append("\n" + md_table)

        if ctx.role == UserRole.EMPLOYEE:
            lines.append("\n继续上传可发送更多发票。报销单将按周期自动生成与归集。")
        else:
            lines.append("\n继续上传可发送更多发票，输入「完成」提交报销。")

        return {
            "text": "\n".join(lines),
            "data": {"updated": len(updated), "total": len(ordered)},
        }

    async def _handle_delete_invoice(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """删除/撤销已上传但未提交的发票

        从 batch 列表确定目标 → InvoiceService.delete_invoice 硬删除 → 从 batch 移除。
        delete_target 槽位支持三种值：
          - "last"（默认）→ 最近上传的一张
          - "index:N"    → 第 N 张（1-based）
          - "type:关键词" → 按票据类型/销售方/品名匹配
        """
        if not ctx.batch_invoice_ids:
            return {"text": "您还没有上传任何发票，无法删除。", "data": {}}

        # 获取删除目标
        target_slot = ctx.slots.get("delete_target")
        delete_target = target_slot.value if target_slot and target_slot.filled else "last"

        batch_ids = list(ctx.batch_invoice_ids)

        # 查询 batch 中的发票
        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(batch_ids))
        )
        invoice_map = {inv.id: inv for inv in result.scalars().all()}
        # 按 batch 顺序排列（保留上传序）
        ordered = [invoice_map[i] for i in batch_ids if i in invoice_map]

        if not ordered:
            return {"text": "批量列表中的发票不存在，可能已被处理。", "data": {}}

        # ---------- 确定删除目标 ----------
        target_invoice = None
        target_label = ""

        if delete_target == "last" or not delete_target:
            target_invoice = ordered[-1]
            target_label = "最近上传的一张"

        elif delete_target.startswith("index:"):
            try:
                idx = int(delete_target.split(":", 1)[1])
            except ValueError:
                return {"text": "无法解析序号，请说「删除第2张」。", "data": {}}
            if 1 <= idx <= len(ordered):
                target_invoice = ordered[idx - 1]
                target_label = f"第 {idx} 张"
            else:
                return {
                    "text": f"序号超出范围，当前共有 {len(ordered)} 张发票。",
                    "data": {},
                }

        elif delete_target.startswith("type:"):
            kw = delete_target.split(":", 1)[1]
            matched = [
                inv for inv in ordered
                if (inv.receipt_type and kw in inv.receipt_type.value)
                or (inv.seller_name and kw in inv.seller_name)
                or (inv.item_name and kw in inv.item_name)
            ]
            if not matched:
                return {
                    "text": f"未找到与「{kw}」相关的发票。当前批量列表中有 {len(ordered)} 张。",
                    "data": {},
                }
            if len(matched) > 1:
                lines = "\n".join(
                    f"  {i+1}. #{inv.id} {inv.receipt_type.value if inv.receipt_type else ''}"
                    f" - {inv.seller_name or '未知'}"
                    for i, inv in enumerate(ordered)
                )
                return {
                    "text": f"找到了 {len(matched)} 张匹配的发票，请指定序号：\n{lines}",
                    "data": {},
                }
            target_invoice = matched[0]
            target_label = f"与「{kw}」匹配"
        else:
            target_invoice = ordered[-1]
            target_label = "最近上传的一张"

        # ---------- 执行硬删除 ----------
        service = InvoiceService(db)
        try:
            await service.delete_invoice(target_invoice.id, user_id=ctx.user_id)
        except Exception as e:
            return {
                "text": f"删除失败：{e}",
                "data": {"error": str(e)},
            }

        # 从 batch 列表移除
        if target_invoice.id in ctx.batch_invoice_ids:
            ctx.batch_invoice_ids.remove(target_invoice.id)

        # 清除待处理标记（如果删的正是 pending 发票）
        if ctx.pending_invoice_id == target_invoice.id:
            ctx.pending_invoice_id = None

        # ---------- 构建回复 ----------
        seller = target_invoice.seller_name or "未知"
        rt = target_invoice.receipt_type.value if target_invoice.receipt_type else "未知"
        amount = target_invoice.total_with_tax or "未知"

        text = (
            f"🗑️ 已删除{target_label}发票\n\n"
            f"📋 编号：#{target_invoice.id}\n"
            f"📄 类型：{rt}\n"
            f"🏪 销售方：{seller}\n"
            f"💰 金额：¥{amount}\n\n"
            f"当前批量列表剩余 {len(ctx.batch_invoice_ids)} 张发票。"
        )
        if not ctx.batch_invoice_ids:
            text += "\n请继续上传发票，或输入「无票」进行无票报销。"

        return {"text": text, "data": {"deleted_invoice_id": target_invoice.id}}

    async def _handle_no_receipt(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """无票报销"""
        amount_slot = ctx.slots.get("amount")
        desc_slot = ctx.slots.get("description")
        amount = amount_slot.value if amount_slot and amount_slot.filled else ""
        description = desc_slot.value if desc_slot and desc_slot.filled else ""

        service = InvoiceService(db)
        invoice = await service.process_no_receipt(
            user_id=ctx.user_id,
            user_description=description,
            amount=amount,
        )

        # 添加到批量列表
        if invoice.id not in ctx.batch_invoice_ids:
            ctx.batch_invoice_ids.append(invoice.id)

        text = (
            f"✅ 无票报销已创建\n\n"
            f"📋 编号：#{invoice.id}\n"
            f"💰 金额：¥{amount or '待补充'}\n"
            f"📝 描述：{description}\n"
            f"📊 分类：{invoice.fee_subcategory or '待确认'}\n"
            f"⏳ 状态：待人工复核\n\n"
            f"已添加到批量提交列表（当前 {len(ctx.batch_invoice_ids)} 条）\n"
        )
        if ctx.role == UserRole.EMPLOYEE:
            text += "报销单将按周期自动生成与归集。"
        else:
            text += "输入「完成」提交报销。"
        return {"text": text, "data": {"invoice_id": invoice.id}}

    async def _handle_mark_travel_day(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """员工在对话中描述出差日期 → 标记 travel_days + 触发补贴重算

        LLM 从用户文本提取 travel_dates（YYYY-MM-DD 数组）+ note（可选）。
        每个 travel_date：
        - 校验日期落在当前周期内（与 picker 一致规则）
        - 查当前周期报销单（仅查询，不创建——员工端无报销单生成权限）
        - 报销单已存在 → 挂载 + 校验未封账 + recompute_all
        - 报销单不存在 → 暂存 reimbursement_id=NULL + cycle_key，等报销单生成时挂载
        - 重复（同员工同 travel_date）→ 跳过
        """
        td_slot = ctx.slots.get("travel_dates")
        note_slot = ctx.slots.get("note")
        raw_dates: list[str] = []
        if td_slot and td_slot.filled and isinstance(td_slot.value, list):
            raw_dates = [str(d) for d in td_slot.value]
        elif td_slot and td_slot.filled and isinstance(td_slot.value, str):
            # LLM 偶尔返回单字符串而非数组，做兼容
            raw_dates = [str(td_slot.value)]
        note = note_slot.value if note_slot and note_slot.filled else None

        if not raw_dates:
            return {
                "text": "请告诉我要标记哪天为出差日，例如「8月15日出差」「8月15-17日去北京」。",
                "data": {},
            }

        # 当前周期 key（21-20 制）— 仅允许标当前周期内的日期
        today = date.today()
        expected_ck = current_cycle_key(today)

        added: list[str] = []
        skipped_dup: list[str] = []
        rejected_out_of_cycle: list[str] = []
        rejected_locked: list[str] = []
        errors: list[str] = []
        pending_count = 0  # 暂存未挂载的天数

        for d_str in raw_dates:
            try:
                parsed = date.fromisoformat(d_str)
            except ValueError:
                errors.append(f"{d_str}（日期格式错误）")
                continue

            # 校验日期落在当前周期内
            travel_ck = cycle_key_of(parsed)
            if travel_ck != expected_ck:
                rejected_out_of_cycle.append(d_str)
                continue

            # 仅查询报销单，不创建（员工端无报销单生成权限）
            reimb = (
                await db.execute(
                    select(Reimbursement).where(
                        Reimbursement.applicant_id == ctx.user_id,
                        Reimbursement.cycle_key == expected_ck,
                    )
                )
            ).scalars().first()
            if reimb and reimb.is_cycle_locked:
                rejected_locked.append(d_str)
                continue

            # 应用层去重：同员工同 travel_date 已存在（含未挂载）→ 跳过
            existing = (
                await db.execute(
                    select(ReimbursementTravelDay).where(
                        ReimbursementTravelDay.applicant_id == ctx.user_id,
                        ReimbursementTravelDay.travel_date == parsed,
                    )
                )
            ).scalars().first()
            if existing:
                skipped_dup.append(d_str)
                continue

            cycle_year = (reimb.cycle_start or today).year if reimb else today.year
            holidays = await load_holidays(db, cycle_year)
            td = ReimbursementTravelDay(
                reimbursement_id=reimb.id if reimb else None,
                cycle_key=expected_ck,
                travel_date=parsed,
                note=note,
                weekday=parsed.weekday(),
                day_type=day_type(parsed, holidays),
                base_rate=float(subsidy_rate(parsed, holidays)),
                applicant_id=ctx.user_id,
            )
            db.add(td)
            try:
                await db.flush()
            except Exception:
                await db.rollback()
                errors.append(f"{d_str}（标记失败）")
                continue

            # 报销单存在时才重算补贴；否则等报销单生成时挂载后重算
            if reimb:
                await recompute_all(db, reimb, holidays)
            else:
                pending_count += 1
            added.append(d_str)

        await db.commit()

        # 构造回复
        parts: list[str] = []
        if added:
            parts.append(f"✅ 已标记 {len(added)} 天为出差日：{'、'.join(added)}")
        if pending_count > 0:
            parts.append(
                f"⏳ 其中 {pending_count} 天待挂载：报销单生成后（封账日系统自动 / 管理员手动）"
                f"将自动关联并核算补贴"
            )
        if skipped_dup:
            parts.append(f"ℹ️ 已跳过（之前已标记）：{'、'.join(skipped_dup)}")
        if rejected_out_of_cycle:
            parts.append(
                f"⚠️ 不在当前周期（{expected_ck}）：{'、'.join(rejected_out_of_cycle)}"
            )
        if rejected_locked:
            parts.append(f"🔒 周期已封账：{'、'.join(rejected_locked)}")
        if errors:
            parts.append(f"❌ 失败：{'、'.join(errors)}")
        if note and added:
            parts.append(f"📝 备注：{note}")

        text = "\n".join(parts) if parts else "未标记任何出差日。"
        return {
            "text": text,
            "data": {
                "added": added,
                "skipped_dup": skipped_dup,
                "rejected_out_of_cycle": rejected_out_of_cycle,
                "rejected_locked": rejected_locked,
                "errors": errors,
            },
        }

    async def _handle_submit_reimbursement(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """提交报销单 — 聚合已上传发票 + 创建报销单 + 提交"""
        if not ctx.batch_invoice_ids:
            return {"text": "您还没有上传任何发票。请先发送发票图片或输入「无票」进行无票报销。", "data": {}}

        # 查询发票状态
        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(ctx.batch_invoice_ids))
        )
        invoices = list(result.scalars().all())

        # 筛选可提交的发票（CONFIRMED 状态）
        confirmed = [inv for inv in invoices if inv.status == InvoiceStatus.confirmed]
        reviewing = [inv for inv in invoices if inv.status == InvoiceStatus.reviewing]
        not_submittable = [inv for inv in invoices if inv.status not in (
            InvoiceStatus.confirmed, InvoiceStatus.reviewing
        )]

        if not confirmed and not reviewing:
            return {
                "text": f"当前 {len(invoices)} 张发票均未确认，无法提交。\n"
                        f"请等待发票处理完成后重试。",
                "data": {},
            }

        # 确认 REVIEWING 状态的发票
        for inv in reviewing:
            inv.status = InvoiceStatus.confirmed
        if reviewing:
            await db.flush()

        purpose_slot = ctx.slots.get("purpose")
        purpose = purpose_slot.value if purpose_slot and purpose_slot.filled else "对话式提交"

        # 创建报销单
        reimbursement = await create_reimbursement(
            db,
            applicant_id=ctx.user_id,
            reason=purpose,
            invoice_ids=[inv.id for inv in invoices if inv.status == InvoiceStatus.confirmed],
            allowed_user_filter=ctx.user_id if ctx.role == UserRole.EMPLOYEE else None,
        )

        # 提交报销单
        await submit_reimbursement(db, reimbursement.id)
        await db.refresh(reimbursement)

        # 清空批量列表
        ctx.batch_invoice_ids = []

        text = (
            f"✅ 报销单已创建并提交\n\n"
            f"📋 报销单号：#{reimbursement.id}\n"
            f"📝 事由：{purpose}\n"
            f"💰 总金额：¥{reimbursement.total_amount or '计算中'}\n"
            f"📤 状态：已提交，等待审批\n"
            f"📅 时间：{reimbursement.submitted_at or reimbursement.created_at}\n\n"
            f"您可以在对话中输入「查询报销」查看审批进度。"
        )
        return {"text": text, "data": {"reimbursement_id": reimbursement.id}}

    async def _handle_modify_field(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """修改发票字段

        支持通过 invoice_index 槽位指定"第N张"（1-based，对应 batch_invoice_ids），
        未指定时回退到 ctx.pending_invoice_id。
        可修改字段：金额、日期、销售方、税号、发票号、用途。
        """
        field_name = ctx.slots.get("field_name")
        field_value = ctx.slots.get("field_value")
        if not field_name or not field_name.filled or not field_value or not field_value.filled:
            return {"text": "请告诉我要修改哪个字段以及新值。", "data": {}}

        # 解析目标发票：优先 invoice_index 槽位（"第N张"），回退 pending_invoice_id
        invoice_id = None
        index_slot = ctx.slots.get("invoice_index")
        if index_slot and index_slot.filled:
            try:
                idx = int(index_slot.value)
                if idx < 1:
                    return {"text": f"发票序号需大于0，您输入的是 {idx}。", "data": {}}
                if not ctx.batch_invoice_ids:
                    return {"text": "您还没有上传任何发票，无法按序号修改。", "data": {}}
                if idx > len(ctx.batch_invoice_ids):
                    return {
                        "text": f"序号超出范围，您当前共 {len(ctx.batch_invoice_ids)} 张发票。",
                        "data": {},
                    }
                invoice_id = ctx.batch_invoice_ids[idx - 1]
            except (ValueError, TypeError):
                return {"text": f"无法解析发票序号「{index_slot.value}」，请说「第2张」。", "data": {}}

        if not invoice_id:
            invoice_id = ctx.pending_invoice_id
        if not invoice_id:
            return {"text": "请先指定要修改的发票，例如「第一张发票的金额改成100」。", "data": {}}

        result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()
        if not invoice:
            return {"text": f"未找到发票 #{invoice_id}。", "data": {}}

        fn = field_name.value
        fv = field_value.value

        # 映射字段名到模型属性
        field_map = {
            "金额": "total_with_tax", "amount": "total_with_tax",
            "日期": "issue_date", "date": "issue_date",
            "销售方": "seller_name", "seller": "seller_name",
            "税号": "seller_tax_id", "tax_id": "seller_tax_id",
            "发票号": "invoice_number", "invoice_number": "invoice_number",
            "用途": "user_description", "description": "user_description",
            "备注": "user_description",
        }
        model_attr = field_map.get(fn.lower() if isinstance(fn, str) else fn, fn)

        if hasattr(invoice, model_attr):
            setattr(invoice, model_attr, fv)
            await db.commit()
            text = f"✅ 已将发票 #{invoice_id} 的{fn}修改为 {fv}。"
            # 仅返回本次修改的发票详情（场景B：单次操作）
            text += "\n\n" + self._build_single_invoice_table(invoice)
            return {"text": text, "data": {"invoice_id": invoice_id}}
        else:
            return {"text": f"不支持修改字段「{fn}」。可修改：金额、日期、销售方、税号、发票号、用途。", "data": {}}

    async def _handle_confirm_category(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """确认费用分类"""
        invoice_id = ctx.pending_invoice_id
        if not invoice_id:
            return {"text": "没有待确认分类的发票。", "data": {}}

        cat_slot = ctx.slots.get("category_selection")
        if not cat_slot or not cat_slot.filled:
            return {"text": "请回复数字选择费用分类。", "data": {}}

        result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()
        if not invoice:
            return {"text": f"未找到发票 #{invoice_id}。", "data": {}}

        # 简化处理：将用户输入作为子分类
        invoice.fee_subcategory = str(cat_slot.value)
        invoice.classify_source = "manual"
        invoice.status = InvoiceStatus.confirmed
        await db.commit()

        return {
            "text": f"✅ 发票 #{invoice_id} 的分类已确认为「{cat_slot.value}」，状态已更新为已确认。",
            "data": {"invoice_id": invoice_id},
        }

    async def _handle_confirm_project(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """确认项目归属"""
        invoice_id = ctx.pending_invoice_id
        if not invoice_id:
            return {"text": "没有待确认项目的发票。", "data": {}}

        proj_slot = ctx.slots.get("project_id")
        if not proj_slot or not proj_slot.filled:
            return {"text": "请回复数字选择项目。", "data": {}}

        result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()
        if not invoice:
            return {"text": f"未找到发票 #{invoice_id}。", "data": {}}

        try:
            project_id = int(proj_slot.value)
        except (ValueError, TypeError):
            return {"text": "项目编号应为数字，请重新选择。", "data": {}}

        invoice.project_id = project_id
        invoice.project_match_source = "manual"
        await db.commit()

        return {
            "text": f"✅ 发票 #{invoice_id} 的项目已关联（项目ID: {project_id}）。",
            "data": {"invoice_id": invoice_id, "project_id": project_id},
        }

    # ============================================================
    # 批量用途描述 + 批量修改（场景1 & 场景3）
    # ============================================================

    async def _handle_batch_describe(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """批量用途描述 — 用户一条说明为多张发票分配用途

        典型输入："前两张是差旅-交通，第三张是差旅-餐饮"
        核心逻辑：
        1. 读取用户描述文本（batch_description 槽位）
        2. 调用 LLM 拆解为每张发票的用途映射
        3. 逐张更新 user_description 字段
        """
        desc_slot = ctx.slots.get("batch_description")
        if not desc_slot or not desc_slot.filled:
            return {"text": "请描述各发票的用途。", "data": {}}

        if not ctx.batch_invoice_ids:
            return {"text": "您还没有上传任何发票，请先发送发票图片。", "data": {}}

        batch_desc = str(desc_slot.value)

        # 查询批量发票信息
        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(ctx.batch_invoice_ids))
        )
        invoices = list(result.scalars().all())
        if not invoices:
            return {"text": "批量列表中的发票不存在，可能已被处理。", "data": {}}

        # 构建 LLM 拆解请求
        invoice_brief = "\n".join(
            f"- #{inv.id}: {inv.seller_name or '未知'} | ¥{inv.total_with_tax or '未知'} | {inv.receipt_type.value if inv.receipt_type else '未知'}"
            for inv in invoices
        )

        try:
            from app.dialog.llm_nlu import get_llm_nlu
            nlu = get_llm_nlu()
            mapping = await nlu._call_llm_batch_describe(batch_desc, invoice_brief, len(invoices))
        except Exception as e:
            logger.warning("Batch describe LLM call failed: %s", e)
            mapping = None

        if not mapping:
            # LLM 拆解失败 → 回退为统一描述
            for inv in invoices:
                inv.user_description = batch_desc
            await db.commit()
            return {
                "text": f"已为所有 {len(invoices)} 张发票设置用途：{batch_desc}",
                "data": {"unified": True, "count": len(invoices)},
            }

        # 按映射逐张更新
        updated = 0
        unmapped = []
        for item in mapping:
            inv_id = item.get("invoice_id")
            desc = item.get("description", "")
            if inv_id and desc:
                inv = next((i for i in invoices if i.id == inv_id), None)
                if inv:
                    inv.user_description = desc
                    updated += 1
                else:
                    unmapped.append(inv_id)
            else:
                unmapped.append(inv_id)

        # 未映射到的发票统一设置描述
        for inv in invoices:
            if inv.id not in [item.get("invoice_id") for item in mapping if item.get("invoice_id")]:
                inv.user_description = batch_desc

        await db.commit()

        # 构建回复
        lines = [f"已为 {len(invoices)} 张发票分配用途：\n"]
        for inv in invoices:
            lines.append(f"  #{inv.id} → {inv.user_description or '未设置'}")

        md_table = await self._build_batch_summary_table(ctx, db)
        if md_table:
            lines.append("\n" + md_table)

        return {
            "text": "\n".join(lines),
            "data": {"updated": updated, "total": len(invoices)},
        }

    async def _handle_batch_modify(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """批量修改发票字段 — 用户一次描述多个字段修改

        典型输入："金额改为100，日期改为2026-08-01"
        核心逻辑：
        1. 读取用户修改描述（batch_modifications 槽位）
        2. 调用 LLM 解析为结构化字段修改列表
        3. 逐张更新指定字段
        """
        mod_slot = ctx.slots.get("batch_modifications")
        if not mod_slot or not mod_slot.filled:
            return {"text": "请描述要修改的内容。", "data": {}}

        if not ctx.batch_invoice_ids:
            return {"text": "您还没有上传任何发票，请先指定要修改的发票。", "data": {}}

        modification_text = str(mod_slot.value)

        # 查询批量发票
        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(ctx.batch_invoice_ids))
        )
        invoices = list(result.scalars().all())
        if not invoices:
            return {"text": "批量列表中的发票不存在。", "data": {}}

        # 字段名 → 模型属性映射
        field_map = {
            "金额": "total_with_tax", "amount": "total_with_tax",
            "日期": "issue_date", "date": "issue_date",
            "销售方": "seller_name", "seller": "seller_name",
            "税号": "seller_tax_id", "tax_id": "seller_tax_id",
            "发票号": "invoice_number", "invoice_number": "invoice_number",
        }

        # 解析修改指令 — 格式: "字段1=值1, 字段2=值2"
        # 支持自然语言：金额改为100 → field=金额, value=100
        try:
            modifications = await self._parse_batch_modifications(modification_text)
        except Exception as e:
            logger.warning("Batch modify parse failed: %s", e)
            return {"text": f"无法解析修改指令，请使用格式如「金额改为100，日期改为2026-08-01」。", "data": {}}

        if not modifications:
            return {"text": "未能识别到有效的修改内容。支持的修改字段：金额、日期、销售方、税号、发票号。", "data": {}}

        # 逐张更新
        updated_count = 0
        for inv in invoices:
            for field_name, field_value in modifications.items():
                model_attr = field_map.get(field_name.lower() if isinstance(field_name, str) else field_name, field_name)
                if hasattr(inv, model_attr):
                    setattr(inv, model_attr, field_value)
                    updated_count += 1

        await db.commit()

        text = f"已批量修改 {len(invoices)} 张发票，共 {updated_count} 处变更。\n\n"
        md_table = await self._build_batch_summary_table(ctx, db)
        if md_table:
            text += md_table
        else:
            for inv in invoices:
                seller = inv.seller_name or "未知"
                amount = inv.total_with_tax or "未知"
                text += f"  #{inv.id} | {seller} | ¥{amount}\n"

        return {
            "text": text,
            "data": {"updated_invoices": len(invoices), "updated_fields": updated_count},
        }

    async def _parse_batch_modifications(self, text: str) -> dict[str, str]:
        """解析批量修改指令为字段映射

        策略：
        1. 正则 fast-path：覆盖常见固定句式，零 LLM 成本。
        2. LLM fallback：处理自然语言变体，如"把金额改成一百块"。

        支持的格式:
        - "金额改为100, 日期改为2026-08-01"
        - "金额=100, 日期=2026-08-01"
        - "把销售方改成XX公司, 税号改成123"
        - "把金额改成一百块，日期调到8月1号"
        """
        text = (text or "").strip()
        if not text:
            return {}

        allowed_fields = {
            "金额", "amount", "日期", "date",
            "销售方", "seller", "税号", "tax_id",
            "发票号", "invoice_number",
        }
        modifications: dict[str, str] = {}

        # 1. 正则 fast-path：固定句式快速解析
        parts = re.split(r'[,，;；\n]', text)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            m = re.match(
                r'(金额|日期|销售方|税号|发票号|amount|date|seller|tax_id|invoice_number)'
                r'\s*(?:改为|改成|更改为|=|→)\s*(.+)',
                part,
                re.IGNORECASE,
            )
            if m:
                modifications[m.group(1).lower()] = m.group(2).strip()

        if modifications:
            return modifications

        # 2. LLM fallback：自然语言变体解析
        from app.services.llm_service import get_llm_service
        llm = get_llm_service()
        if not llm.is_available():
            logger.warning("LLM unavailable for batch modification parsing")
            return {}

        current_year = date.today().year
        prompt = (
            "你是发票字段修改解析助手。请将用户的修改描述解析为字段修改列表。\n\n"
            f"当前年份为 {current_year}。\n"
            "只允许修改以下字段：金额(amount)、日期(date)、销售方(seller)、税号(tax_id)、发票号(invoice_number)。\n\n"
            "输出严格 JSON 数组，每项包含：\n"
            '  - "field": 字段名（使用上面列表中的中文或英文名称）\n'
            '  - "value": 修改后的值。日期请标准化为 YYYY-MM-DD 格式；金额只保留数字和小数点。\n\n'
            "示例：\n"
            '输入：把金额改成一百块，日期调到8月1号\n'
            '输出：[{"field": "金额", "value": "100"}, {"field": "日期", "value": "' + str(current_year) + '-08-01"}]\n\n'
            '输入：销售方换成 ABC 公司，税号改为 91110000XXXX\n'
            '输出：[{"field": "销售方", "value": "ABC公司"}, {"field": "税号", "value": "91110000XXXX"}]\n\n'
            f"输入：{text}\n"
            "只输出 JSON 数组，不要任何其他文字。"
        )

        try:
            resp = await llm.client.chat.completions.create(
                model=settings.get_model_for_task("fee_classify"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=256,
            )
            content = resp.choices[0].message.content.strip()
            result = json.loads(content)
            items = result if isinstance(result, list) else result.get("modifications", [])

            for item in items:
                if not isinstance(item, dict):
                    continue
                field = str(item.get("field", "")).strip().lower()
                value = str(item.get("value", "")).strip()
                if field and value and field in allowed_fields:
                    modifications[field] = value

            if modifications:
                logger.info(
                    "Batch modification parsed by LLM: text=%r modifications=%s",
                    text[:50], list(modifications.keys()),
                )
        except json.JSONDecodeError as e:
            logger.warning("Batch modification LLM response is not valid JSON: %s content=%r", e, content[:200])
        except Exception as e:
            logger.warning("Batch modification LLM parse failed: %s", e)

        return modifications

    async def _parse_batch_description(
        self, text: str, existing_count: int = 0
    ) -> dict[int, str]:
        """用 LLM 理解用户自然语言描述，拆分为 {0-based全局索引: 描述} 映射

        覆盖各种自然语言表达：
        - "第一张是餐饮费、第二张是打车费"
        - "这两张都是 办公用品采购"（"这两张"指当前批次的新两张）
        - "前两张是交通费，第三张是餐费"
        - "打车费, 快递费" (按顺序分配)
        - "去机场打车" (单张，不拆分)

        Args:
            text: 用户输入的描述文本
            existing_count: 之前已上传且已描述过的发票数量（用于"这两张"等相对指代的偏移）

        Returns:
            dict[int, str]: {0-based全局索引: 描述} 映射，空dict表示未检测到批量描述
        """
        text = (text or "").strip()
        if not text:
            return {}

        from app.services.llm_service import get_llm_service
        llm = get_llm_service()
        if not llm.is_available():
            logger.warning("LLM unavailable, cannot parse batch description")
            return {}

        # 序号偏移说明：若已有 existing_count 张，"第一张/这两张"等指代从 existing_count+1 开始
        offset_hint = ""
        if existing_count > 0:
            offset_hint = (
                f"\n注意：用户之前已上传 {existing_count} 张发票并已说明用途。"
                f"本次说明中的'第一张'、'这两张'、'前两张'等指代指的是"
                f"第 {existing_count + 1} 张起的新发票（即本次新上传的发票）。"
            )

        prompt = (
            "你是发票报销助手。用户正在批量上传发票，并给出一段说明。"
            "请把说明拆分为每张发票对应的用途描述。\n\n"
            "规则：\n"
            "1. 输出 JSON 对象，key 为发票序号（从 1 开始的字符串，仅指本次说明覆盖的发票），"
            "value 为该张发票的用途描述（字符串）。\n"
            "2. 若说明只描述一种用途且适用于多张发票（如'这两张都是办公用品'），"
            "则为涉及的每张都填入该用途。\n"
            "3. 若说明只针对部分发票，仅填入能确定的序号；其余不要出现。\n"
            "4. 用途描述要简洁（保留用户原话），不要添加额外解释。\n"
            "5. 若说明与发票用途无关或无法理解，返回空对象 {{}}。\n"
            "6. 若说明只描述单一用途且无'第N张/这两张/前N张'等批量指代，返回空对象 {{}}。\n"
            "{offset_hint}\n\n"
            "示例：\n"
            "输入: text='第一张是餐饮费、第二张是打车费', 已有=0\n"
            "输出: {{\"1\": \"餐饮费\", \"2\": \"打车费\"}}\n\n"
            "输入: text='这两张都是 办公用品采购', 已有=0\n"
            "输出: {{\"1\": \"办公用品采购\", \"2\": \"办公用品采购\"}}\n\n"
            "输入: text='这两张都是 办公用品采购', 已有=2\n"
            "输出: {{\"1\": \"办公用品采购\", \"2\": \"办公用品采购\"}}\n"
            "（'这两张'指本次新上传的两张，序号仍从1开始）\n\n"
            "输入: text='前两张是交通费，第三张是餐费', 已有=0\n"
            "输出: {{\"1\": \"交通费\", \"2\": \"交通费\", \"3\": \"餐费\"}}\n\n"
            "输入: text='打车费, 快递费', 已有=0\n"
            "输出: {{\"1\": \"打车费\", \"2\": \"快递费\"}}\n\n"
            "输入: text='去机场打车', 已有=0\n"
            "输出: {{}}\n\n"
            "现在处理：\n"
            "text: {text}\n"
            "已有: {existing}\n"
            "请直接输出 JSON，不要任何额外文字。"
        ).format(text=text, offset_hint=offset_hint, existing=existing_count)

        try:
            response = await llm.client.chat.completions.create(
                model=settings.get_model_for_task("fee_classify"),  # 短文本理解，路由到快模型
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=300,
            )
            content = response.choices[0].message.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            import json as _json
            parsed = _json.loads(content)
            result: dict[int, str] = {}
            for k, v in parsed.items():
                try:
                    idx = int(k)
                except (ValueError, TypeError):
                    continue
                # LLM 返回的 idx 是本次批次的局部序号（从1开始）
                # 转换为全局索引：existing_count + (idx - 1)
                if idx >= 1 and isinstance(v, str) and v.strip():
                    global_idx = existing_count + (idx - 1)
                    result[global_idx] = v.strip()



            # 仅当解析出至少 2 张发票的描述时，才视为批量描述
            # （单张描述不能构成"批量"，应让上层走普通用途流程）
            if len(result) >= 2:
                logger.info(f"LLM parsed batch description: {result}")
                return result
            logger.info(f"LLM batch parse result too small ({len(result)}), treating as non-batch: {result}")
            return {}
        except Exception as e:
            logger.error(f"LLM batch description parse failed: {e}")
            return {}


    async def _build_batch_invoice_summaries(
        self, ctx: DialogContext, db: AsyncSession
    ) -> list[dict]:
        """构建当前批量发票的可识别摘要列表

        返回每项包含：index（1-based）、id、seller_name、total_with_tax、
        receipt_type、issue_date，供前端在追问用途时展示。
        """
        if not ctx.batch_invoice_ids:
            return []

        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(ctx.batch_invoice_ids))
        )
        invoice_map = {inv.id: inv for inv in result.scalars().all()}

        summaries: list[dict] = []
        for idx, inv_id in enumerate(ctx.batch_invoice_ids, start=1):
            inv = invoice_map.get(inv_id)
            if not inv:
                continue
            summaries.append({
                "index": idx,
                "id": inv.id,
                "seller_name": inv.seller_name or "未知",
                "total_with_tax": str(inv.total_with_tax or "—"),
                "receipt_type": inv.receipt_type.value if inv.receipt_type else "未知",
                "issue_date": inv.issue_date or "—",
            })
        return summaries

    async def _build_batch_summary_table(
        self, ctx: DialogContext, db: AsyncSession
    ) -> str:
        """构建当前批量发票的 Markdown 汇总表格（场景3：表格确认）

        返回空字符串表示无发票可展示。
        """
        if not ctx.batch_invoice_ids:
            return ""

        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(ctx.batch_invoice_ids))
        )
        invoices = list(result.scalars().all())
        if not invoices:
            return ""

        lines = [
            "| 序号 | 类型 | 销售方 | 金额 | 用途 | 出差日期 | 上传时间 |",
            "|------|------|--------|------|------|----------|----------|",
        ]
        for idx, inv in enumerate(invoices, 1):
            rt = inv.receipt_type.value if inv.receipt_type else "未知"
            seller = (inv.seller_name or "未知")[:10]
            amount = f"¥{inv.total_with_tax or '—'}"
            desc = (inv.user_description or "待补充")[:12]
            expense_date = str(inv.expense_date) if inv.expense_date else "—"
            created = inv.created_at.strftime("%Y-%m-%d %H:%M") if inv.created_at else "—"
            lines.append(f"| {idx} | {rt} | {seller} | {amount} | {desc} | {expense_date} | {created} |")

        # 合计行
        total = 0.0
        for inv in invoices:
            try:
                total += self._safe_amount(inv.total_with_tax)
            except (ValueError, TypeError):
                pass
        lines.append(f"| **合计** | | | **¥{total:.2f}** | {len(invoices)}张 | | |")

        return "\n".join(lines)

    async def _build_user_pending_invoices_table(
        self, db: AsyncSession, user_id: str
    ) -> str:
        """构建指定用户未提交发票的 Markdown 表格

        用于发票修改/删除等操作后展示当前未提交票据列表。
        未提交 = reimbursement_id 为空 且 状态在 uploaded/reviewing/confirmed。
        返回空字符串表示无未提交发票。
        """
        result = await db.execute(
            select(Invoice).where(
                Invoice.user_id == user_id,
                Invoice.reimbursement_id.is_(None),
                Invoice.status.in_([
                    InvoiceStatus.confirmed,
                    InvoiceStatus.reviewing,
                    InvoiceStatus.uploaded,
                ]),
            ).order_by(Invoice.created_at.asc())
        )
        invoices = list(result.scalars().all())
        if not invoices:
            return ""

        lines = [
            "| 序号 | 类型 | 销售方 | 金额 | 用途 | 出差日期 | 上传时间 |",
            "|------|------|--------|------|------|----------|----------|",
        ]
        total = 0.0
        for idx, inv in enumerate(invoices, 1):
            rt = inv.receipt_type.value if inv.receipt_type else "未知"
            seller = (inv.seller_name or "无票报销")[:10]
            amount_str = inv.total_with_tax or "—"
            try:
                total += self._safe_amount(inv.total_with_tax)
            except (ValueError, TypeError):
                pass
            desc = (inv.user_description or "待补充")[:12]
            expense_date = str(inv.expense_date) if inv.expense_date else "—"
            created = inv.created_at.strftime("%Y-%m-%d %H:%M") if inv.created_at else "—"
            lines.append(f"| {idx} | {rt} | {seller} | ¥{amount_str} | {desc} | {expense_date} | {created} |")

        lines.append(f"| **合计** | | | **¥{total:.2f}** | {len(invoices)}张 | | |")
        return "\n".join(lines)

    async def _build_user_invoices_table(
        self, db: AsyncSession, user_id: str, limit: int = 20
    ) -> str:
        """构建指定用户全部发票的 Markdown 表格（含状态列）

        用于查询发票场景。按创建时间倒序，最多展示 limit 条。
        返回空字符串表示无发票。
        """
        result = await db.execute(
            select(Invoice)
            .where(Invoice.user_id == user_id)
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
        invoices = list(result.scalars().all())
        if not invoices:
            return ""

        lines = [
            "| 序号 | 类型 | 销售方 | 金额 | 用途 | 出差日期 | 状态 | 上传时间 |",
            "|------|------|--------|------|------|----------|------|----------|",
        ]
        total = 0.0
        for idx, inv in enumerate(invoices, 1):
            rt = inv.receipt_type.value if inv.receipt_type else "未知"
            seller = (inv.seller_name or "无票报销")[:10]
            amount_str = inv.total_with_tax or "—"
            try:
                total += self._safe_amount(inv.total_with_tax)
            except (ValueError, TypeError):
                pass
            desc = (inv.user_description or "待补充")[:12]
            expense_date = str(inv.expense_date) if inv.expense_date else "—"
            status = self._status_text(inv)
            created = inv.created_at.strftime("%Y-%m-%d %H:%M") if inv.created_at else "—"
            lines.append(f"| {idx} | {rt} | {seller} | ¥{amount_str} | {desc} | {expense_date} | {status} | {created} |")

        lines.append(f"| **合计** | | | **¥{total:.2f}** | {len(invoices)}张 | | | |")
        return "\n".join(lines)

    def _build_single_invoice_table(self, invoice: Invoice) -> str:
        """构建单张发票详情的 Markdown 表格（纵向，项目|内容格式）

        用于上传/修改等单次操作场景，仅展示本次操作的发票详情。
        """
        rows = [
            ("发票编号", f"#{invoice.id}"),
            ("发票类型", invoice.receipt_type.value if invoice.receipt_type else "未知"),
            ("单号", invoice.invoice_number or "—"),
            ("销售方", invoice.seller_name or "未知"),
            ("金额（含税）", f"¥{invoice.total_with_tax or '—'}"),
            ("税额", f"¥{invoice.tax_amount or '—'}"),
            ("开票时间", invoice.issue_date or "—"),
            ("出差日期", invoice.expense_date or "待补充"),
            ("费用分类", invoice.fee_subcategory or "—"),
            ("用途", invoice.user_description or "待补充"),
            ("状态", f"{self._status_emoji(invoice)} {self._status_text(invoice)}"),
            ("验真", f"{self._verify_emoji(invoice)} {self._verify_text(invoice)}"),
        ]
        lines = ["| 项目 | 内容 |", "|------|------|"]
        for label, value in rows:
            lines.append(f"| {label} | {value} |")
        return "\n".join(lines)

    # ============================================================
    # 查询类
    # ============================================================

    async def _handle_permission_denied(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """员工越权查询拦截 — 由 LLM 判定后调用，统一回复无权限"""
        return {"text": "没有权限，只能看本人的信息。", "data": {"permission_denied": True}}

    async def _handle_query_invoices(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询用户发票列表（仅展示识别完成的发票，排除 processing 脏数据）"""
        result = await db.execute(
            select(Invoice)
            .where(
                Invoice.user_id == ctx.user_id,
                Invoice.status != InvoiceStatus.processing,
            )
            .order_by(Invoice.created_at.desc())
            .limit(20)
        )
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": "您还没有上传过发票。发送图片即可上传。", "data": {"count": 0}}

        total_amount = 0.0
        for inv in invoices:
            try:
                total_amount += self._safe_amount(inv.total_with_tax)
            except (ValueError, TypeError):
                pass

        header = f"📋 您的发票列表（共 {len(invoices)} 张，合计 ¥{total_amount:.2f}）"
        table = await self._build_user_invoices_table(db, ctx.user_id)
        text = header + "\n\n" + table if table else header

        return {"text": text, "data": {"count": len(invoices), "total": total_amount}}

    async def _handle_query_status(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询报销进度"""
        result = await db.execute(
            select(Reimbursement)
            .where(Reimbursement.applicant_id == ctx.user_id)
            .order_by(Reimbursement.created_at.desc())
            .limit(5)
        )
        reimbursements = list(result.scalars().all())

        if not reimbursements:
            return {"text": "您还没有报销单记录。", "data": {"count": 0}}

        status_map = {
            ReimbursementStatus.draft: "📝 草稿",
            ReimbursementStatus.submitted: "⏳ 已提交（等待审批）",
            ReimbursementStatus.reviewed: "✅ 已审核",
            ReimbursementStatus.reimbursed: "💰 已报销",
        }

        lines = [f"📋 您的报销单（最近 {len(reimbursements)} 条）\n"]
        for r in reimbursements:
            status_text = status_map.get(r.status, r.status.value)
            amount = f"¥{r.total_amount:.2f}" if r.total_amount else "金额计算中"
            lines.append(f"  #{r.id} | {amount} | {status_text}")
            lines.append(f"    事由：{r.reason or '—'}")
            lines.append(f"    时间：{r.created_at}")
            lines.append("")

        return {"text": "\n".join(lines), "data": {"count": len(reimbursements)}}

    async def _handle_self_pending(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询本人未提交票据"""
        result = await db.execute(
            select(Invoice).where(
                Invoice.user_id == ctx.user_id,
                Invoice.reimbursement_id.is_(None),
                Invoice.status.in_([
                    InvoiceStatus.confirmed,
                    InvoiceStatus.reviewing,
                    InvoiceStatus.uploaded,
                ]),
            ).order_by(Invoice.created_at.desc())
        )
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": "✅ 您没有未提交的票据，全部已关联报销单。", "data": {"count": 0}}

        total = 0.0
        for inv in invoices:
            try:
                total += self._safe_amount(inv.total_with_tax)
            except (ValueError, TypeError):
                pass

        lines = [f"📋 未提交票据（{len(invoices)} 张，合计 ¥{total:.2f}）\n"]
        for inv in invoices[:10]:
            seller = inv.seller_name or "无票报销"
            amount = inv.total_with_tax or "—"
            lines.append(f"  #{inv.id} | {seller} | ¥{amount} | {self._status_text(inv)}")

        if ctx.role == UserRole.EMPLOYEE:
            lines.append("\n报销单将按周期自动生成与归集。")
        else:
            lines.append(f"\n输入「完成」可提交报销。")
        return {"text": "\n".join(lines), "data": {"count": len(invoices), "total": total}}

    # ============================================================
    # 管理员操作
    # ============================================================

    async def _handle_admin_approve(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """审核通过发票"""
        reimb_id = None

        # 1. 尝试 reimbursement_id 槽位
        reimb_id_slot = ctx.slots.get("reimbursement_id")
        if reimb_id_slot and reimb_id_slot.filled:
            try:
                reimb_id = int(reimb_id_slot.value)
            except (ValueError, TypeError):
                # reimbursement_id 不是数字 → 尝试按姓名消歧
                name = str(reimb_id_slot.value)
                reimb_id, disambig = await self._resolve_reimbursement_by_person(
                    db, name, status_filter=ReimbursementStatus.submitted,
                )
                if disambig:
                    return {"text": disambig, "data": {}}
                if reimb_id is None:
                    return {"text": f"未找到与「{name}」相关的待审批报销单。", "data": {}}

        # 2. reimbursement_id 未提供 → 尝试 person 槽位
        if reimb_id is None:
            person_slot = ctx.slots.get("person")
            if person_slot and person_slot.filled and person_slot.value:
                name = str(person_slot.value)
                reimb_id, disambig = await self._resolve_reimbursement_by_person(
                    db, name, status_filter=ReimbursementStatus.submitted,
                )
                if disambig:
                    return {"text": disambig, "data": {}}
                if reimb_id is None:
                    return {"text": f"未找到与「{name}」相关的待审批报销单。", "data": {}}

        # 3. 两个槽位都未提供
        if reimb_id is None:
            return {"text": "请指定要批准的报销单编号，或告诉我申请人姓名（如「批准陈辉的报销」）。", "data": {}}

        # 查找报销单关联的发票
        result = await db.execute(
            select(Invoice).where(Invoice.reimbursement_id == reimb_id)
        )
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": f"报销单 #{reimb_id} 没有关联发票。", "data": {}}

        approved = 0
        for inv in invoices:
            if inv.status == InvoiceStatus.reviewing:
                inv.status = InvoiceStatus.confirmed
                approved += 1

        # 更新报销单状态
        reimb = await get_reimbursement_or_404(db, reimb_id)
        if reimb.status == ReimbursementStatus.submitted:
            reimb.status = ReimbursementStatus.reviewed
        await db.commit()

        return {
            "text": f"✅ 报销单 #{reimb_id} 已审核通过\n"
                    f"批准发票：{approved} 张\n"
                    f"报销单状态：已审核",
            "data": {"reimbursement_id": reimb_id, "approved_count": approved},
        }

    async def _handle_admin_reject(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """审核驳回发票"""
        reimb_id_slot = ctx.slots.get("reimbursement_id")
        if not reimb_id_slot or not reimb_id_slot.filled:
            return {"text": "请指定要驳回的报销单编号。", "data": {}}

        try:
            reimb_id = int(reimb_id_slot.value)
        except (ValueError, TypeError):
            return {"text": "请输入正确的报销单编号（数字）。", "data": {}}

        result = await db.execute(
            select(Invoice).where(Invoice.reimbursement_id == reimb_id)
        )
        invoices = list(result.scalars().all())

        rejected = 0
        for inv in invoices:
            if inv.status == InvoiceStatus.reviewing:
                inv.status = InvoiceStatus.not_reimbursed
                rejected += 1

        reimb = await get_reimbursement_or_404(db, reimb_id)
        reason_slot = ctx.slots.get("reason")
        reason = reason_slot.value if reason_slot and reason_slot.filled else "管理员驳回"
        if reimb.status == ReimbursementStatus.submitted:
            reimb.status = ReimbursementStatus.draft
        await db.commit()

        return {
            "text": f"❌ 报销单 #{reimb_id} 已驳回\n"
                    f"驳回发票：{rejected} 张\n"
                    f"驳回原因：{reason}",
            "data": {"reimbursement_id": reimb_id, "rejected_count": rejected},
        }

    async def _handle_admin_pending(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询待审批报销单"""
        result = await db.execute(
            select(Reimbursement)
            .where(Reimbursement.status == ReimbursementStatus.submitted)
            .order_by(Reimbursement.submitted_at.desc().nullslast())
            .limit(20)
        )
        reimbursements = list(result.scalars().all())

        if not reimbursements:
            return {"text": "✅ 当前没有待审批的报销单。", "data": {"count": 0}}

        lines = [f"📋 待审批报销单（{len(reimbursements)} 条）\n"]
        for r in reimbursements:
            amount = f"¥{r.total_amount:.2f}" if r.total_amount else "—"
            lines.append(f"  #{r.id} | {r.applicant_name or r.applicant_id} | {amount}")
            lines.append(f"    事由：{r.reason or '—'}")
            lines.append(f"    提交时间：{r.submitted_at or r.created_at}")
            lines.append("")

        lines.append("输入「批准报销单XXX」或「驳回报销单XXX」进行审批。")
        return {"text": "\n".join(lines), "data": {"count": len(reimbursements)}}

    async def _handle_admin_detail(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询报销单详情"""
        reimb_id_slot = ctx.slots.get("reimbursement_id")
        if not reimb_id_slot or not reimb_id_slot.filled:
            return {"text": "请指定要查看的报销单编号。", "data": {}}

        try:
            reimb_id = int(reimb_id_slot.value)
        except (ValueError, TypeError):
            return {"text": "报销单编号应为数字。", "data": {}}

        reimb = await get_reimbursement_or_404(db, reimb_id)

        result = await db.execute(
            select(Invoice).where(Invoice.reimbursement_id == reimb_id)
        )
        invoices = list(result.scalars().all())

        status_map = {
            ReimbursementStatus.draft: "草稿",
            ReimbursementStatus.submitted: "已提交",
            ReimbursementStatus.reviewed: "已审核",
            ReimbursementStatus.reimbursed: "已报销",
        }

        lines = [
            f"📋 报销单 #{reimb.id} 详情\n",
            f"👤 申请人：{reimb.applicant_name or reimb.applicant_id}",
            f"🏢 部门：{reimb.department or '—'}",
            f"📝 事由：{reimb.reason or '—'}",
            f"💰 总金额：¥{reimb.total_amount:.2f}" if reimb.total_amount else "💰 总金额：计算中",
            f"📊 状态：{status_map.get(reimb.status, reimb.status.value)}",
            f"📅 创建时间：{reimb.created_at}",
            f"\n📦 关联发票（{len(invoices)} 张）：",
        ]

        for inv in invoices:
            seller = inv.seller_name or "无票"
            amount = inv.total_with_tax or "—"
            lines.append(f"  #{inv.id} | {seller} | ¥{amount}")

        return {"text": "\n".join(lines), "data": {"reimbursement_id": reimb_id}}

    # ============================================================
    # 报销周期查询
    # ============================================================

    @staticmethod
    def _resolve_cycle_key(period_val: str | None) -> str:
        """将 period 槽位值解析为报销周期 cycle_key (YYYY-MM)

        支持的输入：
        - YYYY-MM 格式（如 "2026-07"）→ 直接使用
        - current_month / 本月 → 当前周期
        - last_month / 上月 → 上一周期
        - 其他 → 当前周期（兜底）
        """
        if not period_val:
            return current_cycle_key()
        if re.match(r'^\d{4}-\d{2}$', period_val):
            return period_val
        if period_val in ("last_month",):
            curr = current_cycle_key()
            y, m = map(int, curr.split("-"))
            return (date(y, m, 1) - relativedelta(months=1)).strftime("%Y-%m")
        # current_month 或无法识别 → 当前周期
        return current_cycle_key()

    async def _handle_query_my_reimbursement(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询本人报销单列表（含报销周期、费用/补贴明细、封账状态）"""
        query = select(Reimbursement).where(
            Reimbursement.applicant_id == ctx.user_id
        )

        # 可选：按周期筛选
        period_slot = ctx.slots.get("period")
        period_val = period_slot.value if period_slot and period_slot.filled else None
        filter_ck = self._resolve_cycle_key(period_val) if period_val else None
        if filter_ck and period_val:
            query = query.where(Reimbursement.cycle_key == filter_ck)

        query = query.order_by(Reimbursement.created_at.desc()).limit(10)
        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            if filter_ck and period_val:
                return {
                    "text": f"您在周期（{cycle_display(filter_ck)}）暂无报销单记录。",
                    "data": {"count": 0},
                }
            return {"text": "您还没有报销单记录。", "data": {"count": 0}}

        status_map = {
            ReimbursementStatus.draft: "📝 草稿",
            ReimbursementStatus.submitted: "⏳ 待审批",
            ReimbursementStatus.reviewed: "✅ 已审核",
            ReimbursementStatus.reimbursed: "💰 已报销",
        }

        lines = [f"📋 您的报销单（最近 {len(reimbs)} 条）\n"]
        for r in reimbs:
            status_text = status_map.get(r.status, r.status.value)
            lock_icon = "🔒" if r.is_cycle_locked else "🔓"

            if r.cycle_key:
                cycle_str = cycle_display(r.cycle_key)
            else:
                cycle_str = "—"

            exp = r.expense_total or 0.0
            sub = r.subsidy_total or 0.0
            total = r.total_amount or (exp + sub)

            lines.append(f"  #{r.id} | {status_text} {lock_icon}")
            lines.append(f"    周期：{cycle_str}")
            lines.append(f"    费用：¥{exp:,.2f} | 补贴：¥{sub:,.2f} | 合计：¥{total:,.2f}")
            lines.append("")

        return {"text": "\n".join(lines), "data": {"count": len(reimbs)}}

    async def _handle_admin_cycle_summary(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询某报销周期汇总（报销单数、费用/补贴分拆、封账状态、各申请人明细）"""
        # 解析周期 cycle_key
        period_slot = ctx.slots.get("period")
        period_val = period_slot.value if period_slot and period_slot.filled else None
        ck = self._resolve_cycle_key(period_val)
        cycle_str = cycle_display(ck)

        # 查询该周期所有报销单
        result = await db.execute(
            select(Reimbursement)
            .where(Reimbursement.cycle_key == ck)
            .order_by(Reimbursement.applicant_name.nullslast())
        )
        reimbs = list(result.scalars().all())

        if not reimbs:
            return {
                "text": f"📋 周期汇总（{cycle_str}）\n\n暂无报销单记录。",
                "data": {"cycle_key": ck, "count": 0},
            }

        total_expense = sum(r.expense_total or 0.0 for r in reimbs)
        total_subsidy = sum(r.subsidy_total or 0.0 for r in reimbs)
        total_amount = sum(r.total_amount or 0.0 for r in reimbs)
        is_locked = any(r.is_cycle_locked for r in reimbs)

        status_map = {
            ReimbursementStatus.draft: "草稿",
            ReimbursementStatus.submitted: "待审批",
            ReimbursementStatus.reviewed: "已审核",
            ReimbursementStatus.reimbursed: "已报销",
        }

        lock_text = "🔒 已封账" if is_locked else "🔓 未封账"

        lines = [f"📋 周期汇总（{cycle_str}）{lock_text}\n"]
        lines.append(f"📊 报销单数：{len(reimbs)} 笔")
        lines.append(f"💰 费用合计：¥{total_expense:,.2f}")
        lines.append(f"🚗 补贴合计：¥{total_subsidy:,.2f}")
        lines.append(f"💵 总金额：¥{total_amount:,.2f}")
        lines.append(f"\n📋 各申请人明细：")

        for r in reimbs:
            status_text = status_map.get(r.status, r.status.value)
            exp = r.expense_total or 0.0
            sub = r.subsidy_total or 0.0
            total = r.total_amount or (exp + sub)
            name = r.applicant_name or r.applicant_id
            lines.append(f"  #{r.id} | {name} | {status_text}")
            lines.append(f"    费用 ¥{exp:,.2f} | 补贴 ¥{sub:,.2f} | 合计 ¥{total:,.2f}")

        return {
            "text": "\n".join(lines),
            "data": {
                "cycle_key": ck,
                "count": len(reimbs),
                "total_expense": total_expense,
                "total_subsidy": total_subsidy,
                "total_amount": total_amount,
                "is_locked": is_locked,
            },
        }

    async def _handle_admin_mark_reimbursed(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """标记已审核报销单为已打款（REVIEWED → REIMBURSED）"""
        reimb_id = None

        # 1. 尝试 reimbursement_id 槽位
        reimb_id_slot = ctx.slots.get("reimbursement_id")
        if reimb_id_slot and reimb_id_slot.filled:
            try:
                reimb_id = int(reimb_id_slot.value)
            except (ValueError, TypeError):
                # 按姓名/工号消歧查找（打款操作不允许静默取首条）
                name = str(reimb_id_slot.value)
                reimb_id, disambig = await self._resolve_reimbursement_by_person(
                    db, name, status_filter=ReimbursementStatus.reviewed,
                )
                if disambig:
                    return {"text": disambig, "data": {}}
                if reimb_id is None:
                    return {"text": f"未找到与「{name}」相关的已审核报销单。", "data": {}}

        # 2. reimbursement_id 未提供 → 尝试 person 槽位
        if reimb_id is None:
            person_slot = ctx.slots.get("person")
            if person_slot and person_slot.filled and person_slot.value:
                name = str(person_slot.value)
                reimb_id, disambig = await self._resolve_reimbursement_by_person(
                    db, name, status_filter=ReimbursementStatus.reviewed,
                )
                if disambig:
                    return {"text": disambig, "data": {}}
                if reimb_id is None:
                    return {"text": f"未找到与「{name}」相关的已审核报销单。", "data": {}}

        # 3. 两个槽位都未提供
        if reimb_id is None:
            return {"text": "请指定要标记打款的报销单编号，或告诉我申请人姓名（如「给陈辉打款」）。", "data": {}}

        # 查找报销单
        result = await db.execute(
            select(Reimbursement).where(Reimbursement.id == reimb_id)
        )
        reimb = result.scalar_one_or_none()
        if not reimb:
            return {"text": f"报销单 #{reimb_id} 不存在。", "data": {}}

        if reimb.status != ReimbursementStatus.reviewed:
            status_names = {
                ReimbursementStatus.draft: "草稿",
                ReimbursementStatus.submitted: "待审批",
                ReimbursementStatus.reviewed: "已审核",
                ReimbursementStatus.reimbursed: "已报销",
            }
            current = status_names.get(reimb.status, reimb.status.value)
            return {
                "text": f"报销单 #{reimb_id} 状态为「{current}」，仅已审核状态可标记打款。",
                "data": {"reimbursement_id": reimb_id, "current_status": reimb.status.value},
            }

        # 执行状态流转
        from app.services.reimbursement_service import mark_reimbursed
        reimb = await mark_reimbursed(db, reimb_id)

        return {
            "text": f"💰 报销单 #{reimb_id} 已标记为已打款\n"
                    f"申请人：{reimb.applicant_name or reimb.applicant_id}\n"
                    f"金额：¥{reimb.total_amount or 0:,.2f}\n"
                    f"状态：已报销",
            "data": {"reimbursement_id": reimb_id, "new_status": "REIMBURSED"},
        }

    async def _handle_admin_aggregate_invoices(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """批量归集游离发票到报销单（管理员触发）

        支持 person 槽位（姓名/工号/用户ID），NLU 只提取 person，
        这里通过 resolve_person 统一解析为 user_ids 列表。
        传完整列表（employee_no + wecom_user_id）给 aggregate_pending_invoices，
        避免取 user_ids[0] 时因 set→list 顺序不确定而漏匹配。
        """
        resolved_user_ids = None
        real_name = None
        person_slot = ctx.slots.get("person")
        if person_slot and person_slot.filled and person_slot.value:
            person_val = str(person_slot.value).strip()
            from app.dialog.insight_engine import resolve_person
            resolution = await resolve_person(person_val, db, table_hint="invoice")

            if resolution.match_type == "not_found":
                return {"text": f"未找到员工「{person_val}」，请确认姓名或工号。", "data": {}}

            if resolution.match_type == "disambiguate" and len(resolution.user_ids) != 1:
                from app.dialog.insight_engine import _format_disambiguation_prompt
                return {
                    "text": _format_disambiguation_prompt(resolution.candidates),
                    "data": {"candidates": resolution.candidates},
                }

            # exact 或唯一 disambiguate — 保留全部 user_ids（兼容 wecom_user_id 和工号）
            if resolution.user_ids:
                resolved_user_ids = resolution.user_ids
                real_name = resolution.display_name

        from app.services.aggregation_service import aggregate_pending_invoices
        result = await aggregate_pending_invoices(db, user_ids=resolved_user_ids)

        if result["total"] == 0:
            scope = f"员工「{real_name}」的" if resolved_user_ids else "全公司的"
            return {
                "text": f"没有需要归集的{scope}游离发票。所有发票已关联报销单。",
                "data": result,
            }

        scope = f"员工「{real_name}」" if resolved_user_ids else "全公司"
        parts = [
            f"📦 {scope}游离发票归集完成",
            f"归集发票：{result['attached']}/{result['total']} 张",
            f"生成/更新报销单：{len(result['reimb_ids'])} 份",
        ]
        if result["errors"]:
            parts.append(f"失败：{len(result['errors'])} 张")
        if result["reimb_ids"]:
            parts.append(f"报销单编号：{', '.join(f'#{r}' for r in result['reimb_ids'])}")

        return {
            "text": "\n".join(parts),
            "data": result,
        }

    # ============================================================
    # 人名 → 报销单（消歧版） — 批准/驳回/打款等敏感操作专用
    # ============================================================

    async def _resolve_reimbursement_by_person(
        self,
        db: AsyncSession,
        person_value: str,
        *,
        status_filter: Optional[ReimbursementStatus] = None,
    ) -> tuple[Optional[int], Optional[str]]:
        """按人名/工号解析为唯一的报销单 ID（不做静默取首条）

        匹配策略同 resolve_person：
        - 精确== 后模糊 contains，匹配到唯一员工 → 进一步查该员工报销单
        - 多候选 → 返回消歧提示文本（reimb_id 为 None）
        - 找到多人报销单 → 同样返回消歧提示

        Args:
            status_filter: 可选，筛选报销单状态（如 submitted / reviewed）

        Returns: (reimb_id, disambiguation_text)
            - 命中唯一报销单 → (id, None)
            - 多候选需消歧   → (None, 反问文案)
            - 完全无匹配     → (None, None)
        """
        from app.dialog.insight_engine import resolve_person, _format_disambiguation_prompt

        resolution = await resolve_person(person_value, db, table_hint="reimbursement")

        if resolution.match_type == "not_found":
            return (None, None)

        if resolution.match_type == "disambiguate":
            return (None, _format_disambiguation_prompt(resolution.candidates))

        # 唯一候选人 → 查其符合状态条件的报销单
        query = select(Reimbursement).where(
            Reimbursement.applicant_id.in_(resolution.user_ids)
        )
        if status_filter is not None:
            query = query.where(Reimbursement.status == status_filter)
        query = query.order_by(Reimbursement.created_at.desc())

        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            return (None, None)

        if len(reimbs) == 1:
            return (reimbs[0].id, None)

        # 多份报销单 → 消歧
        display = resolution.display_name or person_value
        ids = "、".join(f"#{r.id}" for r in reimbs[:5])
        return (
            None,
            f"找到 {len(reimbs)} 份「{display}」的报销单（编号：{ids}），"
            f"请用具体编号重新操作。",
        )

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _safe_amount(val) -> float:
        """安全转换金额为 float（total_with_tax 可能是 "200元""¥500.00" 等脏数据）"""
        if not val:
            return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            import re
            m = re.search(r"\d+(?:\.\d+)?", str(val))
            return float(m.group()) if m else 0.0

    def _status_text(self, invoice: Invoice) -> str:
        status_map = {
            InvoiceStatus.uploaded: "已上传",
            InvoiceStatus.processing: "处理中",
            InvoiceStatus.reviewing: "待审核",
            InvoiceStatus.confirmed: "已确认",
            InvoiceStatus.reimbursed: "已报销",
            InvoiceStatus.not_reimbursed: "不予报销",
        }
        return status_map.get(invoice.status, str(invoice.status))

    def _status_emoji(self, invoice: Invoice) -> str:
        emoji_map = {
            InvoiceStatus.uploaded: "📥",
            InvoiceStatus.processing: "⏳",
            InvoiceStatus.reviewing: "🔍",
            InvoiceStatus.confirmed: "✅",
            InvoiceStatus.reimbursed: "💰",
            InvoiceStatus.not_reimbursed: "❌",
        }
        return emoji_map.get(invoice.status, "📋")

    def _verify_text(self, invoice: Invoice) -> str:
        if not invoice.verify_status:
            return "未验真"
        return invoice.verify_status.value

    def _verify_emoji(self, invoice: Invoice) -> str:
        from app.models.invoice import VerifyStatus
        emoji_map = {
            VerifyStatus.valid: "✅",
            VerifyStatus.invalid: "❌",
            VerifyStatus.pending: "⏳",
            VerifyStatus.unable: "⚠️",
        }
        if invoice.verify_status:
            return emoji_map.get(invoice.verify_status, "❓")
        return "❓"


# ============================================================
# 全局单例
# ============================================================
_executor: Optional[ActionExecutor] = None


def get_action_executor() -> ActionExecutor:
    """获取 Action Executor 单例"""
    global _executor
    if _executor is None:
        _executor = ActionExecutor()
    return _executor
