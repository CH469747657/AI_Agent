"""报销单归集逻辑

将游离发票批量归集到对应周期的报销单草稿。
归集时机：管理员主动调用 API 或每月21号定时任务触发。
平时上传的发票不自动归集，以「游离」状态保存（reimbursement_id=None）。

核心函数：
- get_or_create_reimbursement：按 applicant_id + cycle_key 获取或创建报销单
- attach_invoice_to_cycle：判定费用日期 → 归入周期 → 建/更新明细行 → 重算补贴与总额
- aggregate_pending_invoices：批量归集所有游离发票（管理员/定时任务入口）
- detach_invoice_from_cycle：从周期报销单中移除发票 → 重算
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reimbursement import (
    Reimbursement,
    ReimbursementStatus,
    ReimbursementItem,
    ReimbursementTravelDay,
)
from app.models.invoice import Invoice
from app.models.employee import Employee
from app.models.holiday import Holiday
from app.services.cycle_engine import billing_cycle, current_cycle_key, cycle_key_of
from app.services.expense_date_engine import determine_expense_date
from app.services.subsidy_engine import recompute_all, load_holidays

logger = logging.getLogger(__name__)


def _parse_amount(val) -> float:
    """安全解析金额为 float"""
    if not val:
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("￥", "").replace("¥", ""))
    except (ValueError, TypeError):
        return 0.0


async def _resolve_employee_info(db: AsyncSession, applicant_id: str) -> tuple[str | None, str | None]:
    """解析员工姓名和部门"""
    result = await db.execute(
        select(Employee).where(
            (Employee.wecom_user_id == applicant_id) | (Employee.employee_no == applicant_id)
        )
    )
    emp = result.scalars().first()
    if emp:
        return (emp.name, emp.department)
    return (None, None)


async def get_or_create_reimbursement(
    db: AsyncSession,
    applicant_id: str,
    cycle_key: str,
    auto_generated: bool = True,
) -> Reimbursement:
    """按 applicant_id + cycle_key 获取或创建报销单草稿

    幂等：UNIQUE(applicant_id, cycle_key) 保证一员工一周期单份

    创建后副作用：把该员工该周期下 reimbursement_id=NULL 的 travel_days
    批量挂载到新报销单，并触发补贴重算。
    """
    result = await db.execute(
        select(Reimbursement).where(
            Reimbursement.applicant_id == applicant_id,
            Reimbursement.cycle_key == cycle_key,
        )
    )
    reimb = result.scalars().first()

    if reimb:
        return reimb

    # 创建新报销单
    cycle_start, cycle_end = billing_cycle(cycle_key)
    name, dept = await _resolve_employee_info(db, applicant_id)

    reimb = Reimbursement(
        applicant_id=applicant_id,
        applicant_name=name,
        department=dept,
        period=cycle_key,  # 兼容字段
        cycle_key=cycle_key,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        status=ReimbursementStatus.draft,
        auto_generated=auto_generated,
    )
    db.add(reimb)
    await db.flush()
    logger.info(f"Created reimbursement #{reimb.id} for {applicant_id} cycle={cycle_key}")

    # 挂载该员工该周期下未挂载的 travel_days（reimbursement_id=NULL）
    pending_result = await db.execute(
        select(ReimbursementTravelDay).where(
            ReimbursementTravelDay.applicant_id == applicant_id,
            ReimbursementTravelDay.cycle_key == cycle_key,
            ReimbursementTravelDay.reimbursement_id.is_(None),
        )
    )
    pending_tds = list(pending_result.scalars().all())
    mounted = 0
    for td in pending_tds:
        td.reimbursement_id = reimb.id
        mounted += 1
    if mounted:
        await db.flush()
        logger.info(f"Mounted {mounted} pending travel_days to reimb #{reimb.id}")
        # 重算补贴（travel_days 现在挂载到该报销单了）
        holidays = await load_holidays(db, cycle_start.year)
        await recompute_all(db, reimb, holidays)

    return reimb


async def aggregate_pending_invoices(
    db: AsyncSession,
    user_id: Optional[str] = None,
    user_ids: Optional[list[str]] = None,
) -> dict:
    """批量归集所有游离发票到对应周期的报销单

    查找 reimbursement_id IS NULL 且已处理完成（非 processing 状态）的发票，
    调用 attach_invoice_to_cycle 逐张归入。

    归集时机：
    - 管理员主动调用 POST /api/reimbursements/aggregate
    - 每月21号定时任务封账前自动执行

    Args:
        user_id: 可选，指定单个用户则只归集该用户的游离发票；None=全公司
        user_ids: 可选，指定多个用户ID（employee_no + wecom_user_id 等），
                  用 .in_() 查询，避免 set→list 顺序不确定导致漏匹配。
                  优先于 user_id。

    Returns:
        {total, attached, reimb_ids, errors}
    """
    from app.models.invoice import InvoiceStatus

    # 查找游离发票（reimbursement_id IS NULL + 非 processing）
    query = (
        select(Invoice)
        .where(Invoice.reimbursement_id.is_(None))
        .where(Invoice.status != InvoiceStatus.processing)
        .order_by(Invoice.created_at)
    )
    if user_ids:
        query = query.where(Invoice.user_id.in_(user_ids))
    elif user_id:
        query = query.where(Invoice.user_id == user_id)

    result = await db.execute(query)
    invoices = list(result.scalars().all())

    if not invoices:
        logger.info("aggregate_pending_invoices: no pending invoices found")
        return {"total": 0, "attached": 0, "reimb_ids": [], "auto_submitted": 0, "errors": []}

    attached = 0
    reimb_ids: set[int] = set()
    errors: list[dict] = []

    for inv in invoices:
        try:
            reimb = await attach_invoice_to_cycle(db, inv)
            reimb_ids.add(reimb.id)
            attached += 1
            logger.info(f"Aggregated invoice #{inv.id} → reimbursement #{reimb.id}")
        except Exception as e:
            logger.warning(f"Failed to aggregate invoice #{inv.id}: {e}")
            errors.append({"invoice_id": inv.id, "error": str(e)})

    await db.commit()

    # 归集后自动提交：将涉及的草稿报销单转为已提交状态
    # 员工端不操作报销单，归集生成后即为终态（员工视角="已关联"）
    now = datetime.now(timezone.utc)
    auto_submitted = 0
    if reimb_ids:
        result = await db.execute(
            select(Reimbursement).where(
                Reimbursement.id.in_(sorted(reimb_ids)),
                Reimbursement.status == ReimbursementStatus.draft,
            )
        )
        for reimb in result.scalars().all():
            reimb.status = ReimbursementStatus.submitted
            reimb.submitted_at = now
            auto_submitted += 1
        if auto_submitted:
            await db.commit()
            logger.info(f"Auto-submitted {auto_submitted} draft reimbursements after aggregation")

    logger.info(
        f"aggregate_pending_invoices: {attached}/{len(invoices)} invoices aggregated "
        f"into {len(reimb_ids)} reimbursements, {auto_submitted} auto-submitted, {len(errors)} errors"
    )
    return {
        "total": len(invoices),
        "attached": attached,
        "reimb_ids": sorted(reimb_ids),
        "auto_submitted": auto_submitted,
        "errors": errors,
    }


async def attach_invoice_to_cycle(
    db: AsyncSession,
    invoice: Invoice,
    today: date | None = None,
) -> Reimbursement:
    """将发票归入所属周期的报销单

    流程：
    1. determine_expense_date → 费用发生日 + source
    2. cycle_key_of → 费用发生日所属周期
    3. 若目标周期已封账 → 归入当前未封账周期，标记 late_charge
    4. 创建明细行 ReimbursementItem
    5. recompute_all → 重算补贴与总额

    Returns: 归入的报销单
    """
    today = today or date.today()

    # 1. 判定费用发生日期
    edate, src = determine_expense_date(invoice, today)
    invoice.expense_date = edate
    invoice.expense_date_source = src

    # 2. 判定目标周期
    target_ck = cycle_key_of(edate) if edate else current_cycle_key(today)
    curr_ck = current_cycle_key(today)

    # 检查目标周期是否已封账
    target_reimb = await db.execute(
        select(Reimbursement).where(
            Reimbursement.applicant_id == invoice.user_id,
            Reimbursement.cycle_key == target_ck,
        )
    )
    target_reimb = target_reimb.scalars().first()

    late = False
    intended = None

    if target_reimb and target_reimb.is_cycle_locked:
        # 目标周期已封账 → 归入当前未封账周期，标记跨期
        reimb = await get_or_create_reimbursement(db, invoice.user_id, curr_ck)
        late = True
        intended = target_ck
    else:
        # 正常归入目标周期
        reimb = target_reimb or await get_or_create_reimbursement(db, invoice.user_id, target_ck)
        late = (target_ck != curr_ck)
        intended = target_ck if late else None

    # 3. 创建明细行
    weekday = edate.weekday() if edate else None
    amount = _parse_amount(invoice.total_with_tax)

    # 如果该发票已有明细行（重复归集），先删除旧行
    result = await db.execute(
        select(ReimbursementItem).where(ReimbursementItem.invoice_id == invoice.id)
    )
    for old_item in result.scalars().all():
        await db.delete(old_item)

    item = ReimbursementItem(
        reimbursement_id=reimb.id,
        invoice_id=invoice.id,
        item_date=edate,
        item_date_source=src,
        weekday=weekday,
        fee_category=invoice.fee_category.value if invoice.fee_category else None,
        fee_subcategory=invoice.fee_subcategory,
        amount=amount,
        description=invoice.user_description,
        is_late_charge=late,
        intended_cycle_key=intended,
    )
    db.add(item)

    # 4. 关联发票到报销单
    invoice.reimbursement_id = reimb.id

    # 5. 加载节假日 + 重算补贴与总额
    cycle_year = (reimb.cycle_start or today).year
    holidays = await load_holidays(db, cycle_year)
    await recompute_all(db, reimb, holidays)

    logger.info(
        f"Invoice #{invoice.id} attached to reimbursement #{reimb.id} "
        f"(cycle={reimb.cycle_key}, date={edate}, source={src}, late={late})"
    )
    return reimb


async def detach_invoice_from_cycle(
    db: AsyncSession,
    invoice: Invoice,
) -> Optional[Reimbursement]:
    """从报销单中移除发票（删除明细行、解除关联、重算）

    Returns: 受影响的报销单（如果有）
    """
    # 找到此发票的明细行
    result = await db.execute(
        select(ReimbursementItem).where(ReimbursementItem.invoice_id == invoice.id)
    )
    item = result.scalars().first()
    if not item:
        return None

    reimb_id = item.reimbursement_id

    # 删除明细行
    await db.delete(item)

    # 解除发票关联
    invoice.reimbursement_id = None
    invoice.expense_date = None
    invoice.expense_date_source = None

    # 获取报销单并重算
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.id == reimb_id)
    )
    reimb = result.scalars().first()
    if reimb:
        cycle_year = (reimb.cycle_start or date.today()).year
        holidays = await load_holidays(db, cycle_year)
        await recompute_all(db, reimb, holidays)
        logger.info(f"Invoice #{invoice.id} detached from reimbursement #{reimb.id}")

    return reimb
