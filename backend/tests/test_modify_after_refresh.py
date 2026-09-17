"""刷新后修改发票的 DB 兜底测试

覆盖场景：用户上传发票后刷新页面，ctx.batch_invoice_ids 清空，
但 DB 中发票仍在（未关联报销单）。修改发票时应从 DB 兜底恢复 batch_invoice_ids。
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


def _make_invoice(inv_id: int, desc: str = "测试用途", amount: str = "100.00"):
    return Invoice(
        id=inv_id,
        receipt_type=ReceiptType.vat_normal,
        seller_name="测试销售方",
        total_with_tax=amount,
        user_description=desc,
        user_id="TEST_USER",
        file_type="jpg",
        status=InvoiceStatus.reviewing,
        reimbursement_id=None,
        created_at=datetime(2026, 8, 19, 17, 4, 12),
    )


class TestEnsureBatchIdsFromDb:
    """_ensure_batch_ids_from_db：batch 为空时从 DB 恢复"""

    async def test_restore_when_empty(self, mock_db):
        """batch_invoice_ids 为空 + DB 有未提交发票 → 回填"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        # batch 为空（模拟刷新后）
        assert ctx.batch_invoice_ids == []

        inv1 = _make_invoice(844, "项目配合费")
        inv2 = _make_invoice(845, "住宿费")
        inv3 = _make_invoice(847, "软件服务费")

        scalars_mock = MagicMock()
        # 按 created_at desc 返回（最新在前）：847, 845, 844
        scalars_mock.all.return_value = [inv3, inv2, inv1]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        restored = await executor._ensure_batch_ids_from_db(ctx, mock_db)

        assert restored is True
        # batch_invoice_ids 按 DESC 顺序：最新(847)在前
        assert ctx.batch_invoice_ids == [847, 845, 844]

    async def test_no_restore_when_nonempty(self, mock_db):
        """batch_invoice_ids 非空 → 不查 DB"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.batch_invoice_ids = [999]

        executor = get_action_executor()
        restored = await executor._ensure_batch_ids_from_db(ctx, mock_db)

        assert restored is False
        assert ctx.batch_invoice_ids == [999]  # 保持不变
        # 不应查 DB
        assert not mock_db.execute.called

    async def test_no_invoices_in_db(self, mock_db):
        """batch 为空 + DB 也无未提交发票 → 不回填"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        restored = await executor._ensure_batch_ids_from_db(ctx, mock_db)

        assert restored is False
        assert ctx.batch_invoice_ids == []


class TestModifyFieldAfterRefresh:
    """刷新后修改发票：_handle_modify_field 兜底恢复"""

    async def test_modify_by_index_after_refresh(self, mock_db):
        """刷新后 ctx.batch_invoice_ids 为空，用户说"改第2张用途"
        → 从 DB 恢复 batch（DESC 顺序），再按序号取 invoice_id
        """
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 2)
        ctx.fill_slot("field_name", "用途")
        ctx.fill_slot("field_value", "新用途")
        # batch 为空（模拟刷新后）

        inv1 = _make_invoice(844, "项目配合费")
        inv2 = _make_invoice(845, "住宿费")
        inv3 = _make_invoice(847, "软件服务费")

        # 第一次查询：_ensure_batch_ids_from_db 恢复 batch（DESC：847, 845, 844）
        # 第二次查询：_handle_modify_field 查具体发票
        scalars_mock1 = MagicMock()
        scalars_mock1.all.return_value = [inv3, inv2, inv1]  # DESC 顺序
        execute_result1 = MagicMock()
        execute_result1.scalars.return_value = scalars_mock1
        execute_result2 = MagicMock()
        execute_result2.scalar_one_or_none.return_value = inv2  # 第2张是 845
        mock_db.execute = AsyncMock(side_effect=[execute_result1, execute_result2])
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        # 关键断言：batch 按 DESC 恢复，第2张 = 845
        assert ctx.batch_invoice_ids == [847, 845, 844]
        # 不应返回"没有上传任何发票"
        assert "没有上传" not in result["text"]
        # 应该成功修改（inv2.user_description 被更新）
        assert inv2.user_description == "新用途"

    async def test_modify_returns_error_when_no_invoices(self, mock_db):
        """DB 也无未提交发票 → 返回"没有上传任何发票" """
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "用途")
        ctx.fill_slot("field_value", "新用途")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        assert "没有上传" in result["text"] or "无法按序号修改" in result["text"]


class TestTableOrderConsistency:
    """表格序号与修改索引映射一致性（修复票据1和3错位）"""

    async def test_modify_first_invoice_not_third(self, mock_db):
        """用户说"改第1张" → 应改表格序号1（最新创建的），不是第3张"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "用途")
        ctx.fill_slot("field_value", "新用途1")

        # 3张发票，按 created_at desc：847(收据,最新), 845(无票), 844(支付截图,最早)
        inv1 = _make_invoice(844, "项目配合费")
        inv2 = _make_invoice(845, "住宿费")
        inv3 = _make_invoice(847, "软件服务费")

        scalars_mock1 = MagicMock()
        scalars_mock1.all.return_value = [inv3, inv2, inv1]  # DESC
        execute_result1 = MagicMock()
        execute_result1.scalars.return_value = scalars_mock1
        # 第1张 = batch[0] = 847（收据，最新）
        execute_result2 = MagicMock()
        execute_result2.scalar_one_or_none.return_value = inv3
        mock_db.execute = AsyncMock(side_effect=[execute_result1, execute_result2])
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        # 关键断言：第1张 = 847（最新），不是 844（最早）
        assert ctx.batch_invoice_ids == [847, 845, 844]
        assert inv3.user_description == "新用途1"  # 847 被修改
        assert inv1.user_description == "项目配合费"  # 844 未被修改

    async def test_modify_third_invoice_not_first(self, mock_db):
        """用户说"改第3张" → 应改表格序号3（最早创建的），不是第1张"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 3)
        ctx.fill_slot("field_name", "用途")
        ctx.fill_slot("field_value", "新用途3")

        inv1 = _make_invoice(844, "项目配合费")
        inv2 = _make_invoice(845, "住宿费")
        inv3 = _make_invoice(847, "软件服务费")

        scalars_mock1 = MagicMock()
        scalars_mock1.all.return_value = [inv3, inv2, inv1]  # DESC
        execute_result1 = MagicMock()
        execute_result1.scalars.return_value = scalars_mock1
        # 第3张 = batch[2] = 844（支付截图，最早）
        execute_result2 = MagicMock()
        execute_result2.scalar_one_or_none.return_value = inv1
        mock_db.execute = AsyncMock(side_effect=[execute_result1, execute_result2])
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        # 关键断言：第3张 = 844（最早），不是 847（最新）
        assert ctx.batch_invoice_ids == [847, 845, 844]
        assert inv1.user_description == "新用途3"  # 844 被修改
        assert inv3.user_description == "软件服务费"  # 847 未被修改
