"""cycle_end_day + cycle_transition_start 配置的进程级缓存层

避免每次 cycle_engine 调用都查 system_settings 表。
管理员改完 cycle_end_day 后调 invalidate_cache() 让下次读时重新加载，
同时触发 scheduler.reschedule_job 动态更新 cron trigger。

方案A 过渡周期机制：
- pending_cycle_end_day 切换后，下个周期用 cycle_transition_start 作起点
- 该周期封账后清空 transition_start，后续周期恢复正常公式计算
"""

import logging
from typing import Optional, Tuple
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSettings

logger = logging.getLogger(__name__)

# 缓存：(cycle_end_day, transition_start) 或 None = 未加载
_cache: Optional[Tuple[int, Optional[date]]] = None


async def get_cycle_end_day(db: AsyncSession) -> int:
    """读取当前 cycle_end_day，走进程级缓存

    Returns:
        cycle_end_day（1-31），无配置时返回 20（默认 21-20 制）
    """
    global _cache
    if _cache is None:
        row = (
            await db.execute(
                select(SystemSettings).where(SystemSettings.id == 1)
            )
        ).scalar_one_or_none()
        if row:
            _cache = (row.cycle_end_day, row.cycle_transition_start)
        else:
            _cache = (20, None)
    return _cache[0]


async def get_cycle_transition_start(db: AsyncSession) -> Optional[date]:
    """读取过渡周期起点（缓存层）

    Returns:
        cycle_transition_start（date）或 None（无过渡周期）
    """
    global _cache
    if _cache is None:
        row = (
            await db.execute(
                select(SystemSettings).where(SystemSettings.id == 1)
            )
        ).scalar_one_or_none()
        if row:
            _cache = (row.cycle_end_day, row.cycle_transition_start)
        else:
            _cache = (20, None)
    return _cache[1]


def invalidate_cache() -> None:
    """让下次 get_cycle_end_day / get_cycle_transition_start 重新读库 + 触发 cron 重新注册

    管理员保存 cycle_end_day 后必须调用。
    """
    global _cache
    _cache = None
    # 通知 scheduler 重新注册 cron trigger（动态生效，不需重启）
    try:
        from app.services.scheduler_service import reschedule_cycle_lock_job
        reschedule_cycle_lock_job()
    except Exception as e:
        logger.error(
            f"Failed to reschedule cycle_lock_job: {e}. "
            f"Manual backend restart may be needed."
        )
