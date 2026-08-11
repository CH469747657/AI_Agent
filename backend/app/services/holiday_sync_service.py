"""节假日同步服务 — 使用 chinese_calendar 库自动同步国务院放假安排到 holidays 表

支持：
- 同步指定年份的法定节假日（holiday）和调休补班日（workday）
- 幂等更新：同日重复同步会覆盖 source/holiday_name，不会产生重复行
- 跨年安全：同步 year 时会覆盖 (year-1)-12-21 ~ (year)-12-20 的完整周期范围
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holiday import Holiday

logger = logging.getLogger(__name__)


async def sync_holidays_from_cn_calendar(
    db: AsyncSession, year: int
) -> dict[str, Any]:
    """从 chinese_calendar 库同步指定年份的节假日数据到 holidays 表

    Args:
        db: 数据库会话
        year: 要同步的年份（如 2026）

    Returns:
        {"year": year, "holidays_added": N, "workdays_added": M, "total": K}
    """
    try:
        import chinese_calendar  # type: ignore
    except ImportError:
        logger.error("chinese_calendar not installed")
        return {
            "year": year,
            "error": "chinese_calendar 库未安装，请检查 requirements.txt",
        }

    holidays_added = 0
    workdays_added = 0
    skipped = 0

    # 遍历该年所有日期
    d = date(year, 1, 1)
    end = date(year, 12, 31)

    while d <= end:
        try:
            # on_holiday: bool, name: str | None
            on_holiday, name = chinese_calendar.get_holiday_detail(d)
        except NotImplementedError:
            # chinese_calendar 可能不支持该日期（超出数据范围）
            skipped += 1
            d += timedelta(days=1)
            continue
        except Exception as e:
            logger.warning("Failed to get holiday detail for %s: %s", d, e)
            skipped += 1
            d += timedelta(days=1)
            continue

        # 判断日期类型
        if on_holiday:
            # 法定节假日（含周末调休放假日）
            # 排除纯周末（周六周日非节假日的不记录）
            is_weekend = d.weekday() >= 5  # 5=周六, 6=周日
            if is_weekend and not name:
                # 纯周末，非法定节假日，跳过
                d += timedelta(days=1)
                continue
            day_type = "holiday"
            holiday_name = name or "法定节假日"
        else:
            # 非节假日 → 检查是否为调休补班日
            # 调休补班：周末但 chinese_calendar 标记为非假日
            is_weekend = d.weekday() >= 5
            if not is_weekend:
                # 普通工作日，跳过
                d += timedelta(days=1)
                continue
            # 周末但标记为非假日 → 调休补班
            day_type = "workday"
            holiday_name = name or "调休补班"

        # 查询是否已存在
        existing = await db.execute(
            select(Holiday).where(Holiday.holiday_date == d)
        )
        record = existing.scalar_one_or_none()

        if record:
            # 更新已有记录
            record.day_type = day_type
            record.holiday_name = holiday_name
            record.year = year
            record.source = "cn_calendar_sync"
        else:
            # 新增记录
            record = Holiday(
                holiday_date=d,
                holiday_name=holiday_name,
                day_type=day_type,
                year=year,
                source="cn_calendar_sync",
            )
            db.add(record)

        if day_type == "holiday":
            holidays_added += 1
        else:
            workdays_added += 1

        d += timedelta(days=1)

    await db.commit()

    result = {
        "year": year,
        "holidays_added": holidays_added,
        "workdays_added": workdays_added,
        "skipped": skipped,
        "total": holidays_added + workdays_added,
    }
    logger.info("Holiday sync completed: %s", result)
    return result


async def list_holidays_by_year(
    db: AsyncSession, year: int
) -> list[dict[str, Any]]:
    """查询指定年份的节假日列表

    返回 (year-1)-12-21 ~ year-12-20 范围内的记录（覆盖完整报销周期）
    """
    start = date(year - 1, 12, 21)
    end = date(year, 12, 20)

    result = await db.execute(
        select(Holiday)
        .where(Holiday.holiday_date >= start)
        .where(Holiday.holiday_date <= end)
        .order_by(Holiday.holiday_date)
    )
    records = result.scalars().all()

    return [
        {
            "id": r.id,
            "holiday_date": r.holiday_date.isoformat(),
            "holiday_name": r.holiday_name,
            "day_type": r.day_type,
            "year": r.year,
            "source": r.source,
        }
        for r in records
    ]


async def clear_holidays_by_year(
    db: AsyncSession, year: int
) -> int:
    """清除指定年份的节假日记录（仅清除 cn_calendar_sync 来源的）

    Returns: 删除的记录数
    """
    start = date(year - 1, 12, 21)
    end = date(year, 12, 20)

    result = await db.execute(
        delete(Holiday)
        .where(Holiday.holiday_date >= start)
        .where(Holiday.holiday_date <= end)
        .where(Holiday.source == "cn_calendar_sync")
    )
    await db.commit()
    return result.rowcount or 0
