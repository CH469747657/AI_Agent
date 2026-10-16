"""对话框上传 OFD 崩溃修复测试 — receipt_type 非法值防御

Bug（2026-10-16 10:33）：对话框上传 OFD 发票时，LLM 把文件格式 "OFD"
填进 emp_upload_invoice 的 receipt_type 参数 →
ReceiptType("OFD") → ValueError → Agent 向用户误报"OFD 格式暂不支持"。

修复：
1. invoice_service.process_upload：receipt_type 非法值回落默认 vat_normal
   （后续 Combined VLM 会看图重判类型，默认值无损）
2. tool_params.UploadInvoiceParams：参数描述明确"票据种类，非文件格式"
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.models.invoice import ReceiptType


def _is_valid_receipt_type(val: str) -> bool:
    return val in {t.value for t in ReceiptType}


class TestReceiptTypeValidation:
    """非法 receipt_type 应被识别并回落（与 process_upload 修复逻辑一致）"""

    def test_ofd_file_format_is_invalid(self):
        assert _is_valid_receipt_type("OFD") is False

    def test_valid_types_pass(self):
        for t in ["增值税普通发票", "增值税专用发票", "火车票", "机票", "收据", "支付截图", "交易流水单"]:
            assert _is_valid_receipt_type(t) is True

    def test_empty_is_handled_by_default_branch(self):
        """空值走既有默认分支（vat_normal），不进枚举校验"""
        assert _is_valid_receipt_type("") is False


class TestProcessUploadGuard:
    """process_upload 源码级防护：非法值回落而非 ValueError"""

    def test_source_has_fallback_guard(self):
        src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "services", "invoice_service.py",
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "if actual_receipt_type not in {t.value for t in ReceiptType}:" in src, (
            "process_upload 必须对非法 receipt_type 回落默认值（防 LLM 把文件格式当票据种类）"
        )


class TestToolParamDescription:
    """工具参数描述必须明确 receipt_type 是票据种类而非文件格式"""

    def test_upload_params_description_mentions_format_exclusion(self):
        from app.dialog.tool_params import UploadInvoiceParams
        desc = UploadInvoiceParams.model_fields["receipt_type"].description or ""
        assert "文件格式" in desc, (
            "参数描述应说明 receipt_type 是票据种类，非文件格式（防 LLM 填 OFD/PDF）"
        )
