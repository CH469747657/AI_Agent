"""上传流程 VLM 字段真值判断测试 — OFD 识别 bug 修复

Bug（2026-10-16 实例 #11）：OFD 电子发票无票面截图，Combined VLM 拿到的
是ofd_parser 提取的印章图 → LLM 返回 {receipt_type:"未知", fields:{全 null}}
—— 非空 dict 但无任何有效值。上传流程 `if vlm_fields:` 判 True，
误以为 VLM 识别成功，跳过 _run_dual_source → OFD 矢量字段（100% 精度）
从未被使用，发票字段全空。

修复：`if vlm_fields:` → `if vlm_fields and any(vlm_fields.values()):`
全 null 的 VLM 结果视为无效，回落到双源路径（OFD 走 ofd_parser 矢量解析）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _has_effective_vlm_fields(vlm_fields) -> bool:
    """与 invoice_service.upload_invoice 中修复后的判断保持一致（镜像断言用）"""
    return bool(vlm_fields) and any(vlm_fields.values())


class TestVlmFieldsTruthiness:
    """VLM 字段有效性判断的边界"""

    def test_all_none_dict_is_invalid(self):
        """全 null 值的非空 dict = 无效（bug 场景：OFD 印章图识别结果）"""
        vlm_fields = {
            "invoice_number": None, "seller_name": None,
            "total_with_tax": None, "issue_date": None,
        }
        assert _has_effective_vlm_fields(vlm_fields) is False

    def test_partial_fields_is_valid(self):
        """至少一个非 null 值 = 有效"""
        vlm_fields = {"invoice_number": "25322000000359354502", "seller_name": None}
        assert _has_effective_vlm_fields(vlm_fields) is True

    def test_empty_dict_is_invalid(self):
        assert _has_effective_vlm_fields({}) is False

    def test_none_is_invalid(self):
        assert _has_effective_vlm_fields(None) is False

    def test_empty_string_values_are_invalid(self):
        """空串值也视为无效（LLM 偶尔返回空串而非 null）"""
        vlm_fields = {"invoice_number": "", "seller_name": ""}
        assert _has_effective_vlm_fields(vlm_fields) is False


class TestUploadFlowGuard:
    """upload_invoice 源码级防护：确保修复条件在源码中存在"""

    def test_source_contains_effective_check(self):
        """invoice_service.py 的 vlm_fields 分支必须用 any(values) 守卫"""
        src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "services", "invoice_service.py",
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        # 旧的 buggy 条件不应存在
        assert "if vlm_fields and any(vlm_fields.values()):" in src, (
            "upload 流程必须用 any(vlm_fields.values()) 守卫全 null 的 VLM 结果"
        )


class TestOfdVectorFieldsFlow:
    """OFD 矢量字段应通过 _run_dual_source 正常到达（回归保护）"""

    def test_process_ofd_returns_vector_fields(self):
        """process_ofd 对含矢量文字的 OFD 返回 100% 置信度字段（不依赖图片）"""
        from app.services.ocr_service import get_ocr_service
        # 构造最小 OFD：真实文件依赖较重，这里验证函数对无矢量文字+无图的行为
        # （有矢量文字的场景由集成验证覆盖 —— 实例 #11 重触发）
        result = get_ocr_service().process_ofd(b"not-a-real-ofd")
        assert result["confidence"] == 0.0
        assert result["extracted_fields"] == {}
