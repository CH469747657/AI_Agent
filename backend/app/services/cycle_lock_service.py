"""周期封账服务

封账流程：
1. 确定刚结束的周期 cycle_key（昨日所属周期，即 21 日 00:05 时为上一个周期）
2. 查找该周期所有报销单，设 is_cycle_locked=True + locked_at=now
3. 仍为 DRAFT 的报销单自动提交（SUBMITTED），防止封账周期遗留草稿
4. 返回封账结果摘要

也可手动指定期号封账（管理端 API）。
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reimbursement import Reimbursement, ReimbursementStatus
from app.services.cycle_engine import just_ended_cycle_key

logger = logging.getLogger(__name__)


async def lock_cycle(
    db: AsyncSession,
    cycle_key: str,
    *,
    auto_submit_drafts: bool = True,
) -> dict:
    """封账指定周期

    Args:
        cycle_key: 周期标识 YYYY-MM
        auto_submit_drafts: 是否自动提交 DRAFT 状态的报销单

    Returns:
        {cycle_key, locked_count, auto_submitted_count, total_reimbursements}
    """
    now = datetime.now(timezone.utc)

    # 查找该周期所有报销单
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.cycle_key == cycle_key)
    )
    reimbursements = list(result.scalars().all())

    locked_count = 0
    auto_submitted = 0

    for reimb in reimbursements:
        reimb.is_cycle_locked = True
        reimb.locked_at = now
        locked_count += 1

        if auto_submit_drafts and reimb.status == ReimbursementStatus.draft:
            reimb.status = ReimbursementStatus.submitted
            reimb.submitted_at = now
            auto_submitted += 1

    await db.commit()

    logger.info(
        f"Cycle lock: {cycle_key} — {locked_count} reimbursements locked, "
        f"{auto_submitted} drafts auto-submitted"
    )

    return {
        "cycle_key": cycle_key,
        "locked_count": locked_count,
        "auto_submitted_count": auto_submitted,
        "total_reimbursements": len(reimbursements),
    }


async def lock_just_ended_cycle(db: AsyncSession) -> dict:
    """封账刚结束的周期（定时任务入口）

    在每月 21 日 00:05 调用，封账上一个周期（即昨日所属周期）。
    """
    ck = just_ended_cycle_key()
    if not ck:
        logger.warning("lock_just_ended_cycle: cannot determine just-ended cycle")
        return {"cycle_key": None, "locked_count": 0, "auto_submitted_count": 0}

    return await lock_cycle(db, ck)


async def get_cycle_lock_status(db: AsyncSession, cycle_key: str) -> dict:
    """查询某周期的封账状态"""
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.cycle_key == cycle_key)
    )
    reimbursements = list(result.scalars().all())

    if not reimbursements:
        return {"cycle_key": cycle_key, "is_locked": False, "reimbursement_count": 0}

    is_locked = any(r.is_cycle_locked for r in reimbursements)
    return {
        "cycle_key": cycle_key,
        "is_locked": is_locked,
        "reimbursement_count": len(reimbursements),
        "locked_at": reimbursements[0].locked_at.isoformat() if reimbursements[0].locked_at else None,
    }
