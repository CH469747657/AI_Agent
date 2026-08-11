"""费用发生日期判定引擎单元测试 — 三级优先

覆盖：
- Level 1: 备注时间解析（多种日期格式、多日期取最早、无日期降级）
- Level 2: 凭证识别日期（发票类 issue_date、非标交易日期）
- Level 3: 上传时间兜底
"""

import sys
import os
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.invoice import ReceiptType
from app.services.expense_date_engine import (
    determine_expense_date,
    parse_note_date,
    _collect_note_text,
    _parse_date_str,
    _parse_receipt_trade_date,
)


def _make_invoice(
    receipt_type=ReceiptType.vat_normal,
    issue_date=None,
    user_description="",
    created_at=None,
    receipt_detail=None,
):
    """创建模拟 Invoice 对象"""
    inv = MagicMock()
    inv.id = 1
    inv.receipt_type = receipt_type
    inv.issue_date = issue_date
    inv.user_description = user_description
    inv.created_at = created_at or datetime(2026, 7, 25, 3, 0, 0, tzinfo=timezone.utc)  # 7/25 11:00 UTC+8
    inv.receipt_detail = receipt_detail
    return inv


class TestParseNoteDate:
    def test_yyyy_mm_dd(self):
        assert parse_note_date("2026-06-18 出差打车", date(2026, 7, 25)) == date(2026, 6, 18)

    def test_slash_format(self):
        assert parse_note_date("2026/6/18的打车费", date(2026, 7, 25)) == date(2026, 6, 18)

    def test_chinese_format_month_day(self):
        assert parse_note_date("5月3日出差打车", date(2026, 7, 25)) == date(2026, 5, 3)

    def test_month_without_day_returns_none(self):
        """仅含月份无日期号 → 无法解析具体日期，返回 None"""
        assert parse_note_date("5月出差打车6月补录", date(2026, 7, 25)) is None

    def test_md_with_day(self):
        assert parse_note_date("6月18日高铁", date(2026, 7, 25)) == date(2026, 6, 18)

    def test_multiple_dates_take_earliest(self):
        """多个日期取最早"""
        result = parse_note_date("6月15日吃饭，6月18日高铁", date(2026, 7, 25))
        assert result == date(2026, 6, 15)

    def test_no_date_returns_none(self):
        assert parse_note_date("高铁费", date(2026, 7, 25)) is None

    def test_empty_text(self):
        assert parse_note_date("", date(2026, 7, 25)) is None
        assert parse_note_date(None, date(2026, 7, 25)) is None


class TestDetermineExpenseDateLevel1:
    """Level 1: 备注时间"""

    def test_note_with_explicit_date(self):
        """备注含明确日期 → note"""
        inv = _make_invoice(
            issue_date="2026-07-10",
            user_description="2026-06-18 出差打车",
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "note"
        assert d == date(2026, 6, 18)

    def test_note_overrides_issue_date(self):
        """备注日期优先于发票票面日期"""
        inv = _make_invoice(
            issue_date="2026-07-10",
            user_description="2026-06-18吃饭",
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "note"
        assert d == date(2026, 6, 18)

    def test_receipt_detail_remark(self):
        """非标票据 receipt_detail.remark 中的日期"""
        inv = _make_invoice(
            receipt_type=ReceiptType.payment_screenshot,
            receipt_detail={"remark": "2026-07-05的打车"},
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "note"
        assert d == date(2026, 7, 5)


class TestDetermineExpenseDateLevel2:
    """Level 2: 凭证识别日期"""

    def test_invoice_typed_uses_issue_date(self):
        """发票类用票面日期"""
        inv = _make_invoice(
            receipt_type=ReceiptType.vat_normal,
            issue_date="2026-07-10",
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "issue_date"
        assert d == date(2026, 7, 10)

    def test_train_ticket_uses_issue_date(self):
        """火车票用票面日期"""
        inv = _make_invoice(
            receipt_type=ReceiptType.train_ticket,
            issue_date="2026-07-15",
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "issue_date"
        assert d == date(2026, 7, 15)

    def test_nonstandard_receipt_uses_trade_date(self):
        """非标凭证用交易日期"""
        inv = _make_invoice(
            receipt_type=ReceiptType.bank_statement,
            receipt_detail={"transaction_time": "2026-07-03"},
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "receipt_date"
        assert d == date(2026, 7, 3)

    def test_invoice_missing_issue_date_falls_back_to_upload(self):
        """发票类无票面日期 → 降级到上传时间"""
        inv = _make_invoice(
            receipt_type=ReceiptType.vat_normal,
            issue_date=None,
            created_at=datetime(2026, 7, 25, 3, 0, 0, tzinfo=timezone.utc),
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "upload_time"
        assert d == date(2026, 7, 25)


class TestDetermineExpenseDateLevel3:
    """Level 3: 上传时间兜底"""

    def test_no_receipt_uses_upload_time(self):
        """无票报销用上传时间"""
        inv = _make_invoice(
            receipt_type=ReceiptType.no_receipt,
            user_description="打车费",
        )
        d, src = determine_expense_date(inv, date(2026, 7, 25))
        assert src == "upload_time"
        assert d == date(2026, 7, 25)  # 7/25 03:00 UTC = 7/25 11:00 UTC+8

    def test_upload_time_timezone_conversion(self):
        """上传时间 UTC→UTC+8 转换"""
        # 7月25日 16:00 UTC → 7月26日 00:00 UTC+8
        inv = _make_invoice(
            receipt_type=ReceiptType.no_receipt,
            created_at=datetime(2026, 7, 25, 16, 0, 0, tzinfo=timezone.utc),
        )
        d, src = determine_expense_date(inv, date(2026, 7, 26))
        assert src == "upload_time"
        assert d == date(2026, 7, 26)
