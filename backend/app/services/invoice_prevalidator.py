"""发票预校验服务 — 在在线验真之前检测逻辑矛盾，无需调用外部 API

校验规则：
  1. 发票号码/代码格式矛盾
     - 有发票代码（传统票）→ 号码应为 8 位
     - 发票号码 20 位（数电票）→ 不应有发票代码
     - 两者矛盾则判定为校验失败

  2. 金额数学矛盾
     - 价税合计 ≈ 不含税金额 + 税额（容差 1%）
     - 严重偏差则判定为校验失败

  3. 备注关键词检测
     - 含"测试发票""样本发票""示例发票"等关键词
     - 判定为校验失败

  4. 增值税发票校验码缺失
     - 增值税普通发票必须有校验码
     - 专票可无校验码，数电票校验码非必填

校验结果：
  - is_valid=False  → 明确校验失败，无需调在线验真
  - is_valid=None   → 预校验通过，继续后续在线验真流程
"""

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 测试/样本发票关键词
TEST_INVOICE_KEYWORDS = [
    "测试发票", "样本发票", "示例发票", "模板发票",
    "假发票", "伪造发票", "模拟发票", "虚构发票",
    "仅用于测试", "仅供测试", "test invoice",
]


@dataclass
class PreCheckResult:
    """预校验结果"""
    # True=预校验通过, False=预校验失败（判定为无效发票）
    is_valid: bool
    # 校验失败原因（多条用分号连接）
    message: str
    # 检测到的问题列表
    issues: list = field(default_factory=list)


def precheck_invoice(fields: dict) -> PreCheckResult:
    """发票预校验主入口

    Args:
        fields: OCR/LLM 提取的发票字段字典，包含：
            - invoice_number: 发票号码
            - invoice_code: 发票代码（可为空）
            - check_code: 校验码（可为空）
            - receipt_type: 票据类型
            - amount: 不含税金额
            - tax_amount: 税额
            - total_with_tax: 价税合计
            - seller_name: 销方名称
            - seller_tax_id: 销方税号
            - buyer_name: 购方名称
            - 备注/remarks: 备注内容

    Returns:
        PreCheckResult
    """
    issues = []

    invoice_number = str(fields.get("invoice_number") or "").strip()
    invoice_code = str(fields.get("invoice_code") or "").strip()
    receipt_type = str(fields.get("receipt_type") or "").strip()

    # === 规则 1: 发票号码/代码格式矛盾 ===
    issue = _check_number_code_consistency(invoice_number, invoice_code, receipt_type)
    if issue:
        issues.append(issue)

    # === 规则 2: 金额数学矛盾 ===
    issue = _check_amount_consistency(fields)
    if issue:
        issues.append(issue)

    # === 规则 3: 备注关键词检测 ===
    issue = _check_test_keywords(fields)
    if issue:
        issues.append(issue)

    # === 规则 4: 增值税普通发票校验码缺失 ===
    issue = _check_check_code_missing(fields)
    if issue:
        issues.append(issue)

    if issues:
        message = "；".join(issues)
        logger.warning(f"发票预校验失败: {message}")
        return PreCheckResult(is_valid=False, message=f"预校验未通过: {message}", issues=issues)

    logger.info("发票预校验通过")
    return PreCheckResult(is_valid=True, message="预校验通过", issues=[])


