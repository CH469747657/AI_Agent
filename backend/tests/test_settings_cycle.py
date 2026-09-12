"""周期 end_day 配置端点集成测试（用真实 DB）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, update

from app.main import app
from app import database as db_module
from app.models.settings import SystemSettings
from app.services import cycle_end_service


@pytest.fixture(autouse=True)
def _reset_engine():
    """每个测试前后清 engine 缓存，避免跨事件循环拿到失效连接"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


@pytest.fixture(autouse=True)
async def _reset_cycle_end_after_test():
    """每个测试前后重置 system_settings.cycle_end_day 回默认 20 + 失效缓存

    防止 test_put_cycle_then_get 写入的 15 残留到后续 test_get_cycle_default，
    也防止历史脏数据导致首个测试失败。
    """
    # 测试开始前：清 engine 缓存拿新 session，把 DB 里的值改回 20，再清进程缓存
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    session_factory = db_module.get_async_sessionmaker()
    async with session_factory() as session:
        await session.execute(
            update(SystemSettings)
            .where(SystemSettings.id == 1)
            .values(cycle_end_day=20)
        )
        await session.commit()
    cycle_end_service.invalidate_cache()

    yield

    # 测试结束后：再次重置
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    session_factory = db_module.get_async_sessionmaker()
    async with session_factory() as session:
        await session.execute(
            update(SystemSettings)
            .where(SystemSettings.id == 1)
            .values(cycle_end_day=20)
        )
        await session.commit()
    cycle_end_service.invalidate_cache()


@pytest.fixture
async def admin_token():
    """登录拿 admin token"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/admin/auth/login", json={"username": "admin", "password": "123456"})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]


@pytest.mark.asyncio
async def test_get_cycle_default(admin_token):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/settings/cycle", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["cycle_end_day"] in (20, None)  # 20 默认或已配置值
    assert r.json()["current_cycle_start"]
    assert r.json()["current_cycle_end"]


@pytest.mark.asyncio
async def test_put_cycle_then_get(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"cycle_end_day": 15}, headers=headers)
        assert r.status_code == 200
        assert r.json()["cycle_end_day"] == 15
        assert r.json()["current_cycle_start"]
        assert r.json()["current_cycle_end"]

        r = await ac.get("/api/settings/cycle", headers=headers)
        assert r.json()["cycle_end_day"] == 15
        assert r.json()["current_cycle_start"]
        assert r.json()["current_cycle_end"]


@pytest.mark.asyncio
async def test_put_rejects_below_1(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"cycle_end_day": 0}, headers=headers)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_rejects_above_31(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"cycle_end_day": 32}, headers=headers)
        assert r.status_code == 422
