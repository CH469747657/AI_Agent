"""cutoff_service 进程级缓存测试"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def reset_cache():
    """每个测试前重置缓存"""
    from app.services import cutoff_service
    cutoff_service._cutoff_cache = None
    yield
    cutoff_service._cutoff_cache = None


@pytest.mark.asyncio
async def test_get_cutoff_day_returns_21_when_no_row():
    """数据库无 system_settings 行时返回默认 21"""
    from app.services import cutoff_service

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    db.execute = mock_execute

    result = await cutoff_service.get_cutoff_day(db)
    assert result == 21


@pytest.mark.asyncio
async def test_get_cutoff_day_reads_from_db():
    """数据库有行时返回行里的值"""
    from app.services import cutoff_service

    fake_row = MagicMock()
    fake_row.cycle_cutoff_day = 15

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    result = await cutoff_service.get_cutoff_day(db)
    assert result == 15


@pytest.mark.asyncio
async def test_get_cutoff_day_uses_cache_on_second_call():
    """第二次读不查库"""
    from app.services import cutoff_service

    fake_row = MagicMock()
    fake_row.cycle_cutoff_day = 25

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    await cutoff_service.get_cutoff_day(db)
    await cutoff_service.get_cutoff_day(db)

    # 第二次应该用缓存，db.execute 只调一次
    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_invalidate_cache_forces_reload():
    """invalidate_cache 后重新读库"""
    from app.services import cutoff_service

    fake_row = MagicMock()
    fake_row.cycle_cutoff_day = 15

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    await cutoff_service.get_cutoff_day(db)  # 第一次读库
    cutoff_service.invalidate_cache()         # 失效缓存
    await cutoff_service.get_cutoff_day(db)  # 应再次读库

    assert db.execute.call_count == 2
