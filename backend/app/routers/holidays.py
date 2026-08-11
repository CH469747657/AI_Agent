"""节假日管理路由（管理端）

提供节假日数据的同步、查询、清除功能。
数据来源为 chinese_calendar 库（国务院放假安排）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import holiday_sync_service

router = APIRouter()


@router.post("/sync/{year}")
async def sync_holidays(
    year: int,
    db: AsyncSession = Depends(get_db),
):
    """从 chinese_calendar 库同步指定年份的节假日数据

    - 幂等：重复同步会更新已有记录
    - 包含法定节假日（holiday）和调休补班日（workday）
    """
    if year < 2024 or year > 2030:
        raise HTTPException(status_code=400, detail="年份范围应在 2024-2030 之间")

    result = await holiday_sync_service.sync_holidays_from_cn_calendar(db, year)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@router.get("/{year}")
async def list_holidays(
    year: int,
    db: AsyncSession = Depends(get_db),
):
    """查询指定年份的节假日列表"""
    return await holiday_sync_service.list_holidays_by_year(db, year)


@router.delete("/{year}")
async def clear_holidays(
    year: int,
    db: AsyncSession = Depends(get_db),
):
    """清除指定年份的节假日记录（仅清除自动同步的，手动添加的保留）"""
    deleted = await holiday_sync_service.clear_holidays_by_year(db, year)
    return {"year": year, "deleted": deleted}
