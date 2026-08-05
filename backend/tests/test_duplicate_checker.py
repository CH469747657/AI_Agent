"""duplicate_checker 单元测试

覆盖纯函数：hamming_distance / _has_matching_field
compute_phash 测试需 imagehash + PIL，依赖在容器内，
本地若缺则用 pytest.importorskip 自动跳过。
"""

import sys
import os
import pytest
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.duplicate_checker import (
    hamming_distance,
    DuplicateChecker,
    PHASH_HAMMING_THRESHOLD,
)


class TestHammingDistance:
    def test_identical_hashes_distance_zero(self):
        """相同 hash → 距离 0"""
        h = "f" * 16
        assert hamming_distance(h, h) == 0

    def test_one_bit_difference(self):
        """差 1 bit → 距离 1"""
        h1 = "0000000000000001"
        h2 = "0000000000000000"
        assert hamming_distance(h1, h2) == 1

    def test_char_difference_is_bit_difference(self):
        """字符差异 = 比特差异

        'f' (1111) vs 'e' (1110) → XOR = 0001 → 1 bit
        """
        h1 = "f" + "0" * 15
        h2 = "e" + "0" * 15
        assert hamming_distance(h1, h2) == 1

    def test_completely_different_hashes_distance_64(self):
        """完全不同 → 距离 64（满）"""
        h1 = "0" * 16
        h2 = "f" * 16
        assert hamming_distance(h1, h2) == 64

    def test_invalid_hash_returns_64(self):
        """非法 hash → 返回 64（保守值）"""
        assert hamming_distance("invalid", "0000000000000000") == 64
        assert hamming_distance(None, "0000000000000000") == 64

    def test_threshold_is_strict(self):
        """阈值严格 ≤ 3"""
        assert PHASH_HAMMING_THRESHOLD == 3


class TestComputePhash:
    """compute_phash 需 imagehash + PIL，依赖在容器内；本地缺则跳过"""

    def test_returns_hex_string_for_png(self):
        pytest.importorskip("imagehash")
        pytest.importorskip("PIL")
        from PIL import Image
        from app.services.duplicate_checker import compute_phash

        img = Image.new("RGB", (100, 100), color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        result = compute_phash(buf.getvalue(), "png")
        assert result is not None
        assert len(result) == 16  # imagehash.phash 默认 hash_size=8 → 16 hex chars
        int(result, 16)

    def test_returns_same_hash_for_same_image(self):
        pytest.importorskip("imagehash")
        pytest.importorskip("PIL")
        from PIL import Image
        from app.services.duplicate_checker import compute_phash

        img = Image.new("RGB", (100, 100), color="white")
        buf1 = BytesIO(); img.save(buf1, format="PNG")
        buf2 = BytesIO(); img.save(buf2, format="PNG")

        h1 = compute_phash(buf1.getvalue(), "png")
        h2 = compute_phash(buf2.getvalue(), "png")
        assert h1 == h2

    def test_returns_none_for_invalid_data(self):
        pytest.importorskip("imagehash")
        from app.services.duplicate_checker import compute_phash
        result = compute_phash(b"not an image", "png")
        assert result is None


class TestHasMatchingField:
    """交叉验证：pHash 匹配后需至少一个业务字段一致"""

    def test_same_seller_matches(self):
        """销售方一致 → True"""
        invoice_data = {"seller_name": "中石化", "total_with_tax": "100", "issue_date": "2026-01-01"}
        matched_invoice = _make_matched_invoice(seller_name="中石化")
        assert DuplicateChecker._has_matching_field(invoice_data, matched_invoice) is True

    def test_same_amount_matches(self):
        """金额一致 → True"""
        invoice_data = {"total_with_tax": "350.00", "issue_date": "2026-01-01"}
        matched_invoice = _make_matched_invoice(total_with_tax="350.00")
        assert DuplicateChecker._has_matching_field(invoice_data, matched_invoice) is True

    def test_same_date_matches(self):
        """日期一致 → True"""
        invoice_data = {"issue_date": "2026-01-15"}
        matched_invoice = _make_matched_invoice(issue_date="2026-01-15")
        assert DuplicateChecker._has_matching_field(invoice_data, matched_invoice) is True

    def test_all_fields_differ_returns_false(self):
        """所有业务字段都不同 → False（防止同模板不同票误判）"""
        invoice_data = {
            "seller_name": "中石化",
            "total_with_tax": "100",
            "issue_date": "2026-01-01",
        }
        matched_invoice = _make_matched_invoice(
            seller_name="中石油",
            total_with_tax="200",
            issue_date="2026-02-02",
        )
        assert DuplicateChecker._has_matching_field(invoice_data, matched_invoice) is False

    def test_empty_fields_returns_false(self):
        """所有字段都空 → False"""
        invoice_data = {}
        matched_invoice = _make_matched_invoice()
        assert DuplicateChecker._has_matching_field(invoice_data, matched_invoice) is False


# ===== 测试辅助 =====
class _FakeInvoice:
    """模拟 Invoice 对象，避免依赖 DB"""
    def __init__(self, **kwargs):
        self.seller_name = kwargs.get("seller_name")
        self.total_with_tax = kwargs.get("total_with_tax")
        self.issue_date = kwargs.get("issue_date")


def _make_matched_invoice(**kwargs):
    return _FakeInvoice(**kwargs)
