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
import logging
import re
from datetime import date
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_sessionmaker
from app.models.invoice import Invoice, InvoiceStatus, ReceiptType
from app.models.reimbursement import Reimbursement, ReimbursementStatus
from app.models.employee import Employee
from app.services.invoice_service import InvoiceService
from app.services.reimbursement_service import (
    create_reimbursement,
    submit_reimbursement,
    get_reimbursement_or_404,
)
from app.services.cycle_engine import cycle_display, current_cycle_key
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
            # 查询类
            "emp_query_invoices": self._handle_query_invoices,
            "emp_query_status": self._handle_query_status,
            "emp_query_my_reimbursement": self._handle_query_my_reimbursement,
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

        # 发票类型：优先用前端弹窗选择的，其次从槽位读取，最后默认
        receipt_type = ctx.slots.get("receipt_type")
        receipt_type_val = receipt_type.value if receipt_type and receipt_type.filled else "增值税普通发票"

        # 费用用途：优先用前端弹窗输入的，否则默认"对话上传"（后续 follow_up 追问）
        user_desc = ctx.user_description or "对话上传"
        has_purpose = bool(ctx.user_description)

        service = InvoiceService(db)
        invoice = await service.process_upload(
            file_data=file_data,
            file_type=file_type,
            receipt_type=receipt_type_val,
            user_id=ctx.user_id,
            user_description=user_desc,
        )

        # 清除临时字段（仅当次请求有效）
        ctx.user_description = None

        # 添加到批量列表
        if invoice.id not in ctx.batch_invoice_ids:
            ctx.batch_invoice_ids.append(invoice.id)

        # 设置待处理发票ID，供后续描述补充使用
        ctx.pending_invoice_id = invoice.id

        # 格式化结果
        seller = invoice.seller_name or "未知"
        amount = invoice.total_with_tax or "未知"
        status_emoji = self._status_emoji(invoice)
        verify_emoji = self._verify_emoji(invoice)

        text = (
            f"✅ 发票已上传并处理\n\n"
            f"📋 发票编号：#{invoice.id}\n"
            f"🏪 销售方：{seller}\n"
            f"💰 金额：¥{amount}\n"
            f"{status_emoji} 状态：{self._status_text(invoice)}\n"
            f"{verify_emoji} 验真：{self._verify_text(invoice)}\n"
        )

        if invoice.fee_subcategory:
            text += f"📊 分类：{invoice.fee_subcategory}\n"
        if invoice.duplicate_status and invoice.duplicate_status.value == "DUPLICATE":
            text += f"⚠️ 提示：此发票可能为重复发票\n"
        if invoice.diff_conflicts:
            text += f"⚠️ 提示：OCR与LLM识别存在差异，请核实\n"

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

        # 无用途 → follow_up 追问
        text += "请简要描述这笔费用的用途（可回复「跳过」跳过）"
        # 追加当前批量发票的 Markdown 汇总表格
        md_table = await self._build_batch_summary_table(ctx, db)
        if md_table:
            text += "\n\n" + md_table
        return {
            "text": text,
            "data": {
                "invoice_id": invoice.id,
                "follow_up": {
                    "state": "waiting_purpose",
                    "intent": "emp_fill_invoice_desc",
                    "prompt": "请简要描述这笔费用的用途，例如：去机场打车",
                    "pending_invoice_id": invoice.id,
                },
            },
        }

    async def _handle_fill_invoice_desc(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """为刚上传的发票补充用途描述/备注"""
        purpose_slot = ctx.slots.get("purpose")
        if not purpose_slot or not purpose_slot.filled:
            return {"text": "请描述这笔费用的用途。", "data": {}}

        invoice_id = ctx.pending_invoice_id
        if not invoice_id:
            return {"text": "没有待描述的发票，请先上传发票图片。", "data": {}}

        result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()
        if not invoice:
            ctx.pending_invoice_id = None
            return {"text": f"未找到发票 #{invoice_id}。", "data": {}}

        invoice.user_description = str(purpose_slot.value)
        await db.commit()

        # 清除待处理标记
        ctx.pending_invoice_id = None

        text = (
            f"已为发票 #{invoice_id} 添加用途描述\n\n"
            f"描述：{purpose_slot.value}\n\n"
            f"已添加到批量提交列表（当前 {len(ctx.batch_invoice_ids)} 张）\n"
        )
        # 追加 Markdown 汇总表格
        md_table = await self._build_batch_summary_table(ctx, db)
        if md_table:
            text += "\n" + md_table + "\n"
        if ctx.role == UserRole.EMPLOYEE:
            text += "继续上传可发送更多发票。报销单将按周期自动生成与归集。"
        else:
            text += "继续上传可发送更多发票，输入「完成」提交报销。"
        return {"text": text, "data": {"invoice_id": invoice_id}}

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
        """修改发票字段"""
        field_name = ctx.slots.get("field_name")
        field_value = ctx.slots.get("field_value")
        if not field_name or not field_name.filled or not field_value or not field_value.filled:
            return {"text": "请告诉我要修改哪个字段以及新值。", "data": {}}

        invoice_id = ctx.pending_invoice_id
        if not invoice_id:
            return {"text": "请先指定要修改的发票编号。", "data": {}}

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
        }
        model_attr = field_map.get(fn.lower() if isinstance(fn, str) else fn, fn)

        if hasattr(invoice, model_attr):
            setattr(invoice, model_attr, fv)
            await db.commit()
            return {"text": f"✅ 已将发票 #{invoice_id} 的{fn}修改为 {fv}。", "data": {"invoice_id": invoice_id}}
        else:
            return {"text": f"不支持修改字段「{fn}」。可修改：金额、日期、销售方、税号、发票号。", "data": {}}

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

        支持的格式:
        - "金额改为100, 日期改为2026-08-01"
        - "金额=100, 日期=2026-08-01"
        - "把销售方改成XX公司, 税号改成123"
        """
        modifications = {}
        # 分割多个修改项
        parts = re.split(r'[,，;；\n]', text)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # 匹配 "字段名 改为/改成/改为/=/→ 值"
            m = re.match(r'(金额|日期|销售方|税号|发票号|amount|date|seller|tax_id|invoice_number)\s*(?:改为|改成|更改为|=|→)\s*(.+)', part, re.IGNORECASE)
            if m:
                modifications[m.group(1)] = m.group(2).strip()
        return modifications

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
            "| # | 编号 | 类型 | 销售方 | 金额 | 用途 |",
            "|---|------|------|--------|------|------|",
        ]
        for idx, inv in enumerate(invoices, 1):
            rt = inv.receipt_type.value if inv.receipt_type else "未知"
            seller = (inv.seller_name or "未知")[:10]
            amount = f"¥{inv.total_with_tax or '—'}"
            desc = (inv.user_description or "待补充")[:12]
            lines.append(f"| {idx} | #{inv.id} | {rt} | {seller} | {amount} | {desc} |")

        # 合计行
        total = 0.0
        for inv in invoices:
            try:
                total += float(inv.total_with_tax or 0)
            except (ValueError, TypeError):
                pass
        lines.append(f"| **合计** | | | | **¥{total:.2f}** | {len(invoices)}张 |")

        return "\n".join(lines)

    # ============================================================
    # 查询类
    # ============================================================

    async def _handle_query_invoices(
        self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
    ) -> dict:
        """查询用户发票列表"""
        result = await db.execute(
            select(Invoice)
            .where(Invoice.user_id == ctx.user_id)
            .order_by(Invoice.created_at.desc())
            .limit(20)
        )
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": "您还没有上传过发票。发送图片即可上传。", "data": {"count": 0}}

        total_amount = 0.0
        for inv in invoices:
            try:
                total_amount += float(inv.total_with_tax or 0)
            except (ValueError, TypeError):
                pass

        lines = [f"📋 您的发票列表（共 {len(invoices)} 张，合计 ¥{total_amount:.2f}）\n"]
        for inv in invoices[:10]:
            seller = inv.seller_name or "未知"
            amount = inv.total_with_tax or "—"
            status = self._status_text(inv)
            lines.append(f"  #{inv.id} | {seller} | ¥{amount} | {status}")

        if len(invoices) > 10:
            lines.append(f"\n（仅显示前10条，共 {len(invoices)} 条）")

        return {"text": "\n".join(lines), "data": {"count": len(invoices), "total": total_amount}}

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
                total += float(inv.total_with_tax or 0)
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
