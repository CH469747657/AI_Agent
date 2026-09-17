"""周期配置端点集成测试（简化版）

设计原则：
- fixture 保存测试前的原值，teardown 恢复为原值，**不污染生产配置**
- 测试断言用 fixture 保存的原值，不硬编码 20（生产可能是 25 等其他值）
"""

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
async def _preserve_cycle_end_setting():
    """保存测试前的原值，测试后恢复原值，避免污染生产配置

    之前 fixture 硬编码把 cycle_end_day 重置为 20，导致用户配置的 25 被改成 20。
    现改为：测试前记录 cycle_end_day + next_cycle_end_day，teardown 恢复为原值。
    测试用例通过 initial_cycle_end_day fixture 拿到测试前的 cycle_end_day 做断言。
    """
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    session_factory = db_module.get_async_sessionmaker()
    async with session_factory() as session:
        row = (
            await session.execute(select(SystemSettings).where(SystemSettings.id == 1))
        ).scalar_one_or_none()
        original_cycle_end_day = row.cycle_end_day if row else 20
        original_next_cycle_end_day = row.next_cycle_end_day if row else None
        # 测试前重置为原值（清掉前一个测试残留的 next）
        await session.execute(
            update(SystemSettings)
            .where(SystemSettings.id == 1)
            .values(
                cycle_end_day=original_cycle_end_day,
                next_cycle_end_day=None,  # 清掉 next，测试统一从无 next 状态开始
            )
        )
        await session.commit()
    cycle_end_service.invalidate_cache()

    yield original_cycle_end_day

    # teardown：恢复原值
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    async with session_factory() as session:
        await session.execute(
            update(SystemSettings)
            .where(SystemSettings.id == 1)
            .values(
                cycle_end_day=original_cycle_end_day,
                next_cycle_end_day=original_next_cycle_end_day,
            )
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
async def test_get_cycle_default(admin_token, _preserve_cycle_end_setting):
    """GET 返回测试前的 cycle_end_day + 无 next_cycle_end_day"""
    initial_cycle_end_day = _preserve_cycle_end_setting
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/settings/cycle", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["cycle_end_day"] == initial_cycle_end_day  # 测试前的原值
    assert body["next_cycle_end_day"] is None  # fixture 清空 next
    assert body["current_cycle_start"]
    assert body["current_cycle_end"]
    assert body["next_cycle_start"]
    assert body["next_cycle_end"]


@pytest.mark.asyncio
async def test_put_cycle_then_get(admin_token, _preserve_cycle_end_setting):
    """PUT next_cycle_end_day=15 应写入 next_cycle_end_day，cycle_end_day 不变"""
    initial_cycle_end_day = _preserve_cycle_end_setting
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"next_cycle_end_day": 15}, headers=headers)
        assert r.status_code == 200
        body = r.json()
        # cycle_end_day 不变（保持测试前原值），next_cycle_end_day 写入 15
        assert body["cycle_end_day"] == initial_cycle_end_day
        assert body["next_cycle_end_day"] == 15
        assert body["current_cycle_start"]
        assert body["current_cycle_end"]
        assert body["next_cycle_start"]
        assert body["next_cycle_end"]

        # GET 也返回 next 值
        r = await ac.get("/api/settings/cycle", headers=headers)
        body = r.json()
        assert body["cycle_end_day"] == initial_cycle_end_day
        assert body["next_cycle_end_day"] == 15


@pytest.mark.asyncio
async def test_put_change_next_back_to_current(admin_token, _preserve_cycle_end_setting):
    """改回原值场景：PUT 15，再 PUT initial_cycle_end_day — 都应成功"""
    initial_cycle_end_day = _preserve_cycle_end_setting
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 第一步：PUT 15
        r = await ac.put("/api/settings/cycle", json={"next_cycle_end_day": 15}, headers=headers)
        assert r.status_code == 200
        assert r.json()["next_cycle_end_day"] == 15

        # 第二步：再 PUT initial_cycle_end_day（改回原值）
        r = await ac.put(
            "/api/settings/cycle",
            json={"next_cycle_end_day": initial_cycle_end_day},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["next_cycle_end_day"] == initial_cycle_end_day


@pytest.mark.asyncio
async def test_put_rejects_below_1(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"next_cycle_end_day": 0}, headers=headers)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_rejects_above_31(admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put("/api/settings/cycle", json={"next_cycle_end_day": 32}, headers=headers)
        assert r.status_code == 422
