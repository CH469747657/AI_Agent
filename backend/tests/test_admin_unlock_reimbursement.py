"""管理员 unlock/lock 报销单端点测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, select

from app.main import app
from app import database as db_module
from app.database import get_async_sessionmaker
from app.models.employee import Employee
from app.models.invoice import Invoice
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementItem,
    ReimbursementDaySubsidy,
    ReimbursementTravelDay,
)
from app.services.auth_service import hash_password


EMP_NO = "UNLOCK-TEST-001"


@pytest.fixture(autouse=True)
def _reset_engine():
    """每个测试前后清 engine 缓存，避免跨事件循环拿到失效连接"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


async def _cleanup_test_data():
    """清理测试残留"""
    async with get_async_sessionmaker()() as db:
        reimb_ids_q = select(Reimbursement.id).where(
            Reimbursement.applicant_id == EMP_NO
        )
        reimb_ids = (await db.execute(reimb_ids_q)).scalars().all()
        if reimb_ids:
            await db.execute(
                delete(ReimbursementItem).where(
                    ReimbursementItem.reimbursement_id.in_(reimb_ids)
                )
            )
            await db.execute(
                delete(ReimbursementDaySubsidy).where(
                    ReimbursementDaySubsidy.reimbursement_id.in_(reimb_ids)
                )
            )
        await db.execute(
            delete(ReimbursementTravelDay).where(
                ReimbursementTravelDay.applicant_id == EMP_NO
            )
        )
        await db.execute(delete(Reimbursement).where(Reimbursement.applicant_id == EMP_NO))
        await db.execute(delete(Invoice).where(Invoice.user_id == EMP_NO))
        await db.execute(delete(Employee).where(Employee.employee_no == EMP_NO))
        await db.commit()


async def _ensure_test_employee():
    """创建测试员工"""
    from app.models.employee import EmployeeStatus

    async with get_async_sessionmaker()() as db:
        existing = await db.execute(
            select(Employee).where(Employee.employee_no == EMP_NO)
        )
        if existing.scalars().first():
            return
        emp = Employee(
            wecom_user_id=f"manual_{EMP_NO}_test",
            name="解锁测试员工",
            employee_no=EMP_NO,
            password_hash=hash_password("123456"),
            status=EmployeeStatus.active,
        )
        db.add(emp)
        await db.commit()


@pytest.fixture
async def admin_token():
    await _cleanup_test_data()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/admin/auth/login", json={"username": "admin", "password": "123456"})
        return r.json()["access_token"]


@pytest.fixture
async def setup_locked_reimbursement(admin_token):
    """创建一个已封账的测试报销单"""
    await _ensure_test_employee()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {admin_token}"}
        # 员工登录 + 生成报销单
        r = await ac.post("/api/portal/auth/login", json={
            "employee_no": EMP_NO, "password": "123456"
        })
        emp_token = r.json()["access_token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}
        r = await ac.post("/api/portal/reimbursements/generate", headers=emp_headers)
        reimb_id = r.json()["id"]
        # 直接调 lock 端点封账
        await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=headers)
    yield reimb_id
    # 清理
    await _cleanup_test_data()


@pytest.mark.asyncio
async def test_admin_unlock_locked_reimbursement(admin_token, setup_locked_reimbursement):
    """unlock 已封账报销单 → 200，审计字段填上"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "员工反馈金额错误"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_cycle_locked"] is False
    assert body["unlocked_by"] == "admin"
    assert body["unlock_reason"] == "员工反馈金额错误"
    assert body["unlocked_at"] is not None


@pytest.mark.asyncio
async def test_admin_unlock_already_unlocked(admin_token, setup_locked_reimbursement):
    """unlock 未封账报销单 → 400"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 先 unlock
        await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "测试"}, headers=headers)
        # 再 unlock → 400
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "再次"}, headers=headers)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_lock_unlocked_reimbursement(admin_token, setup_locked_reimbursement):
    """lock 已 unlock 的报销单 → 200，审计字段清空"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 先 unlock
        await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "测试"}, headers=headers)
        # 重新 lock
        r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_cycle_locked"] is True
    assert body["unlocked_by"] is None
    assert body["unlocked_at"] is None
    assert body["unlock_reason"] is None


@pytest.mark.asyncio
async def test_admin_lock_already_locked(admin_token, setup_locked_reimbursement):
    """lock 已封账报销单 → 400"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=headers)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unlock_requires_reason(admin_token, setup_locked_reimbursement):
    """不传 reason → 422"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={}, headers=headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unlock_reason_too_long(admin_token, setup_locked_reimbursement):
    """reason > 500 字 → 422"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "x" * 501}, headers=headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_employee_cannot_unlock(setup_locked_reimbursement):
    """员工 token 调 unlock → 403"""
    reimb_id = setup_locked_reimbursement
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 员工登录
        r = await ac.post("/api/portal/auth/login", json={
            "employee_no": "UNLOCK-TEST-001", "password": "123456"
        })
        emp_token = r.json()["access_token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "x"}, headers=emp_headers)
    assert r.status_code == 403
