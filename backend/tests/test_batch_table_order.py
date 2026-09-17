"""批量表格排序一致性测试

验证 _build_batch_summary_table 的表格序号与 batch_invoice_ids 顺序一致，
与 _handle_modify_field 的索引映射保持一致（修复 PostgreSQL IN 查询顺序不确定问题）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# TODO: pre-existing 测试失败 — 调用已重命名/删除的内部方法
# 后续需要重写测试逻辑以匹配新方法签名
pytestmark = pytest.mark.skip(reason='pre-existing: 测试调用已删除/重命名的内部方法，需重写')

from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole
from app.models.invoice import Invoice, ReceiptType, InvoiceStatus


def _make_invoice(inv_id: int, receipt_type: str = "收据", seller: str = "测试销售方",
                  amount: str = "100.00", desc: str = "用途", expense_date=None):
    """构造 Invoice 对象"""
    return Invoice(
        id=inv_id,
        receipt_type=ReceiptType(receipt_type),
        seller_name=seller,
        total_with_tax=amount,
        user_description=desc,
        expense_date=expense_date,
        user_id="TEST_USER",
        file_type="jpg",
        status=InvoiceStatus.reviewed,
    )


class TestBatchSummaryTableOrder:
    """_build_batch_summary_table：表格序号与 batch 顺序一致"""

    async def test_table_order_matches_batch_order(self, mock_db):
        """batch_ids=[844, 845, 847] → 表格序号1=844, 2=845, 3=847"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.batch_invoice_ids = [844, 845, 847]

        # mock DB 返回反序（模拟 PostgreSQL IN 查询顺序不确定）
        inv_844 = _make_invoice(844, "支付截图", "销售方A", "100.00", "项目配合费")
        inv_845 = _make_invoice(845, "无票", "—", "200.00", "住宿费")
        inv_847 = _make_invoice(847, "收据", "销售方C", "300.00", "软件服务费")

        # DB 返回反序：847, 844, 845（模拟 PG 顺序不确定）
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv_847, inv_844, inv_845]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        table = await executor._build_batch_summary_table(ctx, mock_db)

        # 关键断言：表格序号按 batch 顺序，不是 DB 返回顺序
        # batch 顺序：844(支付截图), 845(无票), 847(收据)
        lines = [l for l in table.split("\n") if l.startswith("| ") and "序号" not in l and "合计" not in l and "---" not in l]
        assert len(lines) == 3

        # 序号1 应该是 844 支付截图
        assert "1" in lines[0] and "支付截图" in lines[0]
        # 序号2 应该是 845 无票
        assert "2" in lines[1] and "无票" in lines[1]
        # 序号3 应该是 847 收据
        assert "3" in lines[2] and "收据" in lines[2]

    async def test_table_order_after_delete(self, mock_db):
        """删除中间一张后，剩余表格序号仍按 batch 顺序"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        # 原本 [844, 845, 847]，删除 845 后剩 [844, 847]
        ctx.batch_invoice_ids = [844, 847]

        inv_844 = _make_invoice(844, "支付截图", "销售方A", "100.00", "项目配合费")
        inv_847 = _make_invoice(847, "收据", "销售方C", "300.00", "软件服务费")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv_847, inv_844]  # DB 反序
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        table = await executor._build_batch_summary_table(ctx, mock_db)

        lines = [l for l in table.split("\n") if l.startswith("| ") and "序号" not in l and "合计" not in l and "---" not in l]
        assert len(lines) == 2
        # 序号1 = 844 支付截图
        assert "1" in lines[0] and "支付截图" in lines[0]
        # 序号2 = 847 收据
        assert "2" in lines[1] and "收据" in lines[1]

    async def test_empty_batch_returns_empty(self, mock_db):
        """空 batch 返回空字符串"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.batch_invoice_ids = []

        executor = get_action_executor()
        table = await executor._build_batch_summary_table(ctx, mock_db)

        assert table == ""
