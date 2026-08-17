"""BOSS 端认证 + 权限边界测试"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.config import settings
from app.services.auth_service import hash_password
from app import database as db_module


@pytest.fixture
def client():
    """每个测试重建 engine，避免跨测试事件循环关闭导致的连接失效"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_engine_after():
    """测试结束后也清缓存，防止下一个测试拿到旧 engine"""
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


@pytest.fixture(autouse=True)
def setup_boss_creds(monkeypatch):
    """注入 BOSS 凭证到 settings（避免依赖 .env）"""
    monkeypatch.setattr(settings, "boss_username", "zhang")
    monkeypatch.setattr(settings, "boss_password_hash", hash_password("zhang"))


def test_boss_login_success(client):
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["profile"]["role"] == "boss"
    assert body["profile"]["username"] == "zhang"
    assert body["access_token"]


def test_boss_login_wrong_password(client):
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "wrong"})
    assert resp.status_code == 401


def test_boss_login_wrong_username(client):
    resp = client.post("/api/boss/auth/login", json={"username": "other", "password": "zhang"})
    assert resp.status_code == 401


def test_boss_login_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "boss_username", "")
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    assert resp.status_code == 500


def _boss_token(client) -> str:
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    return resp.json()["access_token"]


def test_boss_can_read_invoices(client):
    token = _boss_token(client)
    resp = client.get("/api/invoices", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_can_read_reimbursements(client):
    token = _boss_token(client)
    resp = client.get("/api/reimbursements", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_can_read_employees(client):
    token = _boss_token(client)
    resp = client.get("/api/employees", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_can_read_projects(client):
    token = _boss_token(client)
    resp = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_cannot_delete_invoice(client):
    """BOSS token 调 DELETE 端点应返回 403（写端点保持 get_current_admin）"""
    token = _boss_token(client)
    resp = client.delete("/api/invoices/9999", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_cannot_approve_reimbursement(client):
    token = _boss_token(client)
    resp = client.put("/api/reimbursements/9999/approve", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_cannot_create_employee(client):
    token = _boss_token(client)
    resp = client.post("/api/employees", json={"employee_no": "X", "name": "X"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_cannot_delete_reimbursement(client):
    token = _boss_token(client)
    resp = client.delete("/api/reimbursements/9999", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_token_no_admin_access(client):
    """BOSS token 调 admin 写端点（如改密）应 403"""
    token = _boss_token(client)
    resp = client.post(
        "/api/admin/auth/change-password",
        json={"old_password": "zhang", "new_password": "newpass123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
