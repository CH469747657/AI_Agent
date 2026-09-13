"""alembic 0016 迁移验证测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import text

from app import database as db_module
from app.database import get_async_sessionmaker


@pytest.fixture(autouse=True)
def _reset_engine():
    """每个测试前后清 engine 缓存，避免跨事件循环拿到失效连接"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


@pytest.mark.asyncio
async def test_column_renamed_to_cycle_end_day():
    """列名是 cycle_end_day（不是 cycle_cutoff_day）"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='system_settings' AND column_name IN ('cycle_end_day', 'cycle_cutoff_day')"
        ))
        cols = [r[0] for r in result]
        assert "cycle_end_day" in cols
        assert "cycle_cutoff_day" not in cols


@pytest.mark.asyncio
async def test_check_constraint_renamed():
    """CHECK 约束名是 ck_cycle_end_day_range"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_name='system_settings' AND constraint_name LIKE 'ck_cycle%'"
        ))
        names = [r[0] for r in result]
        assert "ck_cycle_end_day_range" in names
        assert "ck_cycle_cutoff_day_range" not in names


@pytest.mark.asyncio
async def test_default_value_is_20():
    """默认值是 20（不是 21）"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name='system_settings' AND column_name='cycle_end_day'"
        ))
        default = result.scalar()
        assert "20" in default


@pytest.mark.asyncio
async def test_alembic_version_is_0017():
    """alembic 版本是 0017_reimbursement_unlock_audit"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        # 0017 依赖 0016，所以跑完 0017 后 version 是 0017
        assert version == "0017_reimbursement_unlock_audit"
