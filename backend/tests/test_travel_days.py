"""迁移冒烟测试 — 验证 reimbursement_travel_days 表存在

仅一个迁移冒烟测试，其余测试在 Task 4 写
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from app.database import get_async_sessionmaker
from app.models.reimbursement import ReimbursementTravelDay


async def check_table_exists():
    """验证表存在且可查询"""
    async with get_async_sessionmaker()() as db:
        # 尝试查询表
        result = await db.execute(select(ReimbursementTravelDay.id).limit(1))
        # 不抛异常即通过
        assert result is not None


def test_travel_days_table_exists():
    """冒烟测试：reimbursement_travel_days 表存在"""
    asyncio.run(check_table_exists())
