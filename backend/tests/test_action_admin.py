"""Action handler 单元测试 — 提交报销 (T14)

覆盖：
- T14: _handle_submit_reimbursement — 提交报销 + 空批量列表拦截

注：admin handler 相关用例（T10-T13）已拆到 test_action_admin_handlers.py。
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


# ============================================================
# T14: _handle_submit_reimbursement
# ============================================================

class TestHandleSubmitReimbursement:
    """提交报销单

    新实现（Task 11）：按角色分支
    - 员工：applicant_id = ctx.user_id
    - 管理员：从 ctx.slots['user_id'] 提取目标员工
    - 复用 cutoff_service + aggregation_service
    - 状态置 SUBMITTED
    """

    @pytest.fixture(autouse=True)
    def _reset_cutoff_cache(self):
        """清 cycle_end_service 进程级缓存，避免被其他用例的 MagicMock 污染"""
        from app.services.cycle_end_service import invalidate_cache
        invalidate_cache()
        yield
        invalidate_cache()

    async def test_t14_empty_batch_returns_guide(self, mock_db):
        """T14: 员工 + 批量列表空 → 返回引导"""
        ctx = _make_ctx(user_id="EMP001", role=UserRole.EMPLOYEE)
        # batch_invoice_ids 默认空

        executor = get_action_executor()
        result = await executor._handle_submit_reimbursement(ctx, mock_db, None)

        assert "没有上传任何发票" in result["text"]

    async def test_t14_admin_submit_with_user_id_slot(self, mock_db):
        """T14: 管理员提交 → 用 ctx.slots['user_id'] 指定目标员工 + 清空 batch"""
        ctx = _make_ctx(user_id="ADMIN", role=UserRole.ADMIN)
        ctx.batch_invoice_ids = [100]
        ctx.fill_slot("user_id", "EMP001")

        inv = _mock_invoice(invoice_id=100, status=InvoiceStatus.reviewed)
        # free_invoices 查询返回的 scalars() 迭代器
        scalars_iter = MagicMock()
        scalars_iter.__iter__ = MagicMock(return_value=iter([inv]))
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_iter
        mock_db.execute = AsyncMock(return_value=exec_result)

        fake_reimb = _mock_reimbursement(reimb_id=200, status=ReimbursementStatus.draft)

        with patch(
            "app.services.cycle_end_service.get_cycle_end_day",
            AsyncMock(return_value=21),
        ), patch(
            "app.services.cycle_engine.current_cycle_key",
            return_value="2026-09",
        ), patch(
            "app.services.aggregation_service.get_or_create_reimbursement",
            AsyncMock(return_value=fake_reimb),
        ), patch(
            "app.services.aggregation_service.attach_invoice_to_cycle",
            AsyncMock(return_value=fake_reimb),
        ):
            executor = get_action_executor()
            result = await executor._handle_submit_reimbursement(ctx, mock_db, None)

        # 状态被置 SUBMITTED
        assert fake_reimb.status == ReimbursementStatus.submitted
        # batch 清空
        assert ctx.batch_invoice_ids == []
        # 返回文本含周期
        assert "已提交报销单 #200" in result["text"]
        assert "2026-09" in result["text"]
        assert result["data"]["reimbursement_id"] == 200

    async def test_t14_employee_submit_uses_ctx_user_id(self, mock_db):
        """T14: 员工提交 → applicant_id = ctx.user_id（自己）"""
        ctx = _make_ctx(user_id="EMP001", role=UserRole.EMPLOYEE)
        ctx.batch_invoice_ids = [100]

        inv = _mock_invoice(invoice_id=100, status=InvoiceStatus.reviewed)
        scalars_iter = MagicMock()
        scalars_iter.__iter__ = MagicMock(return_value=iter([inv]))
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_iter
        mock_db.execute = AsyncMock(return_value=exec_result)

        fake_reimb = _mock_reimbursement(reimb_id=300, status=ReimbursementStatus.draft)

        captured = {}

        async def fake_get_or_create(db, applicant_id, cycle_key, auto_generated):
            captured["applicant_id"] = applicant_id
            captured["cycle_key"] = cycle_key
            captured["auto_generated"] = auto_generated
            return fake_reimb

        with patch(
            "app.services.cycle_end_service.get_cycle_end_day",
            AsyncMock(return_value=21),
        ), patch(
            "app.services.cycle_engine.current_cycle_key",
            return_value="2026-09",
        ), patch(
            "app.services.aggregation_service.get_or_create_reimbursement",
            side_effect=fake_get_or_create,
        ), patch(
            "app.services.aggregation_service.attach_invoice_to_cycle",
            AsyncMock(return_value=fake_reimb),
        ):
            executor = get_action_executor()
            result = await executor._handle_submit_reimbursement(ctx, mock_db, None)

        # 员工：target_user_id = ctx.user_id = EMP001
        assert captured["applicant_id"] == "EMP001"
        assert captured["auto_generated"] is False
        assert fake_reimb.status == ReimbursementStatus.submitted
        assert ctx.batch_invoice_ids == []
        assert "已提交报销单 #300" in result["text"]
