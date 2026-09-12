"""cycle_end_day 配置的进程级缓存层

避免每次 cycle_engine 调用都查 system_settings 表。
管理员改完 cycle_end_day 后调 invalidate_cache() 让下次读时重新加载，
同时触发 scheduler.reschedule_job 动态更新 cron trigger。
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSettings

logger = logging.getLogger(__name__)

_cycle_end_cache: Optional[int] = None  # None = 未加载


async def get_cycle_end_day(db: AsyncSession) -> int:
    """读取当前 cycle_end_day，走进程级缓存

    Returns:
        cycle_end_day（1-31），无配置时返回 20（默认 21-20 制）
    """
    global _cycle_end_cache
    if _cycle_end_cache is None:
        row = (
            await db.execute(
                select(SystemSettings).where(SystemSettings.id == 1)
            )
        ).scalar_one_or_none()
        _cycle_end_cache = row.cycle_end_day if row else 20
    return _cycle_end_cache


def invalidate_cache() -> None:
    """让下次 get_cycle_end_day 重新读库 + 触发 cron 重新注册

    管理员保存 cycle_end_day 后必须调用。
    """
    global _cycle_end_cache
    _cycle_end_cache = None
    # 通知 scheduler 重新注册 cron trigger（动态生效，不需重启）
    try:
        from app.services.scheduler_service import reschedule_cycle_lock_job
        reschedule_cycle_lock_job()
    except Exception as e:
        logger.error(
            f"Failed to reschedule cycle_lock_job: {e}. "
            f"Manual backend restart may be needed."
        )
