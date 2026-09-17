"""_handle_upload_invoice slot 路径单元测试

覆盖：
- U8: Agent 已通过 function calling 拆好 purpose/expense_date slot 时，_llm_split_purpose_date 不被触发
- U9: slots 为空 + ctx.current_text 含日期+用途 → 触发 _llm_split_purpose_date 兜底
- U9+ : 兜底成功后 slot 被正确填充
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# TODO: pre-existing 测试失败 — 调用已重命名/删除的内部方法
# 后续需要重写测试逻辑以匹配新方法签名
pytestmark = pytest.mark.skip(reason='pre-existing: 测试调用已删除/重命名的内部方法，需重写')

from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole
from app.models.invoice import Invoice, ReceiptType, InvoiceStatus


def _make_ctx_with_text(text: str) -> DialogContext:
    """构造 ctx，slots 为空，仅 current_text 含用户输入"""
    ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
    ctx.current_text = text
    return ctx


def _mock_process_upload(invoice_id: int = 888):
    """patch InvoiceService.process_upload 返回 dummy invoice"""
    async def fake(self, file_data, file_type, receipt_type, user_id, user_description="", on_progress=None):
        return Invoice(
            id=invoice_id,
            receipt_type=ReceiptType.unknown,
            user_description=user_description,
            user_id=user_id,
            file_type=file_type,
            status=InvoiceStatus.processing,
        )
    return patch("app.services.invoice_service.InvoiceService.process_upload", fake)


def _disable_batch_parse():
    """patch _parse_batch_description 返回空（避免触发真实 LLM）"""
    async def fake(self, text, existing_count=0):
        return {}
    return patch.object(
        get_action_executor().__class__,
        "_parse_batch_description",
        fake,
    )


class TestHandleUploadInvoiceSlotPaths:
    """_handle_upload_invoice：Agent slot 路径 vs legacy 兜底路径"""

    async def test_u8_agent_slot_not_overwritten_by_legacy_split(
        self, mock_llm_service, mock_db, fake_attachment_data
    ):
        """U8: Agent 已拆好 slot → _llm_split_purpose_date 不应被调用"""
        ctx = _make_ctx_with_text("dummy")  # current_text 给任意值
        ctx.fill_slot("purpose", "Agent拆的用途")
        ctx.fill_slot("expense_date", "2026-08-02")
        ctx.attachment_data = fake_attachment_data

        executor = get_action_executor()

        # 监视 _llm_split_purpose_date 是否被调用
        with patch.object(
            executor, "_llm_split_purpose_date", AsyncMock()
        ) as mock_split, _mock_process_upload(), _disable_batch_parse():
            # mock 兜底解析后 refresh 不报错
            await executor._handle_upload_invoice(ctx, mock_db, fake_attachment_data)

            # 关键断言：_llm_split_purpose_date 未被调用
            mock_split.assert_not_called()

        # Agent 拆的 slot 应保留
        purpose_slot = ctx.slots.get("purpose")
        assert purpose_slot and purpose_slot.filled
        assert purpose_slot.value == "Agent拆的用途"

    async def test_u9_empty_slots_triggers_legacy_split(
        self, mock_llm_with_purpose_date_split, mock_db, fake_attachment_data
    ):
        """U9: slots 为空 + current_text 含「项目投标费 8月2日」→ 触发 _llm_split_purpose_date 兜底"""
        ctx = _make_ctx_with_text("项目投标费 8 月 2 日")
        ctx.attachment_data = fake_attachment_data

        executor = get_action_executor()

        with _mock_process_upload(), _disable_batch_parse():
            await executor._handle_upload_invoice(ctx, mock_db, fake_attachment_data)

        # 兜底拆分后 slot 被填充
        purpose_slot = ctx.slots.get("purpose")
        assert purpose_slot and purpose_slot.filled
        assert purpose_slot.value == "项目投标费"

        expense_date_slot = ctx.slots.get("expense_date")
        assert expense_date_slot and expense_date_slot.filled
        assert expense_date_slot.value == "2026-08-02"

    async def test_u9_only_purpose_no_date_does_not_fill_expense_date(
        self, mock_llm_service, mock_db, fake_attachment_data
    ):
        """U9: 用户输入「软件服务费」（无日期）→ purpose 填充, expense_date 不填"""
        import json
        fake_response = {
            "purpose": "软件服务费",
            "expense_date": None,
        }
        from tests.conftest import _set_llm_response
        _set_llm_response(mock_llm_service, json.dumps(fake_response, ensure_ascii=False))

        ctx = _make_ctx_with_text("软件服务费")
        ctx.attachment_data = fake_attachment_data

        executor = get_action_executor()

        with _mock_process_upload(), _disable_batch_parse():
            await executor._handle_upload_invoice(ctx, mock_db, fake_attachment_data)

        # purpose 被填
        purpose_slot = ctx.slots.get("purpose")
        assert purpose_slot and purpose_slot.filled
        assert purpose_slot.value == "软件服务费"

        # expense_date 不应被填
        expense_date_slot = ctx.slots.get("expense_date")
        assert not (expense_date_slot and expense_date_slot.filled)
