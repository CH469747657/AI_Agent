"""cutoff 配置的进程级缓存层

避免每次 cycle_engine 调用都查 system_settings 表。
管理员改完 cutoff 后调 invalidate_cache() 让下次读时重新加载。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSettings

_cutoff_cache: Optional[int] = None  # None = 未加载


async def get_cutoff_day(db: AsyncSession) -> int:
    """读取当前 cycle_cutoff_day，走进程级缓存

    Returns:
        cutoff 日（1-31），无配置时返回 21
    """
    global _cutoff_cache
    if _cutoff_cache is None:
        row = (
            await db.execute(
                select(SystemSettings).where(SystemSettings.id == 1)
            )
        ).scalar_one_or_none()
        _cutoff_cache = row.cycle_cutoff_day if row else 21
    return _cutoff_cache


def invalidate_cache() -> None:
    """让下次 get_cutoff_day 重新读库

    管理员保存 cutoff 后必须调用。
    """
    global _cutoff_cache
    _cutoff_cache = None
