"""Action handler 单元测试 — 管理员审批 + 提交报销

覆盖：
- T10: _handle_admin_approve — 审批通过 + 状态变更
- T11: _handle_admin_reject — 审批驳回
- T12: _handle_admin_pending — 待审列表
- T13: _handle_admin_detail — 报销单详情
- T14: _handle_submit_reimbursement — 提交报销 + 空批量列表拦截
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
        """清 cutoff_service 进程级缓存，避免被其他用例的 MagicMock 污染"""
        from app.services.cutoff_service import invalidate_cache
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
            "app.services.cutoff_service.get_cutoff_day",
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
            "app.services.cutoff_service.get_cutoff_day",
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
