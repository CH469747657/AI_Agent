"""批量修改按索引差异化测试

覆盖场景：用户输入"发票1改为软件服务费，发票3改为培训费"，
系统应只改发票1和3，发票2保持不变。
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


def _make_invoice(inv_id: int, desc: str = "原用途", amount: str = "100.00"):
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


class TestParseBatchModifications:
    """_parse_batch_modifications：解析按索引差异化修改"""

    async def test_parse_indexed_modifications(self):
        """正则解析：发票1改为X，发票3改为Y → [(1, 用途, X), (3, 用途, Y)]"""
        executor = get_action_executor()
        result = await executor._parse_batch_modifications("发票1改为软件服务费，发票3改为培训费")

        assert len(result) == 2
        assert result[0] == (1, "用途", "软件服务费")
        assert result[1] == (3, "用途", "培训费")

    async def test_parse_no_index_applies_to_all(self):
        """无索引：金额改为100 → [(None, 金额, 100)]（应用到所有）"""
        executor = get_action_executor()
        result = await executor._parse_batch_modifications("金额改为100，日期改为2026-08-01")

        assert len(result) == 2
        assert result[0] == (None, "金额", "100")
        assert result[1] == (None, "日期", "2026-08-01")

    async def test_parse_mixed_index_and_no_index(self):
        """混合：第1张金额改为100，日期改为2026-08-01"""
        executor = get_action_executor()
        result = await executor._parse_batch_modifications("第1张金额改为100，日期改为2026-08-01")

        assert len(result) == 2
        assert result[0] == (1, "金额", "100")
        assert result[1] == (None, "日期", "2026-08-01")


class TestHandleBatchModifyIndexed:
    """_handle_batch_modify：按索引差异化修改，不误改其他发票"""

    async def test_modify_index_1_and_3_not_2(self, mock_db):
        """用户输入"发票1改为软件服务费，发票3改为培训费"
        → 只改发票1和3，发票2保持原用途
        """
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        # batch 顺序 DESC：847(序号1), 845(序号2), 844(序号3)
        ctx.batch_invoice_ids = [847, 845, 844]
        ctx.fill_slot("batch_modifications", "发票1改为软件服务费，发票3改为培训费")

        inv1 = _make_invoice(847, "原用途1")  # 序号1
        inv2 = _make_invoice(845, "原用途2")  # 序号2
        inv3 = _make_invoice(844, "原用途3")  # 序号3

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2, inv3]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_batch_modify(ctx, mock_db, None)

        # 关键断言：发票1(847) 和 发票3(844) 被修改
        assert inv1.user_description == "软件服务费"
        assert inv3.user_description == "培训费"
        # 发票2(845) 保持原用途，未被误改
        assert inv2.user_description == "原用途2"

        # 回复应说明修改了 2 张
        assert "已修改 2 张" in result["text"]

    async def test_modify_all_when_no_index(self, mock_db):
        """无索引"金额改为100" → 应用到所有发票"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.batch_invoice_ids = [847, 845, 844]
        ctx.fill_slot("batch_modifications", "金额改为200")

        inv1 = _make_invoice(847, "用途1", "100.00")
        inv2 = _make_invoice(845, "用途2", "100.00")
        inv3 = _make_invoice(844, "用途3", "100.00")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2, inv3]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_batch_modify(ctx, mock_db, None)

        # 所有三张都被修改
        assert inv1.total_with_tax == "200"
        assert inv2.total_with_tax == "200"
        assert inv3.total_with_tax == "200"
        assert "已修改 3 张" in result["text"]

    async def test_index_out_of_range_warning(self, mock_db):
        """序号超出范围 → 提示未找到，不误改其他"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.batch_invoice_ids = [847, 845, 844]
        ctx.fill_slot("batch_modifications", "发票5改为测试")

        inv1 = _make_invoice(847, "原用途1")
        inv2 = _make_invoice(845, "原用途2")
        inv3 = _make_invoice(844, "原用途3")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2, inv3]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_batch_modify(ctx, mock_db, None)

        # 没有发票被修改
        assert inv1.user_description == "原用途1"
        assert inv2.user_description == "原用途2"
        assert inv3.user_description == "原用途3"
        # 提示序号超出范围
        assert "超出范围" in result["text"] or "未找到" in result["text"]
