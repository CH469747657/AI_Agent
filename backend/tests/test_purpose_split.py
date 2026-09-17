"""purpose 二次校验拆分测试

覆盖 Agent 路径下 LLM 违反规则 9、把"8月3日 项目投标费"整段塞进 purpose 的场景：
- U19: extract_date_and_purpose 各种日期格式
- U16/U17: _handle_upload_invoice purpose 含日期时二次校验拆分
"""

from datetime import date

import pytest

from app.services.expense_date_engine import extract_date_and_purpose


class TestExtractDateFromText:
    """extract_date_and_purpose：从混合文本提取日期 + 剩余纯用途"""

    def test_u19_m月d日格式(self):
        d, remaining = extract_date_and_purpose("8月3日 项目投标费")
        assert d == date(date.today().year, 8, 3)
        assert remaining == "项目投标费"

    def test_u19_m月d号格式(self):
        d, remaining = extract_date_and_purpose("8月3号 项目投标费")
        assert d == date(date.today().year, 8, 3)
        assert remaining == "项目投标费"

    def test_u19_yyyy_mm_dd格式(self):
        d, remaining = extract_date_and_purpose("2026-08-03 项目投标费")
        assert d == date(2026, 8, 3)
        assert remaining == "项目投标费"

    def test_u19_yyyy年m月d日格式(self):
        d, remaining = extract_date_and_purpose("2026年8月3日 项目投标费")
        assert d == date(2026, 8, 3)
        assert remaining == "项目投标费"

    def test_u19_日期在后(self):
        d, remaining = extract_date_and_purpose("项目投标费 8月3日")
        assert d == date(date.today().year, 8, 3)
        assert remaining == "项目投标费"

    def test_u19_无日期返回原文本(self):
        d, remaining = extract_date_and_purpose("项目投标费")
        assert d is None
        assert remaining == "项目投标费"

    def test_u19_空文本(self):
        d, remaining = extract_date_and_purpose("")
        assert d is None
        assert remaining == ""
