"""端到端流程：员工生成 → 封账 → 撤回 409 → unlock → 撤回 200 → 改 → 提交 → 重新封账"""

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
async def setup():
    """setup admin + employee + 报销单"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # admin 登录
        r = await ac.post("/api/admin/auth/login", json={"username": "admin", "password": "123456"})
        admin_token = r.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        # 创建员工
        await ac.post("/api/employees", json={
            "name": "端到端测试员工", "employee_no": "FLOW-TEST-001",
            "status": 1, "password": "123456"
        }, headers=admin_headers)
        # 员工登录
        r = await ac.post("/api/portal/auth/login", json={
            "employee_no": "FLOW-TEST-001", "password": "123456"
        })
        emp_token = r.json()["access_token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}
        # 生成报销单
        r = await ac.post("/api/portal/reimbursements/generate", headers=emp_headers)
        reimb_id = r.json()["id"]
    yield admin_headers, emp_headers, reimb_id
    # 清理
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        try:
            await ac.delete(f"/api/reimbursements/{reimb_id}", headers=admin_headers)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_locked_then_unlock_flow(setup):
    admin_headers, emp_headers, reimb_id = setup

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
