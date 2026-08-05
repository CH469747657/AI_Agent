"""验真返回的票面信息 与 OCR/LLM 双源结果的第三源交叉验证

百度验真 API 返回国税权威票面数据（seller_name / amount / total_with_tax /
invoice_number / issue_date 等），可作为第三源对双源结果做最终校验。

策略:
  - 仅比对 verified_fields 非空且 confirmed 非空的字段
  - 标准化后比较（去空格、大小写、金额单位）
  - 差异字段记录到 verify_cross_check，并在 verify_status 已 VALID 的基础上
    把 invoice.status 降级为 reviewing（验真一致但与本地识别冲突，需人工确认）
"""

import logging
from typing import Any

from app.services.diff_engine import normalize_value, _parse_amount

logger = logging.getLogger(__name__)

# 可比对字段（验真返回的字段名与本地一致）
CROSS_CHECK_FIELDS = [
    "invoice_number",
    "invoice_code",
    "issue_date",
    "seller_name",
    "seller_tax_id",
    "buyer_name",
    "buyer_tax_id",
    "total_with_tax",
    "amount",
    "tax_amount",
    "check_code",
]


def cross_check_verified_fields(
    confirmed: dict, verified_fields: dict
) -> dict:
    """对比验真返回字段与本地确认字段

    Returns:
        {
            "mismatches": list[dict],   # 不一致字段（field/local/verified）
            "matches": int,            # 一致字段数
            "total_compared": int,     # 实际对比字段数
            "confidence": float,       # 一致率 0.0-1.0
        }
    """
    mismatches = []
    matches = 0
    compared = 0

    for field in CROSS_CHECK_FIELDS:
        local_val = confirmed.get(field)
        verified_val = verified_fields.get(field)
        if local_val is None or verified_val is None:
            continue

        compared += 1

        # 金额类用数值比较（容差 0.01）
        if field in ("total_with_tax", "amount", "tax_amount"):
            local_num = _parse_amount(local_val)
            verified_num = _parse_amount(verified_val)
            if local_num is not None and verified_num is not None:
                if abs(local_num - verified_num) <= 0.01:
                    matches += 1
                    continue
                mismatches.append({
                    "field": field,
                    "local": local_val,
                    "verified": verified_val,
                    "reason": "金额不一致",
                })
                continue

        # 文本类标准化后比较
        local_norm = normalize_value(local_val)
        verified_norm = normalize_value(verified_val)
        if local_norm and verified_norm and local_norm == verified_norm:
            matches += 1
        else:
            mismatches.append({
                "field": field,
                "local": local_val,
                "verified": verified_val,
                "reason": "值不一致",
            })

    confidence = (matches / compared) if compared > 0 else 1.0
    return {
        "mismatches": mismatches,
        "matches": matches,
        "total_compared": compared,
        "confidence": round(confidence, 4),
    }
