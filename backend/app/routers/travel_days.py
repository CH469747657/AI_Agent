"""出差日 API 路由

员工端（/api/portal/travel-days*）：
- GET    /api/portal/travel-days           — 列出当前员工所有报销单的出差日
- POST   /api/portal/travel-days           — 标记一个出差日
- DELETE /api/portal/travel-days/{id}      — 按 id 删除（仅本人）
- DELETE /api/portal/travel-days/by-date/{date} — 按日期删除

管理端（/api/admin/travel-days）：
- GET    /api/admin/travel-days?reimbursement_id=N — 穿透查看任意报销单的出差日
"""

import logging
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.employee import Employee
from app.models.reimbursement import Reimbursement, ReimbursementTravelDay
from app.routers.portal_auth import get_current_employee_async
from app.routers.admin_auth import get_current_admin_or_boss
from app.schemas import TravelDayCreateRequest, TravelDayResponse
from app.services.cycle_engine import cycle_key_of, current_cycle_key
from app.services.subsidy_engine import recompute_all, day_type, subsidy_rate, load_holidays

logger = logging.getLogger(__name__)


portal_router = APIRouter()
admin_router = APIRouter()


async def _find_or_pending_reimbursement(
    db: AsyncSession, employee: Employee, travel_date: date
) -> tuple[Reimbursement | None, str]:
    """按 travel_date 找该员工当前周期的报销单

    业务规则：员工端不允许执行报销单生成操作。报销单仅由两种方式生成：
    1. 封账日（每月21日）系统自动生成
    2. 管理员手动提前生成

    员工标记出差日时：
    - 若报销单已存在（上述两种方式之一）→ 返回该报销单，travel_day 挂载上去
    - 若不存在 → 返回 (None, cycle_key)，travel_day 以 reimbursement_id=NULL + cycle_key 暂存

    Returns:
        (reimb_or_none, cycle_key)
    """
    today = date.today()
    expected_cycle_key = current_cycle_key(today)
    travel_cycle_key = cycle_key_of(travel_date)
    if travel_cycle_key != expected_cycle_key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"出差日期 {travel_date} 不在当前周期（{expected_cycle_key}），"
                f"请选择当前周期内的日期"
            ),
        )
    # 仅查询，不创建（员工端无报销单生成权限）
    result = await db.execute(
        select(Reimbursement).where(
            Reimbursement.applicant_id == employee.employee_no,
            Reimbursement.cycle_key == expected_cycle_key,
        )
    )
    reimb = result.scalars().first()
    return reimb, expected_cycle_key


def _assert_not_locked(reimb: Reimbursement | None) -> None:
    """周期已封账则禁止改 travel_days（21 日定时任务后只读）"""
    if reimb and reimb.is_cycle_locked:
        raise HTTPException(
            status_code=409,
            detail=(
                f"周期 {reimb.cycle_key} 已封账"
                f"（{reimb.locked_at.isoformat() if reimb.locked_at else ''}），"
                f"不能再修改出差日"
            ),
        )


