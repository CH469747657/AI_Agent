"""Action handler 单元测试 — 管理员审批/驳回/待审/详情

覆盖：
- T10: _handle_admin_approve — 审批通过 + 状态变更
- T11: _handle_admin_reject — 审批驳回
- T12: _handle_admin_pending — 待审列表
- T13: _handle_admin_detail — 报销单详情

注：此文件从 test_action_admin.py 拆出，仅含 admin handler 相关用例。
T14 _handle_submit_reimbursement 用例仍在 test_action_admin.py。
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole
from app.models.invoice import Invoice, ReceiptType, InvoiceStatus
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementStatus,
)


def _make_ctx(user_id: str = "ADMIN", role: UserRole = UserRole.ADMIN) -> DialogContext:
    return DialogContext(user_id=user_id, role=role)


def _mock_invoice(invoice_id: int = 100, **overrides):
    defaults = dict(
        id=invoice_id,
        receipt_type=ReceiptType.vat_normal,
        user_description="打车费",
        user_id="EMP001",
        file_type="jpg",
        total_with_tax="120",
        seller_name="测试销售方",
        status=InvoiceStatus.reviewing,
        reimbursement_id=200,
    )
    defaults.update(overrides)
    return Invoice(**defaults)


def _mock_reimbursement(reimb_id: int = 200, **overrides):
    defaults = dict(
        id=reimb_id,
        applicant_id="EMP001",
        applicant_name="陈辉",
        cycle_key="2026-08",
        status=ReimbursementStatus.submitted,
        reason="差旅报销",
        total_amount=500.0,
        is_cycle_locked=False,
        created_at=datetime(2026, 8, 1),
    )
    defaults.update(overrides)
    return Reimbursement(**defaults)


def _setup_db_execute_seq(mock_db, exec_results):
    """让 mock_db.execute 按调用顺序返回不同结果（每次调用返回列表下一个）"""
    call_count = [0]
    async def fake_execute(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        return exec_results[idx] if idx < len(exec_results) else exec_results[-1]
    mock_db.execute = AsyncMock(side_effect=fake_execute)


# ============================================================
# T10: _handle_admin_approve
# ============================================================

class TestHandleAdminApprove:
    """管理员审批通过"""

    async def test_t10_no_id_returns_guide(self, mock_db):
        """T10: 未提供报销单 ID → 返回引导"""
        ctx = _make_ctx()
        # 不填 reimbursement_id / person

        executor = get_action_executor()
        result = await executor._handle_admin_approve(ctx, mock_db, None)

        assert "请指定" in result["text"]

    async def test_t10_approve_updates_invoice_and_reimb_status(self, mock_db):
        """T10: 审批通过 → 发票 confirmed + 报销单 reviewed"""
        ctx = _make_ctx()
        ctx.fill_slot("reimbursement_id", "200")

        inv = _mock_invoice(invoice_id=100, status=InvoiceStatus.reviewing)
        reimb = _mock_reimbursement(reimb_id=200, status=ReimbursementStatus.submitted)

        # 第一次 db.execute：查发票列表
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv]
        exec_result_1 = MagicMock()
        exec_result_1.scalars.return_value = scalars_mock

        with patch(
            "app.dialog.action_executor.get_reimbursement_or_404",
            AsyncMock(return_value=reimb),
        ):
            mock_db.execute = AsyncMock(return_value=exec_result_1)

            executor = get_action_executor()
            result = await executor._handle_admin_approve(ctx, mock_db, None)

        # 断言：发票状态 reviewed
        assert inv.status == InvoiceStatus.reviewed
        # 断言：报销单状态 reviewed
        assert reimb.status == ReimbursementStatus.reviewed
        assert mock_db.commit.called
        assert result["data"]["approved_count"] == 1

    async def test_t10_invalid_reimb_id_format_returns_guide(self, mock_db):
        """T10: reimbursement_id 不是数字 → 走姓名消歧"""
        ctx = _make_ctx()
        ctx.fill_slot("reimbursement_id", "陈辉")  # 非数字

        # mock _resolve_reimbursement_by_person 返回 None
        with patch.object(
            get_action_executor(),
            "_resolve_reimbursement_by_person",
            AsyncMock(return_value=(None, "")),
        ):
            executor = get_action_executor()
            result = await executor._handle_admin_approve(ctx, mock_db, None)

        assert "未找到" in result["text"]
        assert "陈辉" in result["text"]


# ============================================================
# T11: _handle_admin_reject
# ============================================================

class TestHandleAdminReject:
    """管理员驳回"""

    async def test_t11_no_id_returns_guide(self, mock_db):
        """T11: 未提供 ID → 返回引导"""
        ctx = _make_ctx()

        executor = get_action_executor()
        result = await executor._handle_admin_reject(ctx, mock_db, None)

        assert "请指定" in result["text"]

    async def test_t11_reject_updates_invoice_and_reimb_status(self, mock_db):
        """T11: 驳回 → 发票 rejected + 报销单 draft"""
        ctx = _make_ctx()
        ctx.fill_slot("reimbursement_id", "200")
        ctx.fill_slot("reason", "金额不合理")

        inv = _mock_invoice(invoice_id=100, status=InvoiceStatus.reviewing)
        reimb = _mock_reimbursement(reimb_id=200, status=ReimbursementStatus.submitted)

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=exec_result)

        with patch(
            "app.dialog.action_executor.get_reimbursement_or_404",
            AsyncMock(return_value=reimb),
        ):
            executor = get_action_executor()
            result = await executor._handle_admin_reject(ctx, mock_db, None)

        # 断言：发票状态 rejected
        assert inv.status == InvoiceStatus.rejected
        # 断言：报销单状态 draft
        assert reimb.status == ReimbursementStatus.draft
        assert mock_db.commit.called
        assert "已驳回" in result["text"]

    async def test_t11_non_numeric_id_returns_guide(self, mock_db):
        """T11: 非数字 ID → 返回引导"""
        ctx = _make_ctx()
        ctx.fill_slot("reimbursement_id", "abc")

        executor = get_action_executor()
        result = await executor._handle_admin_reject(ctx, mock_db, None)

        assert "数字" in result["text"]


# ============================================================
# T12: _handle_admin_pending
# ============================================================

class TestHandleAdminPending:
    """待审列表"""

    async def test_t12_empty_returns_guide(self, mock_db):
        """T12: 无待审 → 返回无待审"""
        ctx = _make_ctx()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=exec_result)

        executor = get_action_executor()
        result = await executor._handle_admin_pending(ctx, mock_db, None)

        assert "没有待审批" in result["text"]
        assert result["data"]["count"] == 0

    async def test_t12_returns_list_with_applicant_info(self, mock_db):
        """T12: 有待审 → 返回列表含申请人"""
        ctx = _make_ctx()
        reimb = _mock_reimbursement(reimb_id=200, applicant_name="陈辉")
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [reimb]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=exec_result)

        executor = get_action_executor()
        result = await executor._handle_admin_pending(ctx, mock_db, None)

        assert "陈辉" in result["text"]
        assert "200" in result["text"]
        assert result["data"]["count"] == 1


# ============================================================
# T13: _handle_admin_detail
# ============================================================

class TestHandleAdminDetail:
    """报销单详情"""

    async def test_t13_no_id_returns_guide(self, mock_db):
        """T13: 未提供 ID → 返回引导"""
        ctx = _make_ctx()

        executor = get_action_executor()
        result = await executor._handle_admin_detail(ctx, mock_db, None)

        assert "请指定" in result["text"]

    async def test_t13_non_numeric_returns_guide(self, mock_db):
        """T13: 非数字 ID → 返回引导"""
        ctx = _make_ctx()
        ctx.fill_slot("reimbursement_id", "abc")

        executor = get_action_executor()
        result = await executor._handle_admin_detail(ctx, mock_db, None)

        assert "数字" in result["text"]

    async def test_t13_returns_detail_with_invoices(self, mock_db):
        """T13: 返回详情含关联发票"""
        ctx = _make_ctx()
        ctx.fill_slot("reimbursement_id", "200")

        reimb = _mock_reimbursement(reimb_id=200, applicant_name="陈辉")
        inv = _mock_invoice(invoice_id=100, seller_name="测试销售方", total_with_tax="120")

        # 两次 db.execute：第1次 get_reimbursement_or_404（实际是 patched），第2次查发票
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=exec_result)

        with patch(
            "app.dialog.action_executor.get_reimbursement_or_404",
            AsyncMock(return_value=reimb),
        ):
            executor = get_action_executor()
            result = await executor._handle_admin_detail(ctx, mock_db, None)

        assert "陈辉" in result["text"]
        assert "测试销售方" in result["text"]
        assert "¥120" in result["text"]
        assert result["data"]["reimbursement_id"] == 200
