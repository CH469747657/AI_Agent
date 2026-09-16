"""cycle_end_service 进程级缓存测试（简化版）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_cache():
    """每个测试前重置缓存 + mock scheduler.reschedule_cycle_lock_job"""
    from app.services import cycle_end_service
    cycle_end_service._cache = None
    with patch("app.services.scheduler_service.reschedule_cycle_lock_job") as mock_reschedule:
        yield mock_reschedule
    cycle_end_service._cache = None


@pytest.mark.asyncio
async def test_get_cycle_end_day_returns_20_when_no_row():
    """数据库无 system_settings 行时返回默认 20"""
    from app.services import cycle_end_service

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    db.execute = mock_execute

    result = await cycle_end_service.get_cycle_end_day(db)
    assert result == 20


@pytest.mark.asyncio
async def test_get_cycle_end_day_reads_from_db():
    """数据库有行时返回行里的值"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 25
    fake_row.next_cycle_end_day = None

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    result = await cycle_end_service.get_cycle_end_day(db)
    assert result == 25


@pytest.mark.asyncio
async def test_get_cycle_end_day_uses_cache_on_second_call():
    """第二次读不查库"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 25
    fake_row.next_cycle_end_day = None

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    await cycle_end_service.get_cycle_end_day(db)
    await cycle_end_service.get_cycle_end_day(db)

    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_invalidate_cache_forces_reload(reset_cache):
    """invalidate_cache 后重新读库 + 调 reschedule_cycle_lock_job"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 15
    fake_row.next_cycle_end_day = None

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    await cycle_end_service.get_cycle_end_day(db)
    assert reset_cache.call_count == 0  # 第一次读不调 reschedule

    cycle_end_service.invalidate_cache()
    reset_cache.assert_called_once()  # invalidate_cache 触发 reschedule

    await cycle_end_service.get_cycle_end_day(db)
    assert db.execute.call_count == 2


@pytest.mark.asyncio
async def test_get_next_cycle_end_day_returns_none_by_default():
    """无下个周期配置时返回 None（沿用 cycle_end_day）"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 25
    fake_row.next_cycle_end_day = None

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    result = await cycle_end_service.get_next_cycle_end_day(db)
    assert result is None


@pytest.mark.asyncio
async def test_get_next_cycle_end_day_returns_value_when_set():
    """有下个周期配置时返回该值"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 25
    fake_row.next_cycle_end_day = 20

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    result = await cycle_end_service.get_next_cycle_end_day(db)
    assert result == 20