@portal_router.get("", response_model=List[TravelDayResponse])
async def list_my_travel_days(
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """列出当前员工所有报销单的出差日（按日期升序，含未挂载的）"""
    result = await db.execute(
        select(ReimbursementTravelDay)
        .where(ReimbursementTravelDay.applicant_id == employee.employee_no)
        .order_by(ReimbursementTravelDay.travel_date)
    )
    return list(result.scalars().all())


@portal_router.post("", response_model=TravelDayResponse)
async def mark_travel_day(
    req: TravelDayCreateRequest,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """标记一个出差日

    - 报销单已存在 → 挂载到报销单 + recompute
    - 报销单不存在 → 暂存 reimbursement_id=NULL + cycle_key，等报销单生成时挂载
    """
    reimb, cycle_key = await _find_or_pending_reimbursement(db, employee, req.travel_date)
    _assert_not_locked(reimb)

    cycle_year = (reimb.cycle_start or date.today()).year if reimb else date.today().year
    holidays = await load_holidays(db, cycle_year)
    dt = day_type(req.travel_date, holidays)
    rate = subsidy_rate(req.travel_date, holidays)

    # 应用层去重：同员工同 travel_date 已存在（含未挂载）→ 409
    # PG 在 reimbursement_id=NULL 时 UniqueConstraint(reimbursement_id, travel_date) 不生效
    existing = (
        await db.execute(
            select(ReimbursementTravelDay).where(
                ReimbursementTravelDay.applicant_id == employee.employee_no,
                ReimbursementTravelDay.travel_date == req.travel_date,
            )
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail=f"出差日 {req.travel_date} 已标记")

    td = ReimbursementTravelDay(
        reimbursement_id=reimb.id if reimb else None,
        cycle_key=cycle_key,
        travel_date=req.travel_date,
        note=req.note,
        weekday=req.travel_date.weekday(),
        day_type=dt,
        base_rate=float(rate),
        applicant_id=employee.employee_no,
    )
    db.add(td)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"出差日 {req.travel_date} 已标记")

    # 报销单存在时才重算补贴；否则等报销单生成时由 aggregation_service 挂载后重算
    if reimb:
        await recompute_all(db, reimb, holidays)
    await db.commit()
    await db.refresh(td)
    return td


@portal_router.delete("/{travel_day_id}")
async def delete_travel_day(
    travel_day_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """按 id 删除出差日（仅本人）"""
    result = await db.execute(
        select(ReimbursementTravelDay).where(ReimbursementTravelDay.id == travel_day_id)
    )
    td = result.scalars().first()
    if not td:
        raise HTTPException(status_code=404, detail="出差日不存在")
    if td.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="不能删除他人的出差日")

    reimb_id = td.reimbursement_id
    reimb = (
        await db.execute(select(Reimbursement).where(Reimbursement.id == reimb_id))
    ).scalars().first()
    if reimb:
        _assert_not_locked(reimb)

    await db.delete(td)
    await db.flush()

    if reimb:
        cycle_year = (reimb.cycle_start or date.today()).year
        holidays = await load_holidays(db, cycle_year)
        await recompute_all(db, reimb, holidays)

    await db.commit()
    return {"deleted": True, "id": travel_day_id}


@portal_router.delete("/by-date/{travel_date}")
async def delete_travel_day_by_date(
    travel_date: date,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """按日期删除出差日（员工端日历点取消更直观）"""
    result = await db.execute(
        select(ReimbursementTravelDay).where(
            ReimbursementTravelDay.applicant_id == employee.employee_no,
            ReimbursementTravelDay.travel_date == travel_date,
        )
    )
    td = result.scalars().first()
    if not td:
        raise HTTPException(status_code=404, detail=f"出差日 {travel_date} 不存在")

    reimb_id = td.reimbursement_id
    reimb = (
        await db.execute(select(Reimbursement).where(Reimbursement.id == reimb_id))
    ).scalars().first()
    if reimb:
        _assert_not_locked(reimb)

    await db.delete(td)
    await db.flush()

    if reimb:
        cycle_year = (reimb.cycle_start or date.today()).year
        holidays = await load_holidays(db, cycle_year)
        await recompute_all(db, reimb, holidays)

    await db.commit()
    return {"deleted": True, "travel_date": travel_date.isoformat()}


@admin_router.get("", response_model=List[TravelDayResponse])
async def list_travel_days_admin(
    reimbursement_id: int = Query(..., description="报销单 ID"),
    _: dict = Depends(get_current_admin_or_boss),
    db: AsyncSession = Depends(get_db),
):
    """管理员/超级管理员穿透查看指定报销单的出差日"""
    result = await db.execute(
        select(ReimbursementTravelDay)
        .where(ReimbursementTravelDay.reimbursement_id == reimbursement_id)
        .order_by(ReimbursementTravelDay.travel_date)
    )
    return list(result.scalars().all())
