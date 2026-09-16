"""cycle_end_day + next_cycle_end_day 配置的进程级缓存层

避免每次 cycle_engine 调用都查 system_settings 表。
管理员改完 cycle_end_day 后调 invalidate_cache() 让下次读时重新加载，
同时触发 scheduler.reschedule_job 动态更新 cron trigger。

简化后的规则：
- cycle_end_day: 当前周期截止日（1-31）
- next_cycle_end_day: 下个周期截止日（可选，None 表示沿用 cycle_end_day）
- 封账任务触发后：若 next_cycle_end_day 不为 None，切换 cycle_end_day = next_cycle_end_day，
  next_cycle_end_day = None；新周期起点 = 上个周期截止的次日
"""

import logging
from typing import Optional, Tuple
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSettings

logger = logging.getLogger(__name__)

# 缓存：(cycle_end_day, next_cycle_end_day) 或 None = 未加载
_cache: Optional[Tuple[int, Optional[int]]] = None


async def _load(db: AsyncSession) -> Tuple[int, Optional[int]]:
    row = (
        await db.execute(
            select(SystemSettings).where(SystemSettings.id == 1)
        )
    ).scalar_one_or_none()
    if row:
        return (row.cycle_end_day, row.next_cycle_end_day)
    return (20, None)


async def get_cycle_end_day(db: AsyncSession) -> int:
    """读取当前 cycle_end_day，走进程级缓存

    Returns:
        cycle_end_day（1-31），无配置时返回 20（默认 21-20 制）
    """
    global _cache
    if _cache is None:
        _cache = await _load(db)
    return _cache[0]


async def get_next_cycle_end_day(db: AsyncSession) -> Optional[int]:
    """读取下个周期截止日（缓存层）

    Returns:
        next_cycle_end_day（1-31）或 None（沿用 cycle_end_day）
    """
    global _cache
    if _cache is None:
        _cache = await _load(db)
    return _cache[1]


def invalidate_cache() -> None:
    """让下次 get_cycle_end_day / get_next_cycle_end_day 重新读库 + 触发 cron 重新注册

    管理员保存 cycle_end_day / next_cycle_end_day 后必须调用。
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
