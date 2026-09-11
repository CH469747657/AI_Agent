"""员工自生成报销单端点测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, select, text

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


EMP_NO = "TEST-001"


@pytest.fixture(autouse=True)
def _reset_engine():
    """每个测试前后清 engine 缓存，避免跨事件循环拿到失效连接"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


async def _ensure_enum_compat():
    """扩展 DB employeestatus 枚举兼容 SQLAlchemy 默认命名

    背景：alembic 0001 建表时把 enum 值写成了 {"1","2"}（字符串数字），
    但 SQLAlchemy 默认发 enum **名**（"active"/"resigned"）。
    向 DB enum 添加 "active"/"resigned" 兼容 ORM 读写，
    旧数据 "1"/"2" 仍可保留（无人写入）。
    幂等：IF NOT EXISTS。
    """
    async with get_async_sessionmaker()() as db:
        await db.execute(
            text("ALTER TYPE employeestatus ADD VALUE IF NOT EXISTS 'active' BEFORE '1'")
        )
        await db.execute(
            text("ALTER TYPE employeestatus ADD VALUE IF NOT EXISTS 'resigned' BEFORE '1'")
        )
        # ALTER TYPE ADD VALUE 不能在事务块内 — commit 隐式执行
        await db.commit()


async def _cleanup_test_data():
    """清理 TEST-001 测试残留"""
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
        await db.execute(
            delete(Reimbursement).where(Reimbursement.applicant_id == EMP_NO)
        )
        await db.execute(delete(Invoice).where(Invoice.user_id == EMP_NO))
        await db.execute(delete(Employee).where(Employee.employee_no == EMP_NO))
        await db.commit()


async def _ensure_test_employee():
    """创建测试员工

    通过 ORM 创建（status=EmployeeStatus.active），
    SQLAlchemy 发送 "active"（enum name），DB enum 已扩展兼容。
    """
    from app.models.employee import EmployeeStatus

    async with get_async_sessionmaker()() as db:
        existing = await db.execute(
            select(Employee).where(Employee.employee_no == EMP_NO)
        )
        emp = existing.scalars().first()
        if emp:
            return

        emp = Employee(
            wecom_user_id=f"manual_{EMP_NO}_test",
            name="测试员工",
            employee_no=EMP_NO,
            password_hash=hash_password("123456"),
            status=EmployeeStatus.active,
        )
        db.add(emp)
        await db.commit()


@pytest.fixture
async def employee_token():
    """创建员工 + 登录拿 token"""
    await _ensure_enum_compat()
    await _cleanup_test_data()
    await _ensure_test_employee()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/api/portal/auth/login",
            json={"employee_no": EMP_NO, "password": "123456"},
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]


@pytest.mark.asyncio
async def test_employee_generate_first_time(employee_token):
    """员工首次生成 → 200 + DRAFT 状态

    注：ReimbursementStatus.draft.value = "DRAFT"（大写），
    ReimbursementResponse 通过 pydantic 序列化时返回 "DRAFT"。
    """
    headers = {"Authorization": f"Bearer {employee_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/portal/reimbursements/generate", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DRAFT"
    assert body["applicant_id"] == EMP_NO


@pytest.mark.asyncio
async def test_employee_generate_idempotent(employee_token):
    """第二次生成 → 返回同一份 id"""
    headers = {"Authorization": f"Bearer {employee_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r1 = await ac.post("/api/portal/reimbursements/generate", headers=headers)
        r2 = await ac.post("/api/portal/reimbursements/generate", headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_unauthenticated_401():
    """未带 token → 401"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/portal/reimbursements/generate")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_generate_with_no_free_invoices(employee_token):
    """无游离发票 → 返回空报销单 DRAFT"""
    headers = {"Authorization": f"Bearer {employee_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/portal/reimbursements/generate", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DRAFT"
