"""修改发票日期字段映射测试

验证 _handle_modify_field 把"日期"写进 expense_date（费用发生日期）
而非 issue_date（开票日期），并同步设 expense_date_source="note"。
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

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


class TestModifyFieldDateMapping:
    """修改日期字段：应写 expense_date + source=note，不写 issue_date"""

    async def test_modify_date_writes_expense_date(self, mock_db):
        """用户说"日期改为2026-08-10" → expense_date=2026-08-10, source=note"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "日期")
        ctx.fill_slot("field_value", "2026-08-10")
        ctx.batch_invoice_ids = [849]

        inv = _make_invoice(849, "住宿费", "1500")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        # 关键断言：expense_date 被写，issue_date 不被写
        assert inv.expense_date == date(2026, 8, 10)
        assert inv.expense_date_source == "note"
        assert inv.issue_date is None or inv.issue_date == ""
        assert "2026-08-10" in result["text"]

    async def test_modify_date_chinese_format(self, mock_db):
        """用户说"8月14日" → 补当前年份，expense_date=2026-08-14"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "日期")
        ctx.fill_slot("field_value", "8月14日")
        ctx.batch_invoice_ids = [850]

        inv = _make_invoice(850, "餐饮费", "540")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        assert inv.expense_date == date(2026, 8, 14)
        assert inv.expense_date_source == "note"
        assert "不支持" not in result["text"]

    async def test_modify_date_invalid_format_returns_error(self, mock_db):
        """日期格式无法解析 → 返回错误提示，不写 expense_date"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "日期")
        ctx.fill_slot("field_value", "不是日期")
        ctx.batch_invoice_ids = [849]

        inv = _make_invoice(849, "住宿费", "1500")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        # 关键断言：不写 expense_date，返回格式错误提示
        assert inv.expense_date is None
        assert "日期格式无法解析" in result["text"]
        # 不应 commit
        mock_db.commit.assert_not_called()

    async def test_modify_other_field_uses_setattr(self, mock_db):
        """改"用途"仍走 setattr 通用路径，不受日期分支影响"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "用途")
        ctx.fill_slot("field_value", "打车费")
        ctx.batch_invoice_ids = [849]

        inv = _make_invoice(849, "住宿费", "1500")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        assert inv.user_description == "打车费"
        assert "已将发票" in result["text"]
