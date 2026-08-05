"""verify_cross_check 单元测试

覆盖验真返回字段与本地确认字段的交叉验证逻辑
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.verify_cross_check import cross_check_verified_fields


class TestCrossCheckVerifiedFields:
    def test_all_fields_match(self):
        """所有字段一致 → confidence=1.0, 无 mismatches"""
        confirmed = {
            "invoice_number": "12345678901234567890",
            "seller_name": "中国石化销售有限公司",
            "total_with_tax": "350.00",
            "amount": "300.00",
            "tax_amount": "50.00",
        }
        verified = dict(confirmed)

        result = cross_check_verified_fields(confirmed, verified)
        assert result["mismatches"] == []
        assert result["confidence"] == 1.0
        assert result["matches"] == 5

    def test_amount_tolerance(self):
        """金额容差 0.01 — 350.00 vs 350.005 视为一致"""
        confirmed = {"total_with_tax": "350.00"}
        verified = {"total_with_tax": "350.005"}
        result = cross_check_verified_fields(confirmed, verified)
        assert result["mismatches"] == []
        assert result["confidence"] == 1.0

    def test_amount_mismatch(self):
        """金额不一致 → mismatch"""
        confirmed = {"total_with_tax": "350.00"}
        verified = {"total_with_tax": "300.00"}
        result = cross_check_verified_fields(confirmed, verified)
        assert len(result["mismatches"]) == 1
        assert result["mismatches"][0]["field"] == "total_with_tax"
        assert result["mismatches"][0]["reason"] == "金额不一致"
        assert result["confidence"] == 0.0

    def test_text_mismatch(self):
        """文本不一致 → mismatch"""
        confirmed = {"seller_name": "中国石化"}
        verified = {"seller_name": "中国石油"}
        result = cross_check_verified_fields(confirmed, verified)
        assert len(result["mismatches"]) == 1
        assert result["confidence"] == 0.0

    def test_text_normalization(self):
        """标准化后一致（去空格、大小写、货币符号）"""
        confirmed = {"seller_name": " 中国石化 "}
        verified = {"seller_name": "中国石化"}
        result = cross_check_verified_fields(confirmed, verified)
        assert result["mismatches"] == []
        assert result["confidence"] == 1.0

    def test_skip_none_fields(self):
        """任一源为空 → 跳过该字段"""
        confirmed = {"invoice_number": "12345678901234567890", "seller_name": None}
        verified = {"invoice_number": "12345678901234567890", "seller_name": "中石化"}
        result = cross_check_verified_fields(confirmed, verified)
        # 只对比了 invoice_number
        assert result["total_compared"] == 1
        assert result["matches"] == 1
        assert result["confidence"] == 1.0

    def test_partial_match(self):
        """部分一致"""
        confirmed = {
            "invoice_number": "12345678901234567890",  # 一致
            "seller_name": "中石化",                  # 不一致
            "total_with_tax": "350.00",              # 一致
        }
        verified = {
            "invoice_number": "12345678901234567890",
            "seller_name": "中石油",
            "total_with_tax": "350.00",
        }
        result = cross_check_verified_fields(confirmed, verified)
        assert result["matches"] == 2
        assert len(result["mismatches"]) == 1
        assert result["confidence"] == round(2 / 3, 4)

    def test_empty_dicts_returns_full_confidence(self):
        """两边都空 → confidence=1.0（无字段可比，视为通过）"""
        result = cross_check_verified_fields({}, {})
        assert result["mismatches"] == []
        assert result["total_compared"] == 0
        assert result["confidence"] == 1.0
