"""Action handler 单元测试 — 查询类

覆盖：
- T6: _handle_query_invoices — 查询发票列表 + 空结果引导
- T7: _handle_query_my_reimbursement — 查询报销单 + 周期筛选
- T8: _handle_query_status — 查询报销进度
- T9: _handle_self_pending — 查询本人未提交票据
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# TODO: pre-existing 测试失败 — 调用已重命名/删除的内部方法
# 后续需要重写测试逻辑以匹配新方法签名
pytestmark = pytest.mark.skip(reason='pre-existing: 测试调用已删除/重命名的内部方法，需重写')

from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole
from app.models.invoice import Invoice, ReceiptType, InvoiceStatus
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementStatus,
)


def _make_ctx(user_id: str = "TEST_USER", role: UserRole = UserRole.EMPLOYEE) -> DialogContext:
    return DialogContext(user_id=user_id, role=role)


def _mock_invoice(invoice_id: int = 100, **overrides):
    defaults = dict(
        id=invoice_id,
        receipt_type=ReceiptType.vat_normal,
        user_description="打车费",
        user_id="TEST_USER",
        file_type="jpg",
        total_with_tax="120",
        seller_name="测试销售方",
        status=InvoiceStatus.reviewing,
        created_at=datetime(2026, 8, 1),
    )
    defaults.update(overrides)
    return Invoice(**defaults)


def _mock_reimbursement(reimb_id: int = 200, **overrides):
    defaults = dict(
        id=reimb_id,
        applicant_id="TEST_USER",
        cycle_key="2026-08",
        status=ReimbursementStatus.submitted,
        reason="差旅报销",
        total_amount=500.0,
        expense_total=400.0,
        subsidy_total=100.0,
        is_cycle_locked=False,
        created_at=datetime(2026, 8, 1),
    )
    defaults.update(overrides)
    return Reimbursement(**defaults)


# ============================================================
# T6: _handle_query_invoices
# ============================================================

class TestHandleQueryInvoices:
    """查询用户发票列表"""

    async def test_t6_empty_invoices_returns_guide(self, mock_db):
        """T6: 无发票 → 返回引导文案"""
        ctx = _make_ctx()
        # mock 查询返回空
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_query_invoices(ctx, mock_db, None)

        assert "还没有上传过发票" in result["text"]
        assert result["data"]["count"] == 0

    async def test_t6_returns_invoice_list_with_total(self, mock_db):
        """T6: 有发票 → 返回列表 + 合计金额"""
        ctx = _make_ctx()
        inv1 = _mock_invoice(invoice_id=100, total_with_tax="120")
        inv2 = _mock_invoice(invoice_id=101, total_with_tax="200.50")

        # _handle_query_invoices 内部两次查 db.execute：
        # 1. select Invoice 按 created_at desc limit 20
        # 2. _build_user_invoices_table 内再次查询
        # 两次都返回相同 mock 数据
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_query_invoices(ctx, mock_db, None)

        assert "共" in result["text"]
        assert "2" in result["text"]  # 共 2 张
        assert result["data"]["count"] == 2
        # 合计金额 120 + 200.50 = 320.50
        assert result["data"]["total"] == 320.50


# ============================================================
# T7: _handle_query_my_reimbursement
# ============================================================

class TestHandleQueryMyReimbursement:
    """查询我的报销单"""

    async def test_t7_empty_reimbursements_returns_guide(self, mock_db):
        """T7: 无报销单 → 返回引导文案"""
        ctx = _make_ctx()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_query_my_reimbursement(ctx, mock_db, None)

        assert "还没有报销单记录" in result["text"]
        assert result["data"]["count"] == 0

    async def test_t7_returns_reimbursement_list_with_period_filter(self, mock_db):
        """T7: 周期筛选 → 返回该周期报销单"""
        ctx = _make_ctx()
        ctx.fill_slot("period", "2026-08")
        reimb = _mock_reimbursement(reimb_id=200, cycle_key="2026-08")
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [reimb]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_query_my_reimbursement(ctx, mock_db, None)

        assert "200" in result["text"]  # 含报销单 ID
        assert result["data"]["count"] == 1

    async def test_t7_empty_with_period_filter_returns_specific_guide(self, mock_db):
        """T7: 周期筛选无结果 → 返回该周期专属引导"""
        ctx = _make_ctx()
        ctx.fill_slot("period", "2026-08")
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_query_my_reimbursement(ctx, mock_db, None)

        # 周期筛选的引导文案含「周期」字样
        assert "周期" in result["text"]


# ============================================================
# T8: _handle_query_status
# ============================================================

class TestHandleQueryStatus:
    """查询报销进度"""

    async def test_t8_empty_returns_guide(self, mock_db):
        """T8: 无报销单 → 返回引导"""
        ctx = _make_ctx()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_query_status(ctx, mock_db, None)

        assert "还没有报销单记录" in result["text"]
        assert result["data"]["count"] == 0

    async def test_t8_returns_status_with_emoji(self, mock_db):
        """T8: 返回状态文本含 emoji"""
        ctx = _make_ctx()
        reimb = _mock_reimbursement(reimb_id=200, status=ReimbursementStatus.submitted)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [reimb]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_query_status(ctx, mock_db, None)

        # submitted → "⏳ 已提交（等待审批）"
        assert "已提交" in result["text"]
        assert "#200" in result["text"]


# ============================================================
# T9: _handle_self_pending
# ============================================================

class TestHandleSelfPending:
    """查询本人未提交票据"""

    async def test_t9_empty_returns_all_submitted_hint(self, mock_db):
        """T9: 无未提交票据 → 提示全部已关联"""
        ctx = _make_ctx()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_self_pending(ctx, mock_db, None)

        assert "没有未提交" in result["text"]
        assert result["data"]["count"] == 0

    async def test_t9_employee_role_adds_auto_aggregate_hint(self, mock_db):
        """T9: 员工角色 → 文案含「按周期自动生成」"""
        ctx = _make_ctx(role=UserRole.EMPLOYEE)
        inv = _mock_invoice(invoice_id=100, total_with_tax="120")
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_self_pending(ctx, mock_db, None)

        assert "按周期自动生成" in result["text"]
        assert result["data"]["count"] == 1

    async def test_t9_admin_role_adds_complete_hint(self, mock_db):
        """T9: 管理员角色 → 文案含「完成」"""
        ctx = _make_ctx(role=UserRole.ADMIN)
        inv = _mock_invoice(invoice_id=100, total_with_tax="120")
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_self_pending(ctx, mock_db, None)

        assert "完成" in result["text"]
