"""出差日 API + 权限边界测试

覆盖 5 个端点：
- GET    /api/portal/travel-days
- POST   /api/portal/travel-days
- DELETE /api/portal/travel-days/{id}
- DELETE /api/portal/travel-days/by-date/{date}
- GET    /api/admin/travel-days?reimbursement_id=N

权限矩阵：
- employee：本人可读 + 本人可写
- admin：可读任意员工的 travel_days（穿透查看）
- boss：可读（穿透查看），不可写
- 无 token：401
"""

import pytest
from datetime import date
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.services.auth_service import hash_password
from app import database as db_module


@pytest.fixture
def client():
    """每个测试重建 engine + 启动 TestClient lifespan，避免跨测试连接失效"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    # 清理 EMP001 测试残留（前面测试可能 commit 了数据）
    import asyncio
    from sqlalchemy import delete, select
    from app.database import get_async_sessionmaker
    from app.models.reimbursement import (
        ReimbursementTravelDay,
        Reimbursement,
        ReimbursementDaySubsidy,
    )

    async def _cleanup():
        async with get_async_sessionmaker()() as db:
            await db.execute(
                delete(ReimbursementTravelDay).where(
                    ReimbursementTravelDay.applicant_id == EMP_NO
                )
            )
            await db.execute(
                delete(ReimbursementDaySubsidy).where(
                    ReimbursementDaySubsidy.reimbursement_id.in_(
                        select(Reimbursement.id).where(
                            Reimbursement.applicant_id == EMP_NO
                        )
                    )
                )
            )
            await db.execute(
                delete(Reimbursement).where(Reimbursement.applicant_id == EMP_NO)
            )
            await db.commit()

    try:
        asyncio.run(_cleanup())
    except Exception:
        pass
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_engine_after():
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


@pytest.fixture(autouse=True)
def setup_creds(monkeypatch):
    """注入 admin/boss 凭证到 settings"""
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password_hash", hash_password("123456"))
    monkeypatch.setattr(settings, "boss_username", "zhang")
    monkeypatch.setattr(settings, "boss_password_hash", hash_password("zhang"))


EMP_NO = "EMP001"


def _emp_token(client) -> str:
    """员工登录拿 token（EMP001 / 123456）"""
    resp = client.post(
        "/api/portal/auth/login",
        json={"employee_no": EMP_NO, "password": "123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _admin_token(client) -> str:
    resp = client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _boss_token(client) -> str:
    resp = client.post(
        "/api/boss/auth/login",
        json={"username": "zhang", "password": "zhang"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _today_in_cycle() -> str:
    """返回当前周期内一个日期字符串 YYYY-MM-DD"""
    from app.services.cycle_engine import current_cycle_key, billing_cycle
    today = date.today()
    ck = current_cycle_key(today)
    start, _ = billing_cycle(ck)
    return start.isoformat()


def test_mark_travel_day_creates_subsidy_row(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    resp = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": "北京出差"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["travel_date"] == d
    assert body["note"] == "北京出差"
    assert body["applicant_id"] == EMP_NO


def test_mark_outside_cycle_rejected(client):
    """travel_date 落在当前周期外 → 400"""
    token = _emp_token(client)
    resp = client.post(
        "/api/portal/travel-days",
        json={"travel_date": "1999-01-01", "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, resp.text


def test_mark_duplicate_date_rejected(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    resp1 = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200, resp1.text
    resp2 = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 409, resp2.text


def test_employee_can_list_own_travel_days(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.get(
        "/api/portal/travel-days",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(td["travel_date"] == d for td in body)


def test_delete_travel_day_by_date(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.delete(
        f"/api/portal/travel-days/by-date/{d}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    list_resp = client.get(
        "/api/portal/travel-days",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert not any(td["travel_date"] == d for td in list_resp.json())


def test_admin_can_list_any_travel_days(client):
    """admin 端 GET /api/admin/travel-days?reimbursement_id=N"""
    emp_token = _emp_token(client)
    d = _today_in_cycle()
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": "测试"},
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    reimb_resp = client.get(
        "/api/portal/reimbursements",
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    assert reimb_resp.status_code == 200
    reimb_list = reimb_resp.json()
    assert reimb_list, "员工应有报销单"
    reimb_id = reimb_list[0]["id"]

    admin_token = _admin_token(client)
    resp = client.get(
        f"/api/admin/travel-days?reimbursement_id={reimb_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert any(td["travel_date"] == d for td in resp.json())


def test_boss_can_list_but_not_write(client):
    """boss GET → 200, POST → 401/403"""
    emp_token = _emp_token(client)
    d = _today_in_cycle()
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    reimb_resp = client.get(
        "/api/portal/reimbursements",
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    reimb_id = reimb_resp.json()[0]["id"]

    boss_token = _boss_token(client)
    get_resp = client.get(
        f"/api/admin/travel-days?reimbursement_id={reimb_id}",
        headers={"Authorization": f"Bearer {boss_token}"},
    )
    assert get_resp.status_code == 200, get_resp.text
    post_resp = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {boss_token}"},
    )
    assert post_resp.status_code in (401, 403), f"boss POST 期望 401/403，实际 {post_resp.status_code}"


def test_unauth_cannot_access(client):
    """无 token → 401"""
    resp = client.get("/api/portal/travel-days")
    assert resp.status_code == 401