def _check_number_code_consistency(
    invoice_number: str, invoice_code: str, receipt_type: str
) -> str | None:
    """检查发票号码/代码格式矛盾

    中国增值税发票号码规则：
    - 传统纸质/电子发票：发票代码 10-12 位，发票号码 8 位
    - 数电票（全电发票）：无发票代码，发票号码 20 位

    如果出现以下矛盾，说明发票格式异常：
    - 有发票代码 + 号码 20 位（数电票不应有代码）
    - 无发票代码 + 号码 8 位（传统票应有代码）
    - 有发票代码 + 号码非 8 位也非 20 位
    """
    if not invoice_number:
        return None

    num_len = len(invoice_number)
    is_numeric = invoice_number.isdigit()
    has_code = bool(invoice_code)

    # 号码长度异常（既不是 8 位也不是 20 位）
    if is_numeric and num_len not in (8, 20):
        return f"发票号码位数异常: {num_len}位（应为8位传统票或20位数电票）"

    # 数电票（20位）+ 有发票代码 → 矛盾
    if num_len == 20 and has_code:
        return (
            f"发票号码/代码矛盾: 20位号码属于数电票，不应同时存在发票代码({invoice_code})"
        )

    # 传统票（8位）+ 无发票代码 → 疑似异常（宽松警告，不强制判失败）
    # 传统专票/普票确实应有代码，但某些老版电子发票可能代码为空
    # 这里仅对增值税发票做严格检查
    if num_len == 8 and not has_code:
        is_vat = "增值税" in receipt_type or "vat" in receipt_type.lower()
        if is_vat:
            return (
                f"发票号码/代码矛盾: 8位号码属于传统增值税发票，应同时存在发票代码"
            )

    return None


def _check_amount_consistency(fields: dict) -> str | None:
    """检查金额数学矛盾

    价税合计 ≈ 不含税金额 + 税额
    允许 1% 容差（四舍五入可能导致微小差异）
    """
    def parse_amount(val) -> float | None:
        if not val:
            return None
        try:
            return float(str(val).replace(",", "").replace("￥", "").replace("¥", "").strip())
        except (ValueError, TypeError):
            return None

    total = parse_amount(fields.get("total_with_tax"))
    amount = parse_amount(fields.get("amount"))
    tax = parse_amount(fields.get("tax_amount"))

    # 三项都有才检查
    if total is None or amount is None or tax is None:
        return None

    # 全部为 0 跳过
    if total == 0 and amount == 0 and tax == 0:
        return None

    expected_total = amount + tax

    # 价税合计不应小于不含税金额
    if total < amount:
        return (
            f"金额矛盾: 价税合计({total:.2f})小于不含税金额({amount:.2f})"
        )

    # 差值超过 1% 容差
    if expected_total > 0:
        diff_ratio = abs(total - expected_total) / expected_total
        if diff_ratio > 0.01:
            return (
                f"金额矛盾: 价税合计({total:.2f}) ≠ 不含税金额({amount:.2f}) + "
                f"税额({tax:.2f}) = {expected_total:.2f}（偏差{diff_ratio*100:.1f}%）"
            )

    return None


def _check_test_keywords(fields: dict) -> str | None:
    """检查备注/描述中是否含测试/伪造关键词"""
    # 检查多个可能含备注的字段
    text_fields = [
        fields.get("user_description", ""),
        fields.get("remarks", ""),
        fields.get("notes", ""),
    ]
    combined_text = " ".join(str(t) for t in text_fields if t)

    for kw in TEST_INVOICE_KEYWORDS:
        if kw in combined_text:
            return f"备注含异常关键词: '{kw}'"

    return None


def _check_check_code_missing(fields: dict) -> str | None:
    """检查增值税普通发票校验码缺失

    规则：
    - 增值税普通发票：应有校验码
    - 增值税专用发票：可无校验码
    - 数电票（20位号码）：校验码非必填
    """
    receipt_type = str(fields.get("receipt_type") or "")
    check_code = str(fields.get("check_code") or "").strip()
    invoice_number = str(fields.get("invoice_number") or "").strip()

    # 数电票跳过
    if len(invoice_number) == 20:
        return None

    # 专票跳过
    if "专用发票" in receipt_type or "专票" in receipt_type:
        return None

    # 普通发票应有校验码
    if "普通发票" in receipt_type or "普票" in receipt_type:
        if not check_code:
            return "增值税普通发票缺少校验码"

    return None
