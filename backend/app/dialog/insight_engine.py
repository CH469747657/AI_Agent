"""Insight Engine — 数据洞察引擎

提供：
- 时间段解析（自然语言 → 日期范围）
- 员工自我洞察（self_insight_*，数据范围限本人）
- 管理员/老板全局洞察（insight_*，全员数据范围）
- 数据叙述（查询结果 → 自然语言回复）

架构特点：
- 直接 SQLAlchemy ORM 查询，不使用 NL2SQL（安全可控）
- Python 端聚合金额字符串（Invoice.total_with_tax 为 String 类型）
- SelfInsightGuard：self_insight_* 自动过滤 applicant_id == user_id
- PeriodResolver：支持"今天/昨天/本周/上周/本月/上月/今年/去年/最近半年/YYYY-MM"等自然语言时间段
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from dataclasses import dataclass, field

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus, ReceiptType, DuplicateStatus, VerifyStatus
from app.models.reimbursement import Reimbursement, ReimbursementStatus, ReimbursementTravelDay
from app.models.employee import Employee
from app.dialog.models import DialogContext, UserRole

logger = logging.getLogger(__name__)

# 中国时区（UTC+8）— 日级/周级时间段按本地日期计算，避免凌晨时段 UTC 偏移导致查询错位
_CN_TZ = timezone(timedelta(hours=8))


# ============================================================
# 人名解析 — 统一「先精确、后模糊、消歧」策略
# ============================================================

@dataclass
class PersonResolution:
    """人名解析结果

    match_type:
        - "exact"       精确命中唯一员工
        - "disambiguate" 多候选，需要上层反问用户消歧
        - "not_found"   无任何匹配
    """
    match_type: str = "not_found"
    user_ids: list[str] = field(default_factory=list)  # 解析出的 user_id 列表
    candidates: list[dict] = field(default_factory=list)  # 多候选时返回 [{name, employee_no, department}, ...]
    display_name: str = ""  # 解析成功时给上层用的展示名


async def resolve_person(
    person: str,
    db: AsyncSession,
    *,
    table_hint: str = "invoice",  # "invoice" 解析 Invoice.user_id; "reimbursement" 解析 Reimbursement.applicant_id
) -> PersonResolution:
    """统一的人名解析函数

    匹配策略（按优先级，命中即停）：
    1. 精确匹配 Employee.name == / employee_no == / wecom_user_id == → 唯一 → exact
    2. 若精确无果，模糊 Employee.name.contains → 唯一 → exact；多个 → disambiguate
    3. 直接 Invoice.user_id / Reimbursement.applicant_id == person → exact（如 admin 等非员工用户）
    4. 上述全部未中 → not_found

    返回的 user_ids 同时包含 wecom_user_id 和 employee_no，兼容两种 applicant_id 格式。
    """
    if not person:
        return PersonResolution()

    # --- 1. 精确匹配 Employee ---
    emp_exact = await db.execute(
        select(Employee).where(
            or_(
                Employee.name == person,
                Employee.employee_no == person,
                Employee.wecom_user_id == person,
            )
        )
    )
    exact_emps = list(emp_exact.scalars().all())

    if len(exact_emps) == 1:
        emp = exact_emps[0]
        ids = set()
        if emp.wecom_user_id:
            ids.add(emp.wecom_user_id)
        if emp.employee_no:
            ids.add(emp.employee_no)
        return PersonResolution(
            match_type="exact",
            user_ids=list(ids),
            display_name=emp.name or person,
        )

    if len(exact_emps) > 1:
        # 工号/ID 唯一但名字重复 → 都视为精确候选（重名员工）
        return PersonResolution(
            match_type="disambiguate",
            candidates=[
                {"name": e.name, "employee_no": e.employee_no, "department": e.department}
                for e in exact_emps
            ],
        )

    # --- 2. 模糊匹配 Employee.name.contains（精度兜底）---
    emp_fuzzy = await db.execute(
        select(Employee).where(Employee.name.contains(person))
    )
    fuzzy_emps = list(emp_fuzzy.scalars().all())

    if len(fuzzy_emps) == 1:
        emp = fuzzy_emps[0]
        ids = set()
        if emp.wecom_user_id:
            ids.add(emp.wecom_user_id)
        if emp.employee_no:
            ids.add(emp.employee_no)
        return PersonResolution(
            match_type="exact",
            user_ids=list(ids),
            display_name=emp.name or person,
        )

    if len(fuzzy_emps) > 1:
        # 模糊匹配多候选 → 让 LLM 消歧（覆盖"小陈"=陈辉、"老王"=王建国 等昵称场景）
        from app.services.llm_service import get_llm_service
        llm_svc = get_llm_service()
        if llm_svc.is_available():
            candidates = [
                {
                    "employee_no": e.employee_no,
                    "name": e.name,
                    "department": e.department,
                    "wecom_user_id": e.wecom_user_id,
                }
                for e in fuzzy_emps
            ]
            matched_no = await llm_svc.resolve_person_llm(person, candidates)
            if matched_no:
                matched_emp = next(
                    (e for e in fuzzy_emps
                     if e.employee_no == matched_no or e.wecom_user_id == matched_no),
                    None,
                )
                if matched_emp:
                    ids = set()
                    if matched_emp.wecom_user_id:
                        ids.add(matched_emp.wecom_user_id)
                    if matched_emp.employee_no:
                        ids.add(matched_emp.employee_no)
                    return PersonResolution(
                        match_type="exact",
                        user_ids=list(ids),
                        display_name=matched_emp.name or person,
                    )
        # LLM 不可用或无法消歧 → 返回候选列表让用户选择
        return PersonResolution(
            match_type="disambiguate",
            candidates=[
                {"name": e.name, "employee_no": e.employee_no, "department": e.department}
                for e in fuzzy_emps
            ],
        )

    # --- 3. 直接 user_id / applicant_id 精确匹配（admin 等非员工用户）---
    if table_hint == "reimbursement":
        check = await db.execute(
            select(Reimbursement.applicant_id)
            .where(Reimbursement.applicant_id == person)
            .limit(1)
        )
    else:
        check = await db.execute(
            select(Invoice.user_id).where(Invoice.user_id == person).limit(1)
        )

    if check.scalar_one_or_none():
        return PersonResolution(
            match_type="exact",
            user_ids=[person],
            display_name=person,
        )

    # --- 4. 未匹配 ---
    # 含义：没有任何 Employee 或 Invoice/Reimbursement 的 user_id/applicant_id 与之命中
    return PersonResolution(match_type="not_found")


def _format_disambiguation_prompt(candidates: list[dict]) -> str:
    """生成消歧反问文案"""
    names = "、".join(
        f"{c['name']}({c.get('department', '')} {c.get('employee_no', '')})"
        for c in candidates[:5]
    )
    return f"找到 {len(candidates)} 位匹配的员工：{names}。请使用完整姓名或工号重新查询。"


class PeriodResolver:
    """将自然语言时间段转化为日期范围

    支持的 period 标识：
        today / yesterday / current_week / last_week
        current_month / last_month / current_year / last_year
        last_6_months / last_12_months / YYYY-MM / YYYY
    """

    @classmethod
    def resolve(
        cls,
        period: str | None,
        text: str = "",
    ) -> tuple[datetime | None, datetime | None, str]:
        """解析时间段

        Args:
            period: 标准化时间段标识（来自 NLU 槽位提取）
            text: 原始用户文本（备用，尝试从中提取时间段）

        Returns:
            (start_date, end_date, description)
            start_date 为 None 表示不限起始时间
            end_date 为 None 表示不限结束时间（即至今）
        """
        # 如果 slot 未填充，尝试从文本提取
        if not period and text:
            period = _extract_period(text)

        if not period:
            return None, None, "全部时间"

        now = datetime.now(timezone.utc)

        if period == "current_month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, now, f"{now.year}年{now.month}月"

        if period == "last_month":
            if now.month == 1:
                start = now.replace(year=now.year - 1, month=12, day=1,
                                    hour=0, minute=0, second=0, microsecond=0)
            else:
                start = now.replace(month=now.month - 1, day=1,
                                    hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, end, f"{start.year}年{start.month}月"

        if period == "current_year":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, now, f"{now.year}年"

        if period == "last_year":
            start = now.replace(year=now.year - 1, month=1, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, end, f"{now.year - 1}年"

        if period == "today":
            now_cn = datetime.now(_CN_TZ)
            start = now_cn.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now_cn, f"{now_cn.month}月{now_cn.day}日"

        if period == "yesterday":
            now_cn = datetime.now(_CN_TZ)
            start = (now_cn - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now_cn.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, end, f"{start.month}月{start.day}日"

        if period == "current_week":
            now_cn = datetime.now(_CN_TZ)
            monday = now_cn - timedelta(days=now_cn.weekday())
            start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now_cn, "本周"

        if period == "last_week":
            now_cn = datetime.now(_CN_TZ)
            this_monday = (now_cn - timedelta(days=now_cn.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            last_monday = this_monday - timedelta(days=7)
            return last_monday, this_monday, "上周"

        if period == "last_6_months":
            start = (now - timedelta(days=182)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, now, "最近6个月"

        if period == "last_12_months":
            start = (now - timedelta(days=365)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, now, "最近12个月"

        # YYYY-MM 格式
        m = re.match(r"^(\d{4})-(\d{2})$", period)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
            return start, end, f"{year}年{month}月"

        # YYYY 格式
        m = re.match(r"^(\d{4})$", period)
        if m:
            year = int(m.group(1))
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            return start, end, f"{year}年"

        return None, None, "全部时间"


# ============================================================
# InsightEngine — 数据洞察引擎
# ============================================================

# 费用分类别名映射 — 仅作为 LLM 不可用时的兜底（弱匹配）
# 主路径已改为 LLM 语义筛选：handler 取候选发票后让 LLM 判断哪些属于用户问的分类
_CATEGORY_ALIASES: dict[str, list[str]] = {
    "差旅": ["差旅", "住宿", "交通", "出差", "机票", "火车"],
    "交通": ["交通", "车费", "打车", "出行", "机票", "火车"],
    "住宿": ["住宿", "酒店", "宾馆", "房费"],
    "餐饮": ["餐饮", "餐费", "伙食", "吃饭", "用餐"],
    "培训": ["培训", "课程", "学习", "讲座"],
    "快递": ["快递", "物流", "邮寄"],
    "办公": ["办公", "文具", "耗材"],
    "投标": ["投标", "招标"],
    "运营": ["运营"],
}


def _derive_aliases(keyword: str | None) -> list[str] | None:
    """从分类关键词推导别名列表

    当 NLU 未提供 fee_category_aliases 槽位时，
    根据 keyword 在 _CATEGORY_ALIASES 中查找对应别名。
    如果找不到精确匹配，使用 keyword 本身作为唯一别名。

    对于复合子类（如"差旅-交通"含"-"），不做别名扩散，
    只返回 [keyword] 以避免误匹配其他子类（如"差旅-餐饮"）。
    """
    if not keyword:
        return None
    # 复合子类（"差旅-交通""差旅-餐饮"等）：精确匹配，不扩散
    if "-" in keyword:
        return [keyword]
    # 精确匹配
    if keyword in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[keyword]
    # 模糊匹配：keyword 包含某个 key，或某个 key 包含 keyword
    for key, aliases in _CATEGORY_ALIASES.items():
        if key in keyword or keyword in key:
            return aliases
    # 回退：使用 keyword 本身
    return [keyword]


class InsightEngine:
    """数据洞察引擎 — 14 个洞察意图的数据查询与叙述"""

    def __init__(self):
        pass

    async def execute(
        self,
        intent_name: str,
        context: DialogContext,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """执行洞察意图

        Args:
            intent_name: 意图名称
            context: 对话上下文（含已填充槽位、user_id、role）
            db: 数据库会话

        Returns:
            {"text": "用户可见回复", "data": {...}}
        """
        handler = self._get_handler(intent_name)
        if not handler:
            return {
                "text": f"洞察功能「{intent_name}」正在开发中。",
                "data": {"not_implemented": True},
            }

        try:
            return await handler(context, db)
        except Exception as e:
            logger.exception("Insight execution failed: intent=%s error=%s", intent_name, e)
            return {
                "text": f"数据查询失败：{e}",
                "data": {"error": str(e)},
            }

    def _get_handler(self, intent_name: str):
        """获取意图对应的处理函数"""
        handlers = {
            # 员工自我洞察
            "self_insight_total": self._self_total,
            "self_insight_category": self._self_category,
            "self_insight_category_amount": self._self_category_amount,
            "self_insight_trend": self._self_trend,
            "self_insight_compare": self._self_compare,
            "self_insight_pending": self._self_pending,
            "self_insight_invoice_total": self._self_invoice_total,
            "self_insight_invoice_filter": self._self_invoice_filter,
            # 管理员/老板全局洞察
            "insight_total": self._insight_total,
            "insight_by_category": self._insight_by_category,
            "insight_category_amount": self._insight_category_amount,
            "insight_trend": self._insight_trend,
            "insight_anomaly": self._insight_anomaly,
            "insight_top": self._insight_top,
            "insight_project": self._insight_project,
            "insight_by_dept": self._insight_by_dept,
            "insight_person": self._insight_person,
            "insight_compare": self._insight_compare,
            "insight_invoice_total": self._insight_invoice_total,
            "insight_invoice_filter": self._insight_invoice_filter,
        }
        return handlers.get(intent_name)

    # ============================================================
    # 员工自我洞察 — 数据范围限本人
    # ============================================================

    async def _self_total(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_total — 本人报销总额"""
        start, end, desc = self._get_period(ctx)
        query = select(Reimbursement).where(
            Reimbursement.applicant_id == ctx.user_id
        )
        if start:
            query = query.where(Reimbursement.created_at >= start)
        if end:
            query = query.where(Reimbursement.created_at < end)

        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            return {"text": f"📊 您在（{desc}）暂无报销记录。", "data": {"count": 0}}

        total = sum(r.total_amount or 0 for r in reimbs)
        by_status = defaultdict(float)
        for r in reimbs:
            by_status[r.status] += r.total_amount or 0

        status_names = {
            ReimbursementStatus.draft: "草稿",
            ReimbursementStatus.submitted: "待审批",
            ReimbursementStatus.reviewed: "已审核",
            ReimbursementStatus.reviewed: "已报销",
        }

        lines = [f"📊 您的报销总额（{desc}）\n"]
        lines.append(f"💰 报销总额：{self._fmt_money(total)}")
        lines.append(f"📋 报销单数：{len(reimbs)} 笔")
        lines.append("")
        for status, name in status_names.items():
            if status in by_status and by_status[status] > 0:
                lines.append(f"  {name}：{self._fmt_money(by_status[status])}")

        return {"text": "\n".join(lines), "data": {
            "total": total, "count": len(reimbs), "period": desc
        }}

    async def _self_category(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_category — 本人费用分类占比"""
        start, end, desc = self._get_period(ctx)
        query = select(Invoice).where(Invoice.user_id == ctx.user_id, Invoice.status != InvoiceStatus.processing)
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": f"📊 您在（{desc}）暂无发票记录。", "data": {"count": 0}}

        # 按费用子分类聚合（Python 端，因 total_with_tax 是 String）
        cat_totals: dict[str, float] = defaultdict(float)
        for inv in invoices:
            cat = inv.fee_subcategory or "未分类"
            cat_totals[cat] += self._safe_float(inv.total_with_tax)

        total = sum(cat_totals.values())
        # 按金额降序排列
        sorted_cats = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)

        lines = [f"📊 您的费用分类占比（{desc}）\n"]
        for cat, amount in sorted_cats:
            pct = self._fmt_pct(amount, total)
            lines.append(f"  {cat}：{self._fmt_money(amount)}（{pct}）")
        lines.append(f"\n合计：{self._fmt_money(total)}（{len(invoices)} 张发票）")

        return {"text": "\n".join(lines), "data": {
            "categories": dict(sorted_cats), "total": total, "period": desc
        }}

    async def _self_category_amount(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_category_amount — 本人某分类费用金额

        用户说"快递费花了多少"、"差旅费报了多少"等，指定分类名查询金额。
        同时查 invoices 表（含未关联报销单的发票）和 reimbursements 表，
        确保不遗漏任何数据。
        """
        start, end, desc = self._get_period(ctx)
        keyword_slot = ctx.slots.get("fee_category_keyword")
        keyword = keyword_slot.value if keyword_slot and keyword_slot.filled else None
        aliases_slot = ctx.slots.get("fee_category_aliases")
        aliases = aliases_slot.value if aliases_slot and aliases_slot.filled else None

        # 查询本人所有发票（不要求 reimbursement_id，覆盖未关联报销单的发票）
        query = select(Invoice).where(Invoice.user_id == ctx.user_id, Invoice.status != InvoiceStatus.processing)
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": f"📊 您在（{desc}）暂无发票记录。", "data": {"count": 0}}

        # 按分类名过滤 — 员工端
        # 主路径：LLM 语义筛选。理解"打车费"="差旅-交通子类下用途为打车费的发票"等语义等价
        # 回退：硬编码 _CATEGORY_ALIASES 字典 + 子串包含（LLM 不可用时兜底）
        matched_invoices = []
        if keyword:
            from app.services.llm_service import get_llm_service
            llm_svc = get_llm_service()
            if llm_svc.is_available():
                candidates_payload = [
                    {
                        "id": inv.id,
                        "fee_subcategory": inv.fee_subcategory,
                        "fee_category": inv.fee_category,
                        "item_name": inv.item_name,
                        "user_description": inv.user_description,
                    }
                    for inv in invoices
                ]
                matched_ids = await llm_svc.classify_invoices_by_category(
                    keyword, candidates_payload
                )
                matched_id_set = set(matched_ids)
                matched_invoices = [inv for inv in invoices if inv.id in matched_id_set]
                logger.info(
                    "LLM category filter: user=%s keyword=%s matched %d/%d invoices",
                    ctx.user_id, keyword, len(matched_invoices), len(invoices),
                )

            # LLM 不可用或返回空 → 回退到硬编码字典
            if not matched_invoices:
                aliases = _derive_aliases(keyword)
                keyword_is_compound = "-" in (keyword or "")
                for inv in invoices:
                    subcat = inv.fee_subcategory or ""
                    cat = inv.fee_category or ""
                    item = inv.item_name or ""
                    desc_field = inv.user_description or ""
                    if keyword_is_compound:
                        if subcat == keyword or cat == keyword:
                            matched_invoices.append(inv)
                    else:
                        for alias in aliases:
                            if alias in subcat or alias in cat or alias in item or alias in desc_field:
                                matched_invoices.append(inv)
                                break
        else:
            # 无关键词时返回全部分类汇总
            matched_invoices = invoices

        if not matched_invoices:
            available = sorted(set(
                inv.fee_subcategory or "未分类" for inv in invoices
            ))
            avail_str = "、".join(available)
            display_keyword = keyword or "该分类"
            return {
                "text": f"📊 您在（{desc}）没有「{display_keyword}」相关的发票记录。\n现有分类：{avail_str}",
                "data": {"count": 0, "available_categories": available},
            }

        # 聚合金额
        total = sum(self._safe_float(inv.total_with_tax) for inv in matched_invoices)
        display_keyword = keyword or "指定分类"

        lines = [f"📊 您的「{display_keyword}」费用（{desc}）\n"]
        lines.append(f"💰 金额合计：{self._fmt_money(total)}")
        lines.append(f"📋 发票张数：{len(matched_invoices)} 张")
        lines.append("")
        # 旧版仅输出子分类汇总行，但用户问"我有哪些快递费的发票"期望看到明细列表
        # 现在追加 markdown 表格列出每张发票明细，与 _build_user_invoices_table 列结构一致
        lines.append("| 序号 | 类型 | 销售方 | 金额 | 用途 | 出差日期 | 状态 | 上传时间 |")
        lines.append("|------|------|--------|------|------|----------|------|----------|")
        for idx, inv in enumerate(sorted(matched_invoices, key=lambda x: x.created_at, reverse=True), 1):
            rt = inv.receipt_type.value if inv.receipt_type else "未知"
            seller = (inv.seller_name or "无票报销")[:10]
            amt = inv.total_with_tax or "—"
            desc_short = (inv.user_description or "待补充")[:12]
            expense_date = str(inv.expense_date) if inv.expense_date else "—"
            st = self._inv_status_text(inv)
            created = inv.created_at.strftime("%Y-%m-%d %H:%M") if inv.created_at else "—"
            lines.append(f"| {idx} | {rt} | {seller} | ¥{amt} | {desc_short} | {expense_date} | {st} | {created} |")

        return {"text": "\n".join(lines), "data": {
            "category": display_keyword, "total": total,
            "count": len(matched_invoices), "period": desc,
        }}

    async def _self_trend(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_trend — 本人费用趋势"""
        # 趋势查询默认最近6个月
        period_slot = ctx.slots.get("period")
        period_val = period_slot.value if period_slot and period_slot.filled else "last_6_months"
        start, end, desc = PeriodResolver.resolve(period_val, ctx.current_text)

        query = select(Reimbursement).where(
            Reimbursement.applicant_id == ctx.user_id
        )
        if start:
            query = query.where(Reimbursement.created_at >= start)
        if end:
            query = query.where(Reimbursement.created_at < end)

        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            return {"text": f"📊 您在（{desc}）暂无报销记录。", "data": {"count": 0}}

        # 按月分组
        monthly: dict[str, float] = defaultdict(float)
        for r in reimbs:
            dt = r.created_at
            if dt:
                key = f"{dt.year}-{dt.month:02d}"
                monthly[key] += r.total_amount or 0

        sorted_months = sorted(monthly.items())
        if len(sorted_months) < 2:
            return {
                "text": f"📊 您的费用趋势（{desc}）\n\n"
                        f"  {sorted_months[0][0]}：{self._fmt_money(sorted_months[0][1])}\n\n"
                        f"数据不足，无法计算趋势。",
                "data": {"monthly": dict(sorted_months), "period": desc},
            }

        # 计算趋势方向
        last_val = sorted_months[-1][1]
        prev_val = sorted_months[-2][1]
        trend = self._trend_arrow(last_val, prev_val)

        lines = [f"📊 您的费用趋势（{desc}）\n"]
        for month, amount in sorted_months:
            lines.append(f"  {month}：{self._fmt_money(amount)}")
        lines.append(f"\n📈 环比：{trend}")

        return {"text": "\n".join(lines), "data": {
            "monthly": dict(sorted_months), "trend": trend, "period": desc
        }}

    async def _self_compare(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_compare — 本人本月 vs 上月对比"""
        now = datetime.now(timezone.utc)
        this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 1:
            last_start = now.replace(year=now.year - 1, month=12, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)
        else:
            last_start = now.replace(month=now.month - 1, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)

        # 本月
        r1 = await db.execute(
            select(Reimbursement).where(
                Reimbursement.applicant_id == ctx.user_id,
                Reimbursement.created_at >= this_start,
            )
        )
        this_reimbs = list(r1.scalars().all())
        this_total = sum(r.total_amount or 0 for r in this_reimbs)

        # 上月
        r2 = await db.execute(
            select(Reimbursement).where(
                Reimbursement.applicant_id == ctx.user_id,
                Reimbursement.created_at >= last_start,
                Reimbursement.created_at < this_start,
            )
        )
        last_reimbs = list(r2.scalars().all())
        last_total = sum(r.total_amount or 0 for r in last_reimbs)

        trend = self._trend_arrow(this_total, last_total)

        lines = [
            f"📊 您的费用对比（本月 vs 上月）\n",
            f"  本月（{now.year}年{now.month}月）：{self._fmt_money(this_total)}（{len(this_reimbs)} 笔）",
            f"  上月（{last_start.year}年{last_start.month}月）：{self._fmt_money(last_total)}（{len(last_reimbs)} 笔）",
            f"\n📈 环比：{trend}",
        ]

        return {"text": "\n".join(lines), "data": {
            "this_month": this_total, "last_month": last_total, "trend": trend
        }}

    async def _self_pending(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_pending — 本人未提交票据"""
        result = await db.execute(
            select(Invoice).where(
                Invoice.user_id == ctx.user_id,
                Invoice.reimbursement_id.is_(None),
                Invoice.status.in_([
                    InvoiceStatus.reviewed,
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
            total += self._safe_float(inv.total_with_tax)

        lines = [f"📋 未提交票据（{len(invoices)} 张，合计 {self._fmt_money(total)}）\n"]
        for inv in invoices[:10]:
            seller = inv.seller_name or "无票报销"
            amount = inv.total_with_tax or "—"
            lines.append(f"  #{inv.id} | {seller} | ¥{amount} | {self._inv_status_text(inv)}")

        if ctx.role == UserRole.EMPLOYEE:
            lines.append("\n报销单将按周期自动生成与归集。")
        else:
            lines.append("\n输入「完成」可提交报销。")
        return {"text": "\n".join(lines), "data": {"count": len(invoices), "total": total}}

    # ============================================================
    # 管理员/老板全局洞察 — 全员数据范围
    # ============================================================

    async def _insight_total(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_total — 公司报销总额"""
        start, end, desc = self._get_period(ctx)
        query = select(Reimbursement)
        if start:
            query = query.where(Reimbursement.created_at >= start)
        if end:
            query = query.where(Reimbursement.created_at < end)

        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            return {"text": f"📊 公司在（{desc}）暂无报销记录。", "data": {"count": 0}}

        total = sum(r.total_amount or 0 for r in reimbs)
        persons = set(r.applicant_id for r in reimbs)
        by_status = defaultdict(lambda: [0, 0.0])  # [count, amount]
        for r in reimbs:
            by_status[r.status][0] += 1
            by_status[r.status][1] += r.total_amount or 0

        status_names = {
            ReimbursementStatus.draft: "草稿",
            ReimbursementStatus.submitted: "待审批",
            ReimbursementStatus.reviewed: "已审核",
            ReimbursementStatus.reviewed: "已报销",
        }

        lines = [f"📊 公司报销总额（{desc}）\n"]
        lines.append(f"💰 报销总额：{self._fmt_money(total)}")
        lines.append(f"📋 报销单数：{len(reimbs)} 笔")
        lines.append(f"👥 报销人数：{len(persons)} 人")
        lines.append("")
        for status, name in status_names.items():
            if status in by_status:
                cnt, amt = by_status[status]
                lines.append(f"  {name}：{self._fmt_money(amt)}（{cnt} 笔）")

        # 按状态汇总表格预览
        lines.append("\n| 状态 | 报销单数 | 金额 |")
        lines.append("|------|----------|------|")
        for status, name in status_names.items():
            if status in by_status:
                cnt, amt = by_status[status]
                lines.append(f"| {name} | {cnt} 笔 | {self._fmt_money(amt)} |")
        lines.append(f"| **合计** | **{len(reimbs)} 笔** | **{self._fmt_money(total)}** |")

        return {"text": "\n".join(lines), "data": {
            "total": total, "count": len(reimbs),
            "persons": len(persons), "period": desc
        }}

    async def _insight_by_category(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_by_category — 费用类别分布"""
        start, end, desc = self._get_period(ctx)

        # 查询所有发票（含未关联报销单的，确保数据完整）
        query = select(Invoice).where(Invoice.status != InvoiceStatus.processing)
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": f"📊 （{desc}）暂无发票数据。", "data": {"count": 0}}

        # 按费用子分类聚合
        cat_totals: dict[str, float] = defaultdict(float)
        cat_counts: dict[str, int] = defaultdict(int)
        for inv in invoices:
            cat = inv.fee_subcategory or "未分类"
            cat_totals[cat] += self._safe_float(inv.total_with_tax)
            cat_counts[cat] += 1

        total = sum(cat_totals.values())
        sorted_cats = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)

        lines = [f"📊 费用类别分布（{desc}）\n"]
        for cat, amount in sorted_cats:
            pct = self._fmt_pct(amount, total)
            lines.append(f"  {cat}：{self._fmt_money(amount)}（{pct}，{cat_counts[cat]} 张）")
        lines.append(f"\n合计：{self._fmt_money(total)}（{len(invoices)} 张发票）")

        return {"text": "\n".join(lines), "data": {
            "categories": dict(sorted_cats), "total": total, "period": desc
        }}

    async def _insight_category_amount(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_category_amount — 全公司某分类费用金额

        管理员/老板说"快递费花了多少"、"差旅费报了多少"等，
        指定分类名查询全公司金额。同时查 invoices 表（含未关联报销单的发票）。
        """
        start, end, desc = self._get_period(ctx)
        keyword_slot = ctx.slots.get("fee_category_keyword")
        keyword = keyword_slot.value if keyword_slot and keyword_slot.filled else None
        aliases_slot = ctx.slots.get("fee_category_aliases")
        aliases = aliases_slot.value if aliases_slot and aliases_slot.filled else None

        # 查询全公司所有发票（不要求 reimbursement_id，覆盖未关联报销单的发票）
        query = select(Invoice).where(Invoice.status != InvoiceStatus.processing)
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": f"📊 （{desc}）暂无发票数据。", "data": {"count": 0}}

        # 按分类名过滤 — 管理端
        # 主路径：LLM 语义筛选；回退：硬编码字典
        matched_invoices = []
        if keyword:
            from app.services.llm_service import get_llm_service
            llm_svc = get_llm_service()
            if llm_svc.is_available():
                candidates_payload = [
                    {
                        "id": inv.id,
                        "fee_subcategory": inv.fee_subcategory,
                        "fee_category": inv.fee_category,
                        "item_name": inv.item_name,
                        "user_description": inv.user_description,
                    }
                    for inv in invoices
                ]
                matched_ids = await llm_svc.classify_invoices_by_category(
                    keyword, candidates_payload
                )
                matched_id_set = set(matched_ids)
                matched_invoices = [inv for inv in invoices if inv.id in matched_id_set]
                logger.info(
                    "LLM category filter (admin): keyword=%s matched %d/%d invoices",
                    keyword, len(matched_invoices), len(invoices),
                )

            if not matched_invoices:
                aliases = _derive_aliases(keyword)
                keyword_is_compound = "-" in (keyword or "")
                for inv in invoices:
                    subcat = inv.fee_subcategory or ""
                    cat = inv.fee_category or ""
                    item = inv.item_name or ""
                    desc_field = inv.user_description or ""
                    if keyword_is_compound:
                        if subcat == keyword or cat == keyword:
                            matched_invoices.append(inv)
                    else:
                        for alias in aliases:
                            if alias in subcat or alias in cat or alias in item or alias in desc_field:
                                matched_invoices.append(inv)
                                break
        else:
            matched_invoices = invoices

        if not matched_invoices:
            available = sorted(set(
                inv.fee_subcategory or "未分类" for inv in invoices
            ))
            avail_str = "、".join(available)
            display_keyword = keyword or "该分类"
            return {
                "text": f"📊 （{desc}）没有「{display_keyword}」相关的发票记录。\n现有分类：{avail_str}",
                "data": {"count": 0, "available_categories": available},
            }

        # 聚合金额
        total = sum(self._safe_float(inv.total_with_tax) for inv in matched_invoices)
        display_keyword = keyword or "指定分类"

        lines = [f"📊 「{display_keyword}」费用（{desc}，全公司）\n"]
        lines.append(f"💰 金额合计：{self._fmt_money(total)}")
        lines.append(f"📋 发票张数：{len(matched_invoices)} 张")
        lines.append("")
        # 旧版仅输出子分类+上传者汇总行，用户问"哪些是快递费"期望看到明细列表
        # 现在追加 markdown 表格，列含上传者和出差日期（管理端特有）
        lines.append("| 序号 | 类型 | 销售方 | 金额 | 用途 | 出差日期 | 上传者 | 状态 | 上传时间 |")
        lines.append("|------|------|--------|------|------|----------|--------|------|----------|")
        uploader_ids = list(set(inv.user_id for inv in matched_invoices if inv.user_id))
        uploader_names = await self._resolve_user_names(uploader_ids, db)
        for idx, inv in enumerate(sorted(matched_invoices, key=lambda x: x.created_at, reverse=True), 1):
            rt = inv.receipt_type.value if inv.receipt_type else "未知"
            seller = (inv.seller_name or "无票报销")[:10]
            amt = inv.total_with_tax or "—"
            desc_short = (inv.user_description or "待补充")[:12]
            expense_date = str(inv.expense_date) if inv.expense_date else "—"
            uploader = uploader_names.get(inv.user_id, inv.user_id or "未知")
            st = self._inv_status_text(inv)
            created = inv.created_at.strftime("%Y-%m-%d %H:%M") if inv.created_at else "—"
            lines.append(f"| {idx} | {rt} | {seller} | ¥{amt} | {desc_short} | {expense_date} | {uploader} | {st} | {created} |")

        return {"text": "\n".join(lines), "data": {
            "category": display_keyword, "total": total,
            "count": len(matched_invoices), "period": desc,
        }}

    async def _insight_trend(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_trend — 费用趋势（全公司）"""
        period_slot = ctx.slots.get("period")
        period_val = period_slot.value if period_slot and period_slot.filled else "last_6_months"
        start, end, desc = PeriodResolver.resolve(period_val, ctx.current_text)

        query = select(Reimbursement)
        if start:
            query = query.where(Reimbursement.created_at >= start)
        if end:
            query = query.where(Reimbursement.created_at < end)

        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            return {"text": f"📊 公司在（{desc}）暂无报销记录。", "data": {"count": 0}}

        # 按月分组
        monthly: dict[str, float] = defaultdict(float)
        monthly_count: dict[str, int] = defaultdict(int)
        for r in reimbs:
            dt = r.created_at
            if dt:
                key = f"{dt.year}-{dt.month:02d}"
                monthly[key] += r.total_amount or 0
                monthly_count[key] += 1

        sorted_months = sorted(monthly.items())
        if len(sorted_months) < 2:
            lines = [f"📊 公司费用趋势（{desc}）\n"]
            for month, amount in sorted_months:
                lines.append(f"  {month}：{self._fmt_money(amount)}")
            lines.append("\n数据不足，无法计算趋势。")
            # 单月也输出表格预览
            if sorted_months:
                lines.append("\n| 月份 | 报销金额 | 报销单数 |")
                lines.append("|------|----------|----------|")
                for month, amount in sorted_months:
                    lines.append(f"| {month} | {self._fmt_money(amount)} | {monthly_count[month]} 笔 |")
            return {"text": "\n".join(lines), "data": {"monthly": dict(sorted_months)}}

        last_val = sorted_months[-1][1]
        prev_val = sorted_months[-2][1]
        trend = self._trend_arrow(last_val, prev_val)

        lines = [f"📊 公司费用趋势（{desc}）\n"]
        for month, amount in sorted_months:
            lines.append(f"  {month}：{self._fmt_money(amount)}（{monthly_count[month]} 笔）")
        lines.append(f"\n📈 环比：{trend}")

        # 月度趋势表格预览
        lines.append("\n| 月份 | 报销金额 | 报销单数 |")
        lines.append("|------|----------|----------|")
        for month, amount in sorted_months:
            lines.append(f"| {month} | {self._fmt_money(amount)} | {monthly_count[month]} 笔 |")

        return {"text": "\n".join(lines), "data": {
            "monthly": dict(sorted_months), "trend": trend, "period": desc
        }}

    async def _insight_anomaly(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_anomaly — 异常/超标/重复报销检测（支持 anomaly_type 过滤）"""
        start, end, desc = self._get_period(ctx)

        # anomaly_type 槽位：指定只检测某一类异常
        anomaly_type_slot = ctx.slots.get("anomaly_type")
        anomaly_type = anomaly_type_slot.value if anomaly_type_slot and anomaly_type_slot.filled else None

        anomalies: list[str] = []

        # 1. 重复发票
        dups = []
        if anomaly_type is None or anomaly_type == "duplicate":
            dup_query = select(Invoice).where(
            Invoice.duplicate_status == DuplicateStatus.duplicate
        )
        if start:
            dup_query = dup_query.where(Invoice.created_at >= start)
        if end:
            dup_query = dup_query.where(Invoice.created_at < end)
        dup_result = await db.execute(dup_query)
        dups = list(dup_result.scalars().all())

        # 2. 验真失败
        invalids = []
        if anomaly_type is None or anomaly_type == "invalid":
            invalid_query = select(Invoice).where(
                Invoice.verify_status == VerifyStatus.invalid
            )
            if start:
                invalid_query = invalid_query.where(Invoice.created_at >= start)
            if end:
                invalid_query = invalid_query.where(Invoice.created_at < end)
            invalid_result = await db.execute(invalid_query)
            invalids = list(invalid_result.scalars().all())

        # 3. 高风险非标准票据
        risks = []
        if anomaly_type is None or anomaly_type == "high_risk":
            risk_query = select(Invoice).where(
            Invoice.is_nonstandard == True,
            Invoice.risk_level == "high"
        )
        if start:
            risk_query = risk_query.where(Invoice.created_at >= start)
        if end:
            risk_query = risk_query.where(Invoice.created_at < end)
        risk_result = await db.execute(risk_query)
        risks = list(risk_result.scalars().all())

        # 4. 超标报销（金额超出平均值2倍）
        over_budget = []
        if anomaly_type is None or anomaly_type == "over_budget":
            reimb_query = select(Reimbursement).where(
                Reimbursement.total_amount.is_not(None)
            )
            if start:
                reimb_query = reimb_query.where(Reimbursement.created_at >= start)
            if end:
                reimb_query = reimb_query.where(Reimbursement.created_at < end)
            reimb_result = await db.execute(reimb_query)
            reimbs = list(reimb_result.scalars().all())

            avg = sum(r.total_amount or 0 for r in reimbs) / len(reimbs) if reimbs else 0
            over_budget = [r for r in reimbs if (r.total_amount or 0) > avg * 2]

        # 汇总
        total_anomalies = len(dups) + len(invalids) + len(risks) + len(over_budget)

        if total_anomalies == 0:
            return {
                "text": f"✅ 异常检测报告（{desc}）\n\n本期未发现异常报销记录。",
                "data": {"total": 0, "period": desc},
            }

        lines = [f"⚠️ 异常检测报告（{desc}）\n"]

        # 异常汇总表格预览
        lines.append("| 异常类型 | 数量 |")
        lines.append("|----------|------|")
        if dups:
            lines.append(f"| 重复发票 | {len(dups)} 张 |")
        if invalids:
            lines.append(f"| 验真失败 | {len(invalids)} 张 |")
        if risks:
            lines.append(f"| 高风险票据 | {len(risks)} 张 |")
        if over_budget:
            lines.append(f"| 超标报销 | {len(over_budget)} 笔 |")
        lines.append(f"| **合计** | **{total_anomalies}** |")
        lines.append("")

        if dups:
            lines.append(f"🔍 重复发票：{len(dups)} 张")
            lines.append("| 发票编号 | 销售方 | 金额 |")
            lines.append("|----------|--------|------|")
            for inv in dups[:5]:
                seller = inv.seller_name or "未知"
                amount = inv.total_with_tax or "—"
                lines.append(f"| #{inv.id} | {seller} | ¥{amount} |")
            if len(dups) > 5:
                lines.append(f"| ... | 共 {len(dups)} 张 | ... |")
            lines.append("")

        if invalids:
            lines.append(f"❌ 验真失败：{len(invalids)} 张")
            lines.append("| 发票编号 | 销售方 | 失败原因 |")
            lines.append("|----------|--------|----------|")
            for inv in invalids[:5]:
                seller = inv.seller_name or "未知"
                msg = inv.verify_message or "无"
                lines.append(f"| #{inv.id} | {seller} | {msg} |")
            if len(invalids) > 5:
                lines.append(f"| ... | 共 {len(invalids)} 张 | ... |")
            lines.append("")

        if risks:
            lines.append(f"🚨 高风险票据：{len(risks)} 张")
            lines.append("| 发票编号 | 销售方 |")
            lines.append("|----------|--------|")
            for inv in risks[:5]:
                seller = inv.seller_name or "非标准票据"
                lines.append(f"| #{inv.id} | {seller} |")
            if len(risks) > 5:
                lines.append(f"| ... | 共 {len(risks)} 张 | ... |")
            lines.append("")

        if over_budget:
            lines.append(f"📈 超标报销：{len(over_budget)} 笔（超出均值2倍）")
            lines.append("| 报销单编号 | 申请人 | 金额 |")
            lines.append("|------------|--------|------|")
            for r in over_budget[:5]:
                name = r.applicant_name or r.applicant_id
                lines.append(f"| #{r.id} | {name} | {self._fmt_money(r.total_amount or 0)} |")

        return {"text": "\n".join(lines), "data": {
            "total": total_anomalies,
            "duplicates": len(dups),
            "invalid": len(invalids),
            "high_risk": len(risks),
            "over_budget": len(over_budget),
            "period": desc,
        }}

    async def _insight_top(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_top — 费用排名 TOP N（支持最多/最少 + 发票级/报销单级）"""
        start, end, desc = self._get_period(ctx)
        limit_slot = ctx.slots.get("limit")
        limit = 10
        if limit_slot and limit_slot.filled:
            try:
                limit = min(int(limit_slot.value), 50)
            except (ValueError, TypeError):
                pass

        # 排序方向：desc=从多到少（最多），asc=从少到多（最少）
        order_slot = ctx.slots.get("order")
        order_desc = True  # 默认降序（最多）
        if order_slot and order_slot.filled and order_slot.value == "asc":
            order_desc = False

        # 数据范围：invoice=按单张发票排名，reimbursement=按人汇总排名（默认）
        data_scope_slot = ctx.slots.get("data_scope")
        data_scope = "reimbursement"
        if data_scope_slot and data_scope_slot.filled:
            data_scope = data_scope_slot.value

        if data_scope == "invoice":
            return await self._insight_top_by_invoice(ctx, db, start, end, desc, limit, order_desc)
        else:
            return await self._insight_top_by_reimbursement(ctx, db, start, end, desc, limit, order_desc)

    async def _insight_top_by_invoice(
        self, ctx: DialogContext, db: AsyncSession,
        start, end, desc: str, limit: int, order_desc: bool,
    ) -> dict[str, Any]:
        """insight_top 发票级排名 — 按单张发票金额排序"""
        query = select(Invoice).where(
            Invoice.total_with_tax.is_not(None),
            Invoice.status != InvoiceStatus.reviewed,  # 排除已替代的
        )
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        # SelfInsightGuard: 员工只看自己的发票
        if ctx.role == UserRole.EMPLOYEE:
            query = query.where(
                or_(Invoice.user_id == ctx.user_id, Invoice.user_id == ctx.user_id)
            )

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": f"📊 发票排名（{desc}）暂无发票数据。", "data": {"count": 0}}

        # 解析金额并构建排名数据
        invoice_data: list[tuple[int, str, float, str, str]] = []  # (id, seller, amount, category, date)
        for inv in invoices:
            try:
                amount = float(inv.total_with_tax) if inv.total_with_tax else 0
            except (ValueError, TypeError):
                amount = 0
            if amount <= 0:
                continue
            seller = inv.seller_name or "未知"
            category = inv.fee_subcategory or (inv.fee_category.value if inv.fee_category else None) or "未分类"
            date = inv.issue_date or ""
            invoice_data.append((inv.id, seller, amount, category, date))

        if not invoice_data:
            return {"text": f"📊 发票排名（{desc}）暂无有效金额数据。", "data": {"count": 0}}

        # 排序
        invoice_data.sort(key=lambda x: x[2], reverse=order_desc)
        top_n = invoice_data[:limit]

        order_label = "最少" if not order_desc else "最多"
        lines = [f"📊 发票金额排名 TOP {len(top_n)}（{desc}，{order_label}）\n"]
        for i, (inv_id, seller, amount, category, date) in enumerate(top_n, 1):
            line = f"  {i}. {seller}  {self._fmt_money(amount)}"
            if category and category != "未分类":
                line += f"（{category}）"
            if date:
                line += f"  {date}"
            lines.append(line)

        # 发票排名表格预览
        lines.append("\n| 排名 | 销售方 | 金额 | 分类 | 开票日期 |")
        lines.append("|------|--------|------|------|----------|")
        for i, (inv_id, seller, amount, category, date) in enumerate(top_n, 1):
            lines.append(f"| {i} | {seller} | {self._fmt_money(amount)} | {category if category and category != '未分类' else '—'} | {date or '—'} |")

        return {"text": "\n".join(lines), "data": {
            "top": [(seller, amt) for _, seller, amt, _, _ in top_n],
            "period": desc,
            "data_scope": "invoice",
        }}

    async def _insight_top_by_reimbursement(
        self, ctx: DialogContext, db: AsyncSession,
        start, end, desc: str, limit: int, order_desc: bool,
    ) -> dict[str, Any]:
        """insight_top 报销单级排名 — 按人汇总金额排序"""
        query = select(Reimbursement).where(
            Reimbursement.total_amount.is_not(None)
        )
        if start:
            query = query.where(Reimbursement.created_at >= start)
        if end:
            query = query.where(Reimbursement.created_at < end)

        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            return {"text": f"📊 （{desc}）暂无报销数据。", "data": {"count": 0}}

        # 按申请人分组
        person_totals: dict[str, float] = defaultdict(float)
        person_counts: dict[str, int] = defaultdict(int)
        person_names: dict[str, str] = {}
        for r in reimbs:
            person_totals[r.applicant_id] += r.total_amount or 0
            person_counts[r.applicant_id] += 1
            if r.applicant_name:
                person_names[r.applicant_id] = r.applicant_name

        # 查找缺失的姓名（兼容 wecom_user_id 和 employee_no 两种 applicant_id 格式）
        missing_ids = [uid for uid in person_totals if uid not in person_names]
        if missing_ids:
            emp_result = await db.execute(
                select(Employee.wecom_user_id, Employee.employee_no, Employee.name).where(
                    or_(Employee.wecom_user_id.in_(missing_ids), Employee.employee_no.in_(missing_ids))
                )
            )
            for row in emp_result.all():
                _, emp_no, name = row
                # 用 employee_no 或 wecom_user_id 匹配
                for uid in missing_ids:
                    if uid == emp_no or uid == row[0]:
                        person_names[uid] = name

        sorted_persons = sorted(person_totals.items(), key=lambda x: x[1], reverse=order_desc)
        top_n = sorted_persons[:limit]

        order_label = "最少" if not order_desc else "最多"
        lines = [f"📊 费用排名 TOP {len(top_n)}（{desc}，{order_label}）\n"]
        for i, (uid, amount) in enumerate(top_n, 1):
            name = person_names.get(uid, uid)
            count = person_counts[uid]
            lines.append(f"  {i}. {name}  {self._fmt_money(amount)}（{count} 笔）")

        # 人员排名表格预览
        lines.append("\n| 排名 | 申请人 | 报销金额 | 报销单数 |")
        lines.append("|------|--------|----------|----------|")
        for i, (uid, amount) in enumerate(top_n, 1):
            name = person_names.get(uid, uid)
            count = person_counts[uid]
            lines.append(f"| {i} | {name} | {self._fmt_money(amount)} | {count} 笔 |")

        return {"text": "\n".join(lines), "data": {
            "top": [(person_names.get(uid, uid), amt) for uid, amt in top_n],
            "period": desc,
            "data_scope": "reimbursement",
        }}

    async def _insight_project(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_project — 项目费用统计（项目模块已下线）"""
        return {
            "text": "项目归属功能已下线，无法按项目统计费用。可改用「按费用类型查询」或「按人员查询」。",
            "data": {},
        }

    async def _insight_by_dept(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_by_dept — 部门费用排名"""
        start, end, desc = self._get_period(ctx)

        # 联查 Reimbursement + Employee
        # 兼容两种 applicant_id 格式：企微ID (manual_XXX_hash) 或工号 (EMP001)
        join_cond = or_(
            Reimbursement.applicant_id == Employee.wecom_user_id,
            Reimbursement.applicant_id == Employee.employee_no,
        )
        query = (
            select(
                Employee.department,
                func.sum(Reimbursement.total_amount).label("total"),
                func.count(Reimbursement.id).label("count"),
            )
            .join(Employee, join_cond)
            .where(Reimbursement.total_amount.is_not(None))
        )
        if start:
            query = query.where(Reimbursement.created_at >= start)
        if end:
            query = query.where(Reimbursement.created_at < end)
        query = query.group_by(Employee.department).order_by(
            func.sum(Reimbursement.total_amount).desc()
        )

        result = await db.execute(query)
        rows = result.all()

        if not rows:
            return {"text": f"📊 （{desc}）暂无部门费用数据。", "data": {"count": 0}}

        total = sum(row[1] or 0 for row in rows)

        lines = [f"📊 部门费用排名（{desc}）\n"]
        for i, (dept, amount, count) in enumerate(rows, 1):
            dept_name = dept or "未分配部门"
            pct = self._fmt_pct(amount or 0, total)
            lines.append(f"  {i}. {dept_name}  {self._fmt_money(amount or 0)}（{pct}，{count} 笔）")
        lines.append(f"\n合计：{self._fmt_money(total)}")

        # 部门费用排名表格预览
        lines.append("\n| 排名 | 部门 | 报销金额 | 占比 | 报销单数 |")
        lines.append("|------|------|----------|------|----------|")
        for i, (dept, amount, count) in enumerate(rows, 1):
            dept_name = dept or "未分配部门"
            pct = self._fmt_pct(amount or 0, total)
            lines.append(f"| {i} | {dept_name} | {self._fmt_money(amount or 0)} | {pct} | {count} 笔 |")
        lines.append(f"| **合计** | — | **{self._fmt_money(total)}** | **100%** | — |")

        return {"text": "\n".join(lines), "data": {
            "departments": [(r[0] or "未分配", r[1] or 0) for r in rows],
            "total": total, "period": desc,
        }}

    async def _insight_person(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_person — 指定员工费用查询

        使用 resolve_person() 做先精确后模糊的人名解析，
        多候选时反问用户消歧，不再用 applicant_name.contains 扩散结果。
        """
        person_slot = ctx.slots.get("person")
        person_name = person_slot.value if person_slot and person_slot.filled else ""

        if not person_name:
            return {
                "text": "请告诉我具体员工姓名，例如「查张三的费用」。如需查看全公司数据，可以说「公司花了多少」「公司报销总额」「各部门报销」等。",
                "data": {},
            }

        # 防御：过滤时间词/通用词/LLM 缺失槽位填的 None，避免被当人名查询
        if not _is_valid_person(person_name):
            return {
                "text": (
                    f"「{person_name}」不是有效的员工姓名。"
                    f"如需查全公司数据，可以说「公司报销总额」「各部门报销」"
                    f"「重复的发票」「高风险的发票」等；查具体员工请使用姓名或工号。"
                ),
                "data": {},
            }

        # 统一人名解析（先精确 ==，后模糊 contains，多候选消歧）
        resolution = await resolve_person(person_name, db, table_hint="reimbursement")

        if resolution.match_type == "not_found":
            return {"text": f"未找到员工「{person_name}」，请确认姓名或工号。", "data": {"count": 0}}

        if resolution.match_type == "disambiguate":
            return {
                "text": _format_disambiguation_prompt(resolution.candidates),
                "data": {"candidates": resolution.candidates},
            }

        # match_type == "exact"
        matching_ids = resolution.user_ids
        real_name = resolution.display_name

        # 补充部门信息
        department = ""
        if matching_ids:
            emp_result = await db.execute(
                select(Employee).where(
                    or_(
                        Employee.wecom_user_id.in_(matching_ids),
                        Employee.employee_no.in_(matching_ids),
                    )
                ).limit(1)
            )
            emp = emp_result.scalars().first()
            if emp:
                department = emp.department or ""
                real_name = emp.name or real_name

        # 查询该员工的报销单（精确 in_，不再用 applicant_name contains 模糊扩散）
        start, end, desc = self._get_period(ctx)
        query = select(Reimbursement).where(Reimbursement.applicant_id.in_(matching_ids))
        if start:
            query = query.where(Reimbursement.created_at >= start)
        if end:
            query = query.where(Reimbursement.created_at < end)

        result = await db.execute(query)
        reimbs = list(result.scalars().all())

        if not reimbs:
            return {"text": f"未找到「{real_name}」的报销记录。", "data": {"count": 0}}

        total = sum(r.total_amount or 0 for r in reimbs)
        by_status = defaultdict(lambda: [0, 0.0])
        for r in reimbs:
            by_status[r.status][0] += 1
            by_status[r.status][1] += r.total_amount or 0

        # 查找该员工的发票分类（精确 in_）
        inv_query = select(Invoice).where(Invoice.user_id.in_(matching_ids))
        if start:
            inv_query = inv_query.where(Invoice.created_at >= start)
        if end:
            inv_query = inv_query.where(Invoice.created_at < end)
        inv_result = await db.execute(inv_query)
        cat_totals: dict[str, float] = defaultdict(float)
        for inv in inv_result.scalars().all():
            cat = inv.fee_subcategory or "未分类"
            cat_totals[cat] += self._safe_float(inv.total_with_tax)

        status_names = {
            ReimbursementStatus.draft: "草稿",
            ReimbursementStatus.submitted: "待审批",
            ReimbursementStatus.reviewed: "已审核",
            ReimbursementStatus.reviewed: "已报销",
        }

        lines = [f"📊 {real_name}的费用情况（{desc}）\n"]
        if department:
            lines.append(f"🏢 部门：{department}")
        lines.append(f"💰 报销总额：{self._fmt_money(total)}")
        lines.append(f"📋 报销单数：{len(reimbs)} 笔")
        lines.append("")
        for status, name in status_names.items():
            if status in by_status:
                cnt, amt = by_status[status]
                lines.append(f"  {name}：{self._fmt_money(amt)}（{cnt} 笔）")

        if cat_totals:
            lines.append(f"\n📈 主要费用类别：")
            for cat, amount in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)[:5]:
                lines.append(f"  {cat}：{self._fmt_money(amount)}")

        return {"text": "\n".join(lines), "data": {
            "name": real_name, "total": total,
            "count": len(reimbs), "period": desc,
        }}

    async def _insight_compare(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_compare — 全公司本月 vs 上月对比"""
        now = datetime.now(timezone.utc)
        this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 1:
            last_start = now.replace(year=now.year - 1, month=12, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)
        else:
            last_start = now.replace(month=now.month - 1, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)

        # 本月
        r1 = await db.execute(
            select(Reimbursement).where(
                Reimbursement.created_at >= this_start,
                Reimbursement.total_amount.is_not(None),
            )
        )
        this_reimbs = list(r1.scalars().all())
        this_total = sum(r.total_amount or 0 for r in this_reimbs)
        this_persons = set(r.applicant_id for r in this_reimbs)

        # 上月
        r2 = await db.execute(
            select(Reimbursement).where(
                Reimbursement.created_at >= last_start,
                Reimbursement.created_at < this_start,
                Reimbursement.total_amount.is_not(None),
            )
        )
        last_reimbs = list(r2.scalars().all())
        last_total = sum(r.total_amount or 0 for r in last_reimbs)
        last_persons = set(r.applicant_id for r in last_reimbs)

        trend = self._trend_arrow(this_total, last_total)
        person_trend = self._trend_arrow(len(this_persons), len(last_persons))

        lines = [
            f"📊 公司费用对比（本月 vs 上月）\n",
            f"  本月（{now.year}年{now.month}月）：{self._fmt_money(this_total)}（{len(this_reimbs)} 笔，{len(this_persons)} 人）",
            f"  上月（{last_start.year}年{last_start.month}月）：{self._fmt_money(last_total)}（{len(last_reimbs)} 笔，{len(last_persons)} 人）",
            f"\n📈 报销金额环比：{trend}",
            f"📈 报销人数环比：{person_trend}",
        ]

        # 本月 vs 上月对比表格
        lines.append("\n| 周期 | 报销金额 | 报销单数 | 报销人数 |")
        lines.append("|------|----------|----------|----------|")
        lines.append(f"| 本月（{now.year}年{now.month}月） | {self._fmt_money(this_total)} | {len(this_reimbs)} 笔 | {len(this_persons)} 人 |")
        lines.append(f"| 上月（{last_start.year}年{last_start.month}月） | {self._fmt_money(last_total)} | {len(last_reimbs)} 笔 | {len(last_persons)} 人 |")

        return {"text": "\n".join(lines), "data": {
            "this_month": this_total, "last_month": last_total,
            "trend": trend, "period": f"{last_start.year}年{last_start.month}月 vs {now.year}年{now.month}月",
        }}

    # ============================================================
    # 辅助方法
    # ============================================================

    def _get_period(self, ctx: DialogContext) -> tuple[datetime | None, datetime | None, str]:
        """从上下文槽位解析时间段

        优先级：
        1. NLU/Tool 参数填充的 period slot（Agent 路径下 LLM 直接输出标准 period 标识）
        2. period slot 值为中文口语词时，PeriodResolver 内部用 _extract_period 兜底
        3. 兜底：全部时间

        注：原"从 ctx.current_text 提取时间段"的正则兜底已删除
        —— 让 LLM 在 NLU 阶段就把"上上周""前天""Q2""本月"等口语词转为标准 period 标识
        """
        # period slot（Agent 路径下 LLM 直接输出标准 period 标识）
        period_slot = ctx.slots.get("period")
        period_val = period_slot.value if period_slot and period_slot.filled else None
        return PeriodResolver.resolve(period_val, ctx.current_text)

    @staticmethod
    async def _resolve_person_to_user_ids(
        person: str, db: AsyncSession
    ) -> list[str]:
        """[已废弃·兼容封装] 将人员标识解析为 user_id 列表

        保留给已有调用方使用。新代码应直接调用 resolve_person()
        以获取消歧信息。本方法在多候选时返回空列表（保守策略）。
        """
        result = await resolve_person(person, db, table_hint="invoice")
        if result.match_type == "exact":
            return result.user_ids
        return []


    @staticmethod
    def _safe_float(val: Any) -> float:
        """安全转换为 float（Invoice.total_with_tax 是 String，可能含"200元"等非数字字符）"""
        if not val:
            return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            # 提取首个数字部分（兼容"200元""¥500.00"等脏数据）
            import re
            m = re.search(r"\d+(?:\.\d+)?", str(val))
            return float(m.group()) if m else 0.0

    @staticmethod
    def _fmt_money(amount: float) -> str:
        """格式化金额：¥1,234.56"""
        return f"¥{amount:,.2f}"

    @staticmethod
    def _fmt_pct(part: float, total: float) -> str:
        """格式化百分比：35.2%"""
        if total == 0:
            return "0.0%"
        return f"{part / total * 100:.1f}%"

    @staticmethod
    def _trend_arrow(current: float, previous: float) -> str:
        """趋势箭头：↑15.3% / ↓8.5% / 持平"""
        if previous == 0:
            if current > 0:
                return "新增"
            return "持平"
        change = (current - previous) / previous * 100
        if change > 5:
            return f"↑{change:.1f}%"
        elif change < -5:
            return f"↓{abs(change):.1f}%"
        return f"持平（{change:+.1f}%）"

    @staticmethod
    def _inv_status_text(invoice: Invoice) -> str:
        """发票状态中文文本"""
        status_map = {
            InvoiceStatus.uploaded: "已上传",
            InvoiceStatus.processing: "处理中",
            InvoiceStatus.reviewing: "待审核",
            InvoiceStatus.reviewed: "已确认",
            InvoiceStatus.reviewed: "已报销",
            InvoiceStatus.rejected: "不予报销",
        }
        return status_map.get(invoice.status, str(invoice.status))

    async def _resolve_user_names(
        self, user_ids: list[str], db: AsyncSession
    ) -> dict[str, str]:
        """批量查询 user_id → 真实姓名映射"""
        if not user_ids:
            return {}
        emp_result = await db.execute(
            select(Employee.wecom_user_id, Employee.employee_no, Employee.name).where(
                or_(Employee.wecom_user_id.in_(user_ids), Employee.employee_no.in_(user_ids))
            )
        )
        name_map: dict[str, str] = {}
        for row in emp_result.all():
            wecom_id, emp_no, name = row
            if wecom_id:
                name_map[wecom_id] = name
            if emp_no:
                name_map[emp_no] = name
        return name_map

    # ============================================================
    # 新增意图：发票统计 + 发票筛选 + 员工发票统计
    # ============================================================

    async def _insight_invoice_total(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_invoice_total — 全公司发票统计（张数+金额+按状态分组）

        支持 person 筛选：当用户指定员工时，仅统计该员工的发票。
        """
        start, end, desc = self._get_period(ctx)

        # --- 人员筛选 ---
        person_slot = ctx.slots.get("person")
        person_val = person_slot.value if person_slot and person_slot.filled else None
        # 仅信任 LLM 提取的 person slot，不再用 _extract_person 文本兜底
        # （文本兜底会把"查看公司所有"等误提取为人名，导致全公司查询失败）

        person_label = None  # 显示用
        if person_val and _is_valid_person(person_val):
            # 统一人名解析（先精确 ==，后模糊 contains，多候选消歧）
            resolution = await resolve_person(person_val, db, table_hint="invoice")
            if resolution.match_type == "not_found":
                return {
                    "text": f"未找到员工「{person_val}」，请确认姓名或工号。",
                    "data": {"count": 0, "person": person_val},
                }
            if resolution.match_type == "disambiguate":
                return {
                    "text": _format_disambiguation_prompt(resolution.candidates),
                    "data": {"candidates": resolution.candidates},
                }
            # exact
            matching_ids = resolution.user_ids
            person_label = resolution.display_name or person_val
            query = select(Invoice).where(
                Invoice.user_id.in_(matching_ids),
                Invoice.status != InvoiceStatus.processing,
            )
        else:
            query = select(Invoice).where(Invoice.status != InvoiceStatus.processing)

        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        scope_label = f"员工{person_label}" if person_label else "全公司"
        if not invoices:
            return {"text": f"📊 发票统计（{desc}，{scope_label}）\n\n暂无发票记录。", "data": {"count": 0}}

        total_amount = sum(self._safe_float(inv.total_with_tax) for inv in invoices)
        tax_amount = sum(self._safe_float(inv.tax_amount) for inv in invoices)

        # 按状态分组
        by_status: dict[str, list] = defaultdict(list)
        for inv in invoices:
            by_status[inv.status.value].append(inv)

        lines = [f"📊 发票统计（{desc}，{scope_label}）\n"]
        lines.append(f"📋 发票张数：{len(invoices)} 张")
        lines.append(f"💰 价税合计：{self._fmt_money(total_amount)}")
        lines.append(f"🧾 税额合计：{self._fmt_money(tax_amount)}")
        lines.append("")
        status_names = {
            "uploaded": "已上传", "processing": "处理中",
            "reviewing": "待审核", "confirmed": "已确认",
            "reimbursed": "已报销", "not_reimbursed": "不予报销",
        }
        for status_val, name in status_names.items():
            invs = by_status.get(status_val, [])
            if invs:
                amt = sum(self._safe_float(inv.total_with_tax) for inv in invs)
                lines.append(f"  {name}：{len(invs)} 张，{self._fmt_money(amt)}")

        # 追加发票列表表格（最多 20 条，便于管理员查看明细）
        if invoices:
            lines.append("")
            lines.append("| 序号 | 类型 | 销售方 | 金额 | 用途 | 出差日期 | 状态 | 上传时间 |")
            lines.append("|------|------|--------|------|------|----------|------|----------|")
            for idx, inv in enumerate(invoices[:20], 1):
                rt = inv.receipt_type.value if inv.receipt_type else "未知"
                seller = (inv.seller_name or "无票报销")[:10]
                amt = inv.total_with_tax or "—"
                desc_short = (inv.user_description or "待补充")[:12]
                expense_date = str(inv.expense_date) if inv.expense_date else "—"
                st = self._inv_status_text(inv)
                created = inv.created_at.strftime("%Y-%m-%d %H:%M") if inv.created_at else "—"
                lines.append(f"| {idx} | {rt} | {seller} | ¥{amt} | {desc_short} | {expense_date} | {st} | {created} |")
            if len(invoices) > 20:
                lines.append(f"| **...** | | | | | | | 共 {len(invoices)} 张，仅展示前 20 条 |")

        return {"text": "\n".join(lines), "data": {
            "count": len(invoices), "total_amount": total_amount,
            "tax_amount": tax_amount, "period": desc,
            "person": person_label,
        }}

    async def _insight_invoice_filter(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """insight_invoice_filter — 按条件筛选发票列表"""
        start, end, desc = self._get_period(ctx)

        filter_type_slot = ctx.slots.get("filter_type")
        filter_type = filter_type_slot.value if filter_type_slot and filter_type_slot.filled else None

        # NLU 兜底：LLM 偶尔把费用分类词误填进 filter_type 槽位
        # filter_type 严格枚举仅 duplicate/invalid/high_risk/pending/receipt，其他值需 LLM 判定
        _VALID_FILTER_TYPES = {"duplicate", "invalid", "high_risk", "pending", "receipt"}
        if filter_type and filter_type not in _VALID_FILTER_TYPES:
            from app.services.llm_service import get_llm_service
            llm_svc = get_llm_service()
            kind = (
                await llm_svc.classify_filter_type(filter_type)
                if llm_svc.is_available() else "category"
            )
            if kind == "category":
                logger.info(
                    "filter_type %r classified as fee category, delegating to category_amount",
                    filter_type,
                )
                ctx.fill_slot("fee_category_keyword", filter_type)
                return await self._insight_category_amount(ctx, db)

        # 人名筛选（可选）— "陈辉的重复发票"等
        person_slot = ctx.slots.get("person")
        person_name = person_slot.value if person_slot and person_slot.filled else ""
        person_label = ""
        matching_user_ids: list[str] | None = None

        if person_name and _is_valid_person(person_name):
            resolution = await resolve_person(person_name, db, table_hint="invoice")
            if resolution.match_type == "not_found":
                return {"text": f"未找到员工「{person_name}」，请确认姓名或工号。", "data": {"count": 0}}
            if resolution.match_type == "disambiguate":
                return {
                    "text": _format_disambiguation_prompt(resolution.candidates),
                    "data": {"candidates": resolution.candidates},
                }
            matching_user_ids = resolution.user_ids
            person_label = resolution.display_name or person_name

        # 基础查询（排除 processing 脏数据）
        query = select(Invoice).where(Invoice.status != InvoiceStatus.processing)
        if matching_user_ids is not None:
            query = query.where(Invoice.user_id.in_(matching_user_ids))
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        # 按 filter_type 筛选
        filter_labels = {
            "duplicate": "重复发票",
            "invalid": "验真失败",
            "high_risk": "高风险票据",
            "pending": "待审核发票",
            "receipt": "收据",
        }

        if filter_type == "duplicate":
            matched = [inv for inv in invoices if inv.duplicate_status == DuplicateStatus.duplicate]
        elif filter_type == "invalid":
            matched = [inv for inv in invoices if inv.verify_status == VerifyStatus.invalid]
        elif filter_type == "high_risk":
            matched = [inv for inv in invoices if inv.is_nonstandard and inv.risk_level == "high"]
        elif filter_type == "pending":
            matched = [inv for inv in invoices if inv.status == InvoiceStatus.reviewing]
        elif filter_type == "receipt":
            matched = [inv for inv in invoices if inv.receipt_type == ReceiptType.receipt]
        else:
            # 无明确筛选条件 → 返回全部有异常标记的发票
            matched = [inv for inv in invoices if
                       inv.duplicate_status == DuplicateStatus.duplicate
                       or inv.verify_status == VerifyStatus.invalid
                       or (inv.is_nonstandard and inv.risk_level == "high")]
            filter_type = "all_issues"
            filter_labels["all_issues"] = "异常发票"

        label = filter_labels.get(filter_type, "发票")
        person_desc = f"「{person_label}」的" if person_label else ""

        if not matched:
            return {
                "text": f"📋 {label}筛选（{person_desc}{desc}）\n\n未找到符合条件的发票。",
                "data": {"count": 0, "filter_type": filter_type},
            }

        # 查询上传者姓名（批量）
        uploader_ids = list(set(inv.user_id for inv in matched if inv.user_id))
        uploader_names = await self._resolve_user_names(uploader_ids, db)

        lines = [f"📋 {label}筛选（{person_desc}{desc}，共 {len(matched)} 张）\n"]
        total = sum(self._safe_float(inv.total_with_tax) for inv in matched)
        lines.append(f"💰 金额合计：{self._fmt_money(total)}")
        lines.append("")

        for inv in matched[:15]:
            seller = inv.seller_name or "未知"
            amount = inv.total_with_tax or "—"
            status = self._inv_status_text(inv)
            uploader = uploader_names.get(inv.user_id, inv.user_id or "未知")
            lines.append(f"  #{inv.id} | {seller} | ¥{amount} | {status} | 上传者：{uploader}")

        if len(matched) > 15:
            lines.append(f"\n  ...等 {len(matched)} 张")

        return {"text": "\n".join(lines), "data": {
            "count": len(matched), "total": total,
            "filter_type": filter_type, "period": desc,
        }}

    async def _self_invoice_total(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_invoice_total — 本人发票统计（排除 processing 脏数据）"""
        start, end, desc = self._get_period(ctx)
        query = select(Invoice).where(
            Invoice.user_id == ctx.user_id,
            Invoice.status != InvoiceStatus.processing,
        )
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        if not invoices:
            return {"text": f"📊 您的发票统计（{desc}）\n\n暂无发票记录。", "data": {"count": 0}}

        total_amount = sum(self._safe_float(inv.total_with_tax) for inv in invoices)
        by_status: dict[str, int] = defaultdict(int)
        for inv in invoices:
            by_status[inv.status.value] += 1

        lines = [f"📊 您的发票统计（{desc}）\n"]
        lines.append(f"📋 发票张数：{len(invoices)} 张")
        lines.append(f"💰 价税合计：{self._fmt_money(total_amount)}")
        lines.append("")
        status_names = {
            "uploaded": "已上传", "processing": "处理中",
            "reviewing": "待审核", "confirmed": "已确认",
            "reimbursed": "已报销", "not_reimbursed": "不予报销",
        }
        for status_val, name in status_names.items():
            cnt = by_status.get(status_val, 0)
            if cnt:
                lines.append(f"  {name}：{cnt} 张")

        return {"text": "\n".join(lines), "data": {
            "count": len(invoices), "total_amount": total_amount,
            "period": desc,
        }}

    async def _self_invoice_filter(
        self, ctx: DialogContext, db: AsyncSession
    ) -> dict[str, Any]:
        """self_insight_invoice_filter — 按条件筛选本人发票列表"""
        start, end, desc = self._get_period(ctx)

        filter_type_slot = ctx.slots.get("filter_type")
        filter_type = filter_type_slot.value if filter_type_slot and filter_type_slot.filled else None

        # NLU 兜底：LLM 偶尔把费用分类词（如"打车费""快递费"）误填进 filter_type 槽位
        # filter_type 严格枚举仅 duplicate/invalid/high_risk/pending/receipt
        # 非法值时让 LLM 判断这是异常条件还是费用分类词：
        # - 异常条件（重复/验真失败/高风险/待审核/收据等表述）→ 按异常筛选处理
        # - 费用分类词（打车费/快递费/差旅费等）→ 转交 _self_category_amount 用 LLM 语义筛选
        _VALID_FILTER_TYPES = {"duplicate", "invalid", "high_risk", "pending", "receipt"}
        if filter_type and filter_type not in _VALID_FILTER_TYPES:
            from app.services.llm_service import get_llm_service
            llm_svc = get_llm_service()
            kind = (
                await llm_svc.classify_filter_type(filter_type)
                if llm_svc.is_available() else "category"
            )
            if kind == "category":
                logger.info(
                    "filter_type %r classified as fee category, delegating to category_amount",
                    filter_type,
                )
                ctx.fill_slot("fee_category_keyword", filter_type)
                return await self._self_category_amount(ctx, db)
            # kind == "issue" → 继续按异常筛选处理，filter_type 保持原值
            # 走下面的中文映射逻辑

        # 仅查本人发票（排除 processing 脏数据）
        query = select(Invoice).where(
            Invoice.user_id == ctx.user_id,
            Invoice.status != InvoiceStatus.processing,
        )
        if start:
            query = query.where(Invoice.created_at >= start)
        if end:
            query = query.where(Invoice.created_at < end)

        result = await db.execute(query)
        invoices = list(result.scalars().all())

        # 按 filter_type 筛选（含中文异常表述的非枚举值映射）
        filter_labels = {
            "duplicate": "重复发票",
            "invalid": "验真失败",
            "high_risk": "高风险票据",
            "pending": "待审核发票",
            "receipt": "收据",
        }

        if filter_type == "duplicate":
            matched = [inv for inv in invoices if inv.duplicate_status == DuplicateStatus.duplicate]
        elif filter_type == "invalid":
            matched = [inv for inv in invoices if inv.verify_status == VerifyStatus.invalid]
        elif filter_type == "high_risk":
            matched = [inv for inv in invoices if inv.is_nonstandard and inv.risk_level == "high"]
        elif filter_type == "pending":
            matched = [inv for inv in invoices if inv.status == InvoiceStatus.reviewing]
        elif filter_type == "receipt":
            matched = [inv for inv in invoices if inv.receipt_type == ReceiptType.receipt]
        else:
            matched = [inv for inv in invoices if
                       inv.duplicate_status == DuplicateStatus.duplicate
                       or inv.verify_status == VerifyStatus.invalid
                       or (inv.is_nonstandard and inv.risk_level == "high")]
            filter_type = "all_issues"
            filter_labels["all_issues"] = "异常发票"

        label = filter_labels.get(filter_type, "发票")

        if not matched:
            return {
                "text": f"📋 您的{label}筛选（{desc}）\n\n未找到符合条件的发票。",
                "data": {"count": 0, "filter_type": filter_type},
            }

        lines = [f"📋 您的{label}筛选（{desc}，共 {len(matched)} 张）\n"]
        total = sum(self._safe_float(inv.total_with_tax) for inv in matched)
        lines.append(f"💰 金额合计：{self._fmt_money(total)}")
        lines.append("")

        for inv in matched[:15]:
            seller = inv.seller_name or "未知"
            amount = inv.total_with_tax or "—"
            status = self._inv_status_text(inv)
            lines.append(f"  #{inv.id} | {seller} | ¥{amount} | {status}")

        if len(matched) > 15:
            lines.append(f"\n  ...等 {len(matched)} 张")

        return {"text": "\n".join(lines), "data": {
            "count": len(matched), "total": total,
            "filter_type": filter_type, "period": desc,
        }}


# ============================================================
# 全局单例
# ============================================================

_insight_engine: Optional[InsightEngine] = None


def get_insight_engine() -> InsightEngine:
    """获取 Insight Engine 单例"""
    global _insight_engine
    if _insight_engine is None:
        _insight_engine = InsightEngine()
    return _insight_engine


# ============================================================
# 时间段提取 — 从自然语言文本中提取标准化 period 标识
# ============================================================

# 不应被识别为人员名的时间/通用词（精确匹配）
_NON_PERSON_WORDS = frozenset({
    "今天", "昨天", "今日", "昨日", "本周", "这周", "这一周",
    "上周", "上一周", "这个月", "本月", "上个月", "上月", "个月",
    "今年", "去年", "最近", "近半年", "最近半年", "最近一年",
    "公司", "全公司", "全部", "所有人", "一共", "总共", "多少",
    # 补全缺失的高频时间副词 — 防止被误识别为人名
    "目前", "现在", "当前", "至今", "迄今", "暂时",
    "刚才", "刚刚", "近期", "这几天",
    # 英文通用词 — LLM 偶发将"所有/全部"翻译成英文填入 person slot
    "all", "total", "everyone", "everybody", "all_users",
    "all_employees", "whole", "entire",
    # LLM 偶发将缺失槽位填为字面 "None"/"null"/"未指定"
    "none", "null", "n/a", "na", "未指定", "未知", "无",
})

# 候选人名不应以后缀词结尾（防止日期碎片"月一共"等被误识别）
_NON_PERSON_SUFFIXES = frozenset({
    "一共", "总共", "多少", "个月",
    "今天", "昨天", "今日", "昨日", "本周", "这周", "上周",
})


def _is_valid_person(candidate: str) -> bool:
    """检查候选名是否为有效人员名（排除时间词和日期碎片）"""
    if not candidate:
        return False
    # case-insensitive 比较，防止 LLM 偶发填 "None"/"NULL"/"N/A"
    lower = candidate.lower() if isinstance(candidate, str) else str(candidate).lower()
    if lower in {w.lower() for w in _NON_PERSON_WORDS}:
        return False
    if candidate in _NON_PERSON_WORDS:
        return False
    return not any(candidate.endswith(s) for s in _NON_PERSON_SUFFIXES)


def _extract_person(text: str) -> str | None:
    """从文本中提取人员标识（姓名/工号/用户ID）

    识别模式（按优先级）：
    1. "员工XXX" — 最明确，XXX 为字母数字ID或中文名
    2. "XXX [今天/一共] 上传" — 人名后接时间词再接"上传"
    3. "XXX的发票" — 人名接"的发票"
    4. "XXX有多少...发票" / "XXX有几张...发票" — 人名接数量词

    使用非贪婪匹配 + 时间词过滤 + 负向后顾(?<!\\d)，
    避免"8月一共上传了多少发票"等日期碎片被误识别为人名。
    """
    # 人员名 token：字母数字(2-20) 或 中文名(2-6, 非贪婪)
    _NAME = r'([a-zA-Z0-9_]{2,20}|[\u4e00-\u9fa5]{2,6}?)'
    # 可出现在人名和"上传"之间的时间词
    _TIME_OPT = r'\s*(?:一共|今天|昨天|今日|昨日|本周|这周|上周)?\s*'

    # Pattern 1: "员工XXX" — 带前瞻停止词
    m = re.search(
        r'员工\s*' + _NAME +
        r'(?=\s*(?:上传|传了|一共|今天|昨天|今日|昨日|本周|这周|上周'
        r'|的|多少|总共|共|[，。？！,?!]|\s|$))',
        text,
    )
    if m:
        candidate = m.group(1)
        if _is_valid_person(candidate):
            return candidate

    # Pattern 2: "XXX [time] 上传" — 负向后顾过滤数字前缀(如"8月")，
    # 遍历所有匹配，跳过时间词和日期碎片后缀
    for m in re.finditer(r'(?<!\d)' + _NAME + _TIME_OPT + r'上传', text):
        candidate = m.group(1)
        if _is_valid_person(candidate):
            return candidate

    # Pattern 3: "XXX的发票" — 负向后顾过滤数字前缀
    for m in re.finditer(r'(?<!\d)' + _NAME + r'\s*的发票', text):
        candidate = m.group(1)
        if _is_valid_person(candidate):
            return candidate

    # Pattern 4: "XXX有多少张发票" / "XXX有几张发票" / "XXX有多少发票"
    # 处理"8月陈辉有多少张发票"等不带"的"和"上传"的人名+数量词+发票
    for m in re.finditer(
        r'(?<!\d)' + _NAME + r'\s*(?:有多少|有几张|有多少张|有多少张发票).{0,2}发票',
        text,
    ):
        candidate = m.group(1)
        if _is_valid_person(candidate):
            return candidate

    return None


def _extract_period(text: str) -> str | None:
    """从文本中提取时间段关键词

    返回标准化的 period 标识，由 PeriodResolver 解析为日期范围。
    """
    if '今天' in text or '今日' in text:
        return "today"
    if '昨天' in text or '昨日' in text:
        return "yesterday"
    if '本周' in text or '这周' in text or '这一周' in text:
        return "current_week"
    if '上周' in text or '上一周' in text:
        return "last_week"
    if '本月' in text or '这个月' in text:
        return "current_month"
    if '上月' in text or '上个月' in text:
        return "last_month"
    if '本年' in text or '今年' in text:
        return "current_year"
    if '去年' in text or '上一年' in text:
        return "last_year"
    if '最近半年' in text or '近半年' in text:
        return "last_6_months"
    if '最近一年' in text or '近一年' in text or '最近12个月' in text:
        return "last_12_months"
    # 具体月份 YYYY-MM
    m = re.search(r'(\d{4})[-年](\d{1,2})月?', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    # 具体年份 YYYY
    m = re.search(r'\b(20\d{2})\b', text)
    if m and '月' not in text:
        return m.group(1)
    # 裸月份 "N月" → 补当前年份
    m = re.search(r'(?<!\d)(\d{1,2})月', text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            now = datetime.now(timezone.utc)
            return f"{now.year}-{month:02d}"
    return None
