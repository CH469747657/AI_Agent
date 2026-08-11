"""补贴计算引擎

核心算法：
1. 节假日判定：法定放假=80，调休补班=60，普通工作日=60，周末=80
2. recompute_subsidies：按「有费用发生的天」计算补贴，保留手动 included/exclude_reason
3. recompute_totals：重算 expense_total / subsidy_total / total_amount

补贴口径（已确认）：按「有费用发生的天」计，当天有任意凭证即计 1 天。
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reimbursement import (
    Reimbursement,
    ReimbursementItem,
    ReimbursementDaySubsidy,
)
from app.models.holiday import Holiday

logger = logging.getLogger(__name__)

WORKDAY_RATE = Decimal("60")
RESTDAY_RATE = Decimal("80")


# ============================================================
# 节假日数据加载
# ============================================================

async def load_holidays(db: AsyncSession, year: int) -> dict[date, str]:
    """加载指定年份的节假日到内存 dict

    Returns: {date: "holiday"|"workday"}
    """
    # 同时加载可能涉及的跨年数据（周期可能跨年）
    year_start = date(year - 1, 12, 1)
    year_end = date(year, 12, 31)
    result = await db.execute(
        select(Holiday).where(Holiday.holiday_date >= year_start, Holiday.holiday_date <= year_end)
    )
    return {h.holiday_date: h.day_type for h in result.scalars().all()}


def day_type(d: date, holidays: dict[date, str]) -> str:
    """判定某天类型：workday / weekend / holiday

    逻辑：
    - 法定放假（holidays[date]="holiday"）→ "holiday"（80元）
    - 调休补班（holidays[date]="workday"）→ "workday"（60元），即使落在周末
    - 周六周日 → "weekend"（80元）
    - 其他 → "workday"（60元）
    """
    rec = holidays.get(d)
    if rec == "holiday":
        return "holiday"
    if rec == "workday":
        return "workday"
    if d.weekday() >= 5:  # 5=周六 6=周日
        return "weekend"
    return "workday"


def subsidy_rate(d: date, holidays: dict[date, str]) -> Decimal:
    """获取某天的补贴标准"""
    return RESTDAY_RATE if day_type(d, holidays) in ("weekend", "holiday") else WORKDAY_RATE


# ============================================================
# 补贴重算
# ============================================================

async def count_items_by_date(db: AsyncSession, reimb_id: int, d: date) -> int:
    """统计某天有多少张凭证"""
    result = await db.execute(
        select(func.count(ReimbursementItem.id)).where(
            ReimbursementItem.reimbursement_id == reimb_id,
            ReimbursementItem.item_date == d,
        )
    )
    return result.scalar() or 0


async def recompute_subsidies(
    db: AsyncSession,
    reimbursement: Reimbursement,
    holidays: Optional[dict[date, str]] = None,
) -> float:
    """重算报销单的日补贴

    规则：
    1. 收集本单所有有日期的 item，去重得到日期集合
    2. upsert 日补贴行（已有行保留 included/exclude_reason）
    3. 清理不再有费用的天
    4. 汇总 subsidy_total

    Returns: subsidy_total
    """
    # 加载节假日数据（按周期起年份）
    if holidays is None:
        cycle_year = (reimbursement.cycle_start or date.today()).year
        holidays = await load_holidays(db, cycle_year)

    # 1. 收集有费用的日期
    result = await db.execute(
        select(ReimbursementItem.item_date).where(
            ReimbursementItem.reimbursement_id == reimbursement.id,
            ReimbursementItem.item_date.isnot(None),
        ).distinct()
    )
    dates_with_expense = {row for row in result.scalars().all() if row}

    # 2. 加载现有补贴行
    result = await db.execute(
        select(ReimbursementDaySubsidy).where(
            ReimbursementDaySubsidy.reimbursement_id == reimbursement.id
        )
    )
    existing = {ds.subsidy_date: ds for ds in result.scalars().all()}

    # 3. upsert：有费用的天补建/更新补贴行
    for d in sorted(dates_with_expense):
        count = await count_items_by_date(db, reimbursement.id, d)
        if d in existing:
            # 已存在 → 更新 trigger_count，保留 included/exclude_reason
            existing[d].trigger_invoice_count = count
            # 更新基本信息（day_type/rate 可能因节假日数据变更而变化）
            dt = day_type(d, holidays)
            existing[d].day_type = dt
            existing[d].base_rate = float(subsidy_rate(d, holidays))
            if existing[d].included:
                existing[d].subsidy_amount = float(subsidy_rate(d, holidays))
            continue

        # 新建
        rate = subsidy_rate(d, holidays)
        dt = day_type(d, holidays)
        db.add(ReimbursementDaySubsidy(
            reimbursement_id=reimbursement.id,
            subsidy_date=d,
            weekday=d.weekday(),
            day_type=dt,
            base_rate=float(rate),
            subsidy_amount=float(rate),
            included=True,
            trigger_invoice_count=count,
        ))

    # 4. 清理不再有费用的天（已被手动排除的也一并清理）
    for d, ds in existing.items():
        if d not in dates_with_expense:
            await db.delete(ds)

    await db.flush()

    # 5. 汇总
    result = await db.execute(
        select(func.coalesce(func.sum(ReimbursementDaySubsidy.subsidy_amount), 0)).where(
            ReimbursementDaySubsidy.reimbursement_id == reimbursement.id,
            ReimbursementDaySubsidy.included == True,  # noqa: E712
        )
    )
    subsidy_total = float(result.scalar() or 0)
    reimbursement.subsidy_total = subsidy_total
    return subsidy_total


# ============================================================
# 费用合计重算
# ============================================================

async def recompute_totals(db: AsyncSession, reimbursement: Reimbursement) -> float:
    """重算 expense_total + subsidy_total → total_amount

    从 DB 重新汇总结论：expense_total 从 items 汇总，
    subsidy_total 从 day_subsidies 中 included=True 的行汇总，
    total_amount = expense_total + subsidy_total。

    Returns: total_amount
    """
    # 费用合计 = SUM(items.amount)
    result = await db.execute(
        select(func.coalesce(func.sum(ReimbursementItem.amount), 0)).where(
            ReimbursementItem.reimbursement_id == reimbursement.id,
        )
    )
    expense_total = float(result.scalar() or 0)
    reimbursement.expense_total = expense_total

    # 补贴合计 = SUM(day_subsidies.subsidy_amount WHERE included=True)
    result = await db.execute(
        select(func.coalesce(func.sum(ReimbursementDaySubsidy.subsidy_amount), 0)).where(
            ReimbursementDaySubsidy.reimbursement_id == reimbursement.id,
            ReimbursementDaySubsidy.included == True,  # noqa: E712
        )
    )
    subsidy_total = float(result.scalar() or 0)
    reimbursement.subsidy_total = subsidy_total

    # total_amount = expense_total + subsidy_total
    total = expense_total + subsidy_total
    reimbursement.total_amount = total
    return total


async def recompute_all(
    db: AsyncSession,
    reimbursement: Reimbursement,
    holidays: Optional[dict[date, str]] = None,
) -> float:
    """先重算补贴，再重算总额（快捷入口）

    Returns: total_amount
    """
    await recompute_subsidies(db, reimbursement, holidays)
    return await recompute_totals(db, reimbursement)
