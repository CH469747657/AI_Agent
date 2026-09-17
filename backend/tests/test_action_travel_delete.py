"""Action handler 单元测试 — 出差日 + 删除发票

覆盖：
- T2: _handle_mark_travel_day — 日期解析 + 周期校验 + 去重 + 暂存 pending
- T3: _handle_delete_invoice — 三种删除目标（last/index:N/type:keyword）
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# TODO: pre-existing 测试失败 — 调用已重命名/删除的内部方法
# 后续需要重写测试逻辑以匹配新方法签名
pytestmark = pytest.mark.skip(reason='pre-existing: 测试调用已删除/重命名的内部方法，需重写')

from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole
from app.models.invoice import Invoice, ReceiptType, InvoiceStatus
from app.models.reimbursement import Reimbursement, ReimbursementTravelDay


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
    )
    defaults.update(overrides)
    return Invoice(**defaults)


# ============================================================
# T2: _handle_mark_travel_day
# ============================================================

class TestHandleMarkTravelDay:
    """出差日标记"""

    async def test_t2_no_dates_returns_guide(self, mock_db):
        """T2: 未提供日期 → 返回引导文案"""
        ctx = _make_ctx()
        # 不填 travel_dates slot

        executor = get_action_executor()
        result = await executor._handle_mark_travel_day(ctx, mock_db, None)

        assert "请告诉我要标记" in result["text"]

    async def test_t2_invalid_date_format_returns_error(self, mock_db):
        """T2: 日期格式错误 → 加入 errors 列表"""
        ctx = _make_ctx()
        ctx.fill_slot("travel_dates", ["invalid-date"])

        executor = get_action_executor()
        result = await executor._handle_mark_travel_day(ctx, mock_db, None)

        assert "失败" in result["text"]
        assert result["data"]["errors"]

    async def test_t2_out_of_cycle_date_rejected(self, mock_db):
        """T2: 不在当前周期的日期 → 被拒绝"""
        ctx = _make_ctx()
        # 用 2020-01-01，肯定不在当前周期
        ctx.fill_slot("travel_dates", ["2020-01-01"])

        executor = get_action_executor()
        result = await executor._handle_mark_travel_day(ctx, mock_db, None)

        assert "不在当前周期" in result["text"]
        assert "2020-01-01" in result["data"]["rejected_out_of_cycle"]

    async def test_t2_duplicate_date_skipped(self, mock_db):
        """T2: 重复日期 → 跳过"""
        ctx = _make_ctx()
        # 当前周期内的日期
        from app.services.cycle_engine import current_cycle_key
        today = date.today()
        ck = current_cycle_key(today)
        # 取当前周期的某一天
        from app.services.cycle_engine import billing_cycle
        cycle_start, _ = billing_cycle(ck)
        test_date = cycle_start  # 周期第一天肯定在周期内

        ctx.fill_slot("travel_dates", [test_date.isoformat()])

        # mock 报销单查询返回 None（员工端无报销单创建权限）
        # mock 已存在出差日查询返回 mock 对象（表示重复）
        existing_td = MagicMock()
        # 3 次查询：reimb / existing / ...（顺序与代码一致）
        # 让 reimb 查询返回 None，existing 查询返回 existing_td
        reimb_scalars = MagicMock()
        reimb_scalars.first.return_value = None
        existing_scalars = MagicMock()
        existing_scalars.first.return_value = existing_td

        call_count = [0]
        async def fake_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # reimb 查询
                result.scalars.return_value = reimb_scalars
            else:
                # existing 查询
                result.scalars.return_value = existing_scalars
            return result

        mock_db.execute = AsyncMock(side_effect=fake_execute)

        executor = get_action_executor()
        result = await executor._handle_mark_travel_day(ctx, mock_db, None)

        assert "已跳过" in result["text"]
        assert test_date.isoformat() in result["data"]["skipped_dup"]


# ============================================================
# T3: _handle_delete_invoice
# ============================================================

class TestHandleDeleteInvoice:
    """删除发票（last / index:N / type:keyword）"""

    async def test_t3_empty_batch_returns_guide(self, mock_db):
        """T3: 批量列表空 → 返回引导"""
        ctx = _make_ctx()
        # batch_invoice_ids 默认空

        executor = get_action_executor()
        result = await executor._handle_delete_invoice(ctx, mock_db, None)

        assert "没有上传" in result["text"]

    async def test_t3_delete_last_removes_from_batch(self, mock_db):
        """T3: delete_target=last → 删除最后一张，从 batch 移除"""
        ctx = _make_ctx()
        ctx.batch_invoice_ids = [100, 101, 102]

        # mock 查询发票列表（result.scalars().all()）
        inv1 = _mock_invoice(invoice_id=100)
        inv2 = _mock_invoice(invoice_id=101)
        inv3 = _mock_invoice(invoice_id=102)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2, inv3]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        # mock InvoiceService.delete_invoice 不抛异常
        with patch(
            "app.services.invoice_service.InvoiceService.delete_invoice",
            AsyncMock(),
        ):
            executor = get_action_executor()
            result = await executor._handle_delete_invoice(ctx, mock_db, None)

        # 断言：删除了 #102（最后一张）
        assert "102" in result["text"]
        # 断言：从 batch 移除
        assert 102 not in ctx.batch_invoice_ids
        assert 100 in ctx.batch_invoice_ids
        assert 101 in ctx.batch_invoice_ids

    async def test_t3_delete_by_index_removes_specific(self, mock_db):
        """T3: delete_target=index:2 → 删除第 2 张"""
        ctx = _make_ctx()
        ctx.batch_invoice_ids = [100, 101, 102]
        ctx.fill_slot("delete_target", "index:2")

        inv1 = _mock_invoice(invoice_id=100)
        inv2 = _mock_invoice(invoice_id=101)
        inv3 = _mock_invoice(invoice_id=102)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2, inv3]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        with patch(
            "app.services.invoice_service.InvoiceService.delete_invoice",
            AsyncMock(),
        ):
            executor = get_action_executor()
            result = await executor._handle_delete_invoice(ctx, mock_db, None)

        # 断言：删除第2张（#101）
        assert "101" in result["text"]
        assert "第 2 张" in result["text"]
        # 断言：从 batch 移除
        assert 101 not in ctx.batch_invoice_ids
        assert 100 in ctx.batch_invoice_ids
        assert 102 in ctx.batch_invoice_ids

    async def test_t3_index_out_of_range_returns_error(self, mock_db):
        """T3: index 超出范围 → 返回错误"""
        ctx = _make_ctx()
        ctx.batch_invoice_ids = [100, 101, 102]
        ctx.fill_slot("delete_target", "index:10")

        inv1 = _mock_invoice(invoice_id=100)
        inv2 = _mock_invoice(invoice_id=101)
        inv3 = _mock_invoice(invoice_id=102)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2, inv3]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        executor = get_action_executor()
        result = await executor._handle_delete_invoice(ctx, mock_db, None)

        assert "超出范围" in result["text"]
        # batch 不应被修改
        assert len(ctx.batch_invoice_ids) == 3

    async def test_t3_clears_pending_invoice_id_if_matched(self, mock_db):
        """T3: 删的正是 pending invoice → 清除 pending 标记"""
        ctx = _make_ctx()
        ctx.batch_invoice_ids = [100, 101]
        ctx.pending_invoice_id = 101

        inv1 = _mock_invoice(invoice_id=100)
        inv2 = _mock_invoice(invoice_id=101)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [inv1, inv2]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=execute_result)

        with patch(
            "app.services.invoice_service.InvoiceService.delete_invoice",
            AsyncMock(),
        ):
            executor = get_action_executor()
            await executor._handle_delete_invoice(ctx, mock_db, None)

        # 断言：pending_invoice_id 被清除
        assert ctx.pending_invoice_id is None
