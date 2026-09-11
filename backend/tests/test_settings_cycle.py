"""周期 cutoff 配置端点集成测试（用真实 DB）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app import database as db_module


@pytest.fixture(autouse=True)
def _reset_engine():
    """每个测试前后清 engine 缓存，避免跨事件循环拿到失效连接"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


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
    assert r.json()["cycle_cutoff_day"] in (21, None)  # 21 默认或已配置值


@pytest.mark.asyncio
async def test_put_cycle_then_get(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"cycle_cutoff_day": 15}, headers=headers)
        assert r.status_code == 200
        assert r.json()["cycle_cutoff_day"] == 15

        r = await ac.get("/api/settings/cycle", headers=headers)
        assert r.json()["cycle_cutoff_day"] == 15


@pytest.mark.asyncio
async def test_put_rejects_below_1(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"cycle_cutoff_day": 0}, headers=headers)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_rejects_above_31(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"cycle_cutoff_day": 32}, headers=headers)
        assert r.status_code == 422
