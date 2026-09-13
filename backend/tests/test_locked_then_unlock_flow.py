"""端到端流程：员工生成 → 封账 → 撤回 409 → unlock → 撤回 200 → 改 → 提交 → 重新封账

幂等性：测试函数自身负责预清理（不依赖 fixture teardown），因为封账报销单 DELETE 会被
assert_not_locked 挡，而 lock 端点对已封账报销单返回 400，会让后续 run 无法进行。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete
from app.main import app
from app import database as db_module
from app.database import get_async_sessionmaker
from app.models.reimbursement import (
    Reimbursement, ReimbursementItem, ReimbursementDaySubsidy, ReimbursementTravelDay,
)
from app.models.invoice import Invoice
from app.models.employee import Employee


EMP_NO = "FLOW-TEST-001"


async def _cleanup_flow_test_data():
    """删除 FLOW-TEST-001 残留数据（预清理 + 后清理通用）"""
    async with get_async_sessionmaker()() as db:
        rids = [r for r in (await db.execute(
            select(Reimbursement.id).where(Reimbursement.applicant_id == EMP_NO)
        )).scalars()]
        if rids:
            await db.execute(delete(ReimbursementItem).where(ReimbursementItem.reimbursement_id.in_(rids)))
            await db.execute(delete(ReimbursementDaySubsidy).where(ReimbursementDaySubsidy.reimbursement_id.in_(rids)))
            await db.execute(delete(ReimbursementTravelDay).where(ReimbursementTravelDay.applicant_id == EMP_NO))
            await db.execute(delete(Reimbursement).where(Reimbursement.applicant_id == EMP_NO))
        await db.execute(delete(Invoice).where(Invoice.user_id == EMP_NO))
        await db.execute(delete(Employee).where(Employee.employee_no == EMP_NO))
        await db.commit()


@pytest.fixture(autouse=True)
def _reset_engine():
    """每个测试前后清 engine 缓存，避免跨事件循环拿到失效连接"""
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


@pytest.mark.asyncio
async def test_locked_then_unlock_flow():
    """端到端：员工生成 → 封账 → 撤回 409 → unlock → 提交 → 撤回 → 重新封账

    测试函数内自负责预清理 + 后清理，保证幂等。
    """
    # === 预清理 ===
    await _cleanup_flow_test_data()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # admin 登录
            r = await ac.post("/api/admin/auth/login", json={"username": "admin", "password": "123456"})
            admin_token = r.json()["access_token"]
            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            # 创建员工
            await ac.post("/api/employees", json={
                "name": "端到端测试员工", "employee_no": EMP_NO,
                "status": 1, "password": "123456"
            }, headers=admin_headers)
            # 员工登录
            r = await ac.post("/api/portal/auth/login", json={
                "employee_no": EMP_NO, "password": "123456"
            })
            emp_token = r.json()["access_token"]
            emp_headers = {"Authorization": f"Bearer {emp_token}"}
            # 生成报销单
            r = await ac.post("/api/portal/reimbursements/generate", headers=emp_headers)
            reimb_id = r.json()["id"]

            # 1. 管理员封账
            r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=admin_headers)
            assert r.status_code == 200

            # 2. 员工尝试提交 → 409
            r = await ac.post(f"/api/portal/reimbursements/{reimb_id}/submit", headers=emp_headers)
            assert r.status_code == 409

            # 3. 管理员 unlock
            r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "员工反馈有误"}, headers=admin_headers)
            assert r.status_code == 200

            # 4. 员工现在可以提交（DRAFT 状态）
            #    注意：报销单封账时是 DRAFT，lock 没改 status，所以还是 DRAFT
            r = await ac.post(f"/api/portal/reimbursements/{reimb_id}/submit", headers=emp_headers)
            assert r.status_code == 200

            # 5. 员工撤回 → DRAFT
            r = await ac.post(f"/api/portal/reimbursements/{reimb_id}/withdraw", headers=emp_headers)
            assert r.status_code == 200

            # 6. 管理员重新封账
            r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=admin_headers)
            assert r.status_code == 200
            body = r.json()
            assert body["is_cycle_locked"] is True
            assert body["unlocked_by"] is None  # 审计字段清空
    finally:
        # === 后清理：即使测试失败也跑，保证下次 run 幂等 ===
        await _cleanup_flow_test_data()
