"""双源比对引擎（增强版）

核心改进:
1. 冲突时按字段类型择优: 数字字段优先OCR, 文本字段优先LLM
2. 交叉验证: 价税合计=不含税+税额, 购买方≠销售方, 发票号格式校验
3. 置信度评分: 正确的冲突解决会提升置信度

参考项目: stone16/Invoice-Manager invoice_service.py
技术路线: 逐字段对比 OCR 与 LLM 结果，匹配自动确认，冲突按规则择优
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 可对比的13个字段（与 invoice.py COMPARABLE_FIELDS 一致）
COMPARABLE_FIELDS = [
    "invoice_number", "invoice_code", "check_code",
    "issue_date", "buyer_name", "buyer_tax_id",
    "seller_name", "seller_tax_id", "item_name",
    "total_with_tax", "amount", "tax_amount", "tax_rate",
]

# 数字/编码类字段 — OCR更精确（逐字符识别）
NUMERIC_FIELDS = {
    "invoice_number", "invoice_code", "check_code",
    "total_with_tax", "amount", "tax_amount", "tax_rate",
    "buyer_tax_id", "seller_tax_id",
}

# 文本类字段 — LLM更准确（理解上下文，不会混淆购买方/销售方）
TEXT_FIELDS = {
    "buyer_name", "seller_name", "item_name",
}


def normalize_value(value: Any) -> str | None:
    """标准化字段值用于比较"""
    if value is None:
        return None
    if isinstance(value, str):
        val = value.strip()
        # 去除常见噪音字符
        val = val.replace(" ", "").replace("　", "").replace("，", "").replace(",", "")
        val = val.replace("￥", "").replace("¥", "")
        return val.lower() if val else None
    return str(value).strip().lower()


# ===== 交叉验证规则 =====

def _parse_amount(val: Any) -> float | None:
    """安全解析金额为 float"""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("￥", "").replace("¥", "").strip())
    except (ValueError, TypeError):
        return None


def _validate_invoice_number(val: Any) -> bool:
    """发票号码格式校验：增值税发票必须20位纯数字"""
    if not val:
        return False
    num = str(val).strip()
    return bool(re.match(r"^\d{20}$", num))


def _extract_amounts_from_raw_text(raw_text: str) -> dict | None:
    """从 OCR/LLM 原始文本中正则提取价税合计和合计金额

    发票格式通常包含:
      - 价税合计（小写）¥215.80
      - 合计 ￥203.58  ￥12.22
    当双源都混淆了"合计"和"价税合计"时，用此方法从原始文本中精确提取。

    Returns:
        {"total_with_tax": str, "amount": str, "tax_amount": str} 或 None
    """
    if not raw_text:
        return None

    # 将文本合并为单行便于匹配跨行内容
    flat = raw_text.replace("\n", " ").replace("\r", " ")
    # 清理多余空格
    flat = re.sub(r"\s+", " ", flat)

    total_val = None
    amount_val = None
    tax_val = None

    # 模式1: 价税合计（小写）¥215.80  或  （小写)¥215.80
    m = re.search(r"[价税合计]+[（(]小写[)）]\s*[￥¥]?([\d,.]+)", flat)
    if not m:
        # 宽松模式: "(小写)" + 数字
        m = re.search(r"小写[)）]\s*[￥¥]?([\d,.]+)", flat)
    if m:
        total_val = m.group(1).replace(",", "")

    # 模式2: 合计 ￥203.58  ￥12.22
    # 寻找"合计"后的两个金额（不含税金额 + 税额）
    # 发票通常格式: 合计  ￥203.58  ￥12.22
    subtotal_pat = re.search(
        r"合计\s*[￥¥]([\d,.]+)\s*[￥¥]([\d,.]+)",
        flat
    )
    if not subtotal_pat:
        # 尝试匹配跨行: 合\n计  ￥203.58\n￥12.22 (已被合并)
        subtotal_pat = re.search(
            r"合\s*计\s*[￥¥]([\d,.]+)\s*[￥¥]([\d,.]+)",
            flat
        )
    if subtotal_pat:
        amount_val = subtotal_pat.group(1).replace(",", "")
        tax_val = subtotal_pat.group(2).replace(",", "")

    if total_val and amount_val and tax_val:
        logger.info(
            f"原始文本金额提取: 价税合计={total_val}, 合计={amount_val}, 税额={tax_val}"
        )
        return {
            "total_with_tax": total_val,
            "amount": amount_val,
            "tax_amount": tax_val,
        }
    elif total_val:
        # 至少提取到了价税合计
        logger.info(f"原始文本仅提取到价税合计={total_val}")
        return {"total_with_tax": total_val}

    return None


def _cross_validate_amounts(confirmed: dict, ocr_fields: dict, llm_fields: dict, conflicts: list, raw_text: str = "") -> dict:
    """交叉验证金额关系: total_with_tax ≈ amount + tax_amount

    增强逻辑:
    1. 当某源 total 为空但另一源有 total 时，交叉补齐
    2. 当两源的 amount+tax 都等于另一个源的 total 时，说明 amount 可能是 total 的误填
    3. 尝试从 OCR 原始文本正则提取价税合计作为第三源
    4. 所有自动纠正失败时标记为 VALIDATION_WARNING
    """
    total = _parse_amount(confirmed.get("total_with_tax"))
    amount = _parse_amount(confirmed.get("amount"))
    tax = _parse_amount(confirmed.get("tax_amount"))

    # ===== 第一层: 尝试从原始文本正则提取价税合计（最可靠） =====
    raw_amounts = _extract_amounts_from_raw_text(raw_text)

    # ===== 第二层: 如果双源金额关系已成立，但仍需验证 total 的正确性 =====
    # 场景: OCR 的 amount 实际上是"合计"(不含税)，LLM 把"合计"填到 total
    #       两者关系碰巧成立但 total 本身是错的
    # 解决: 如果原始文本提取到了价税合计，且与当前 confirmed 的 total 不同，以原始文本为准
    if total is not None and amount is not None and tax is not None:
        expected_total = round(amount + tax, 2)
        if abs(total - expected_total) <= 0.02:
            # 金额关系成立，但需要验证 total 是否真的是价税合计
            if raw_amounts and raw_amounts.get("total_with_tax"):
                raw_total = _parse_amount(raw_amounts["total_with_tax"])
                if raw_total is not None and abs(raw_total - total) > 0.02:
                    # 原始文本的价税合计与当前 confirmed 的 total 不同
                    # 说明当前 total 可能是"合计"被误认为"价税合计"
                    logger.warning(
                        f"金额关系成立但 total 可能是'合计'被误认为'价税合计': "
                        f"current total={total}, raw_text total={raw_total}, "
                        f"用原始文本纠正"
                    )
                    confirmed["total_with_tax"] = raw_amounts["total_with_tax"]
                    if raw_amounts.get("amount"):
                        confirmed["amount"] = raw_amounts["amount"]
                    if raw_amounts.get("tax_amount"):
                        confirmed["tax_amount"] = raw_amounts["tax_amount"]
                    for c in conflicts:
                        if c.get("field") in ("total_with_tax", "amount", "tax_amount"):
                            c["status"] = "RESOLVED"
                            c["resolved_by"] = "raw_text"
                            c["resolved_reason"] = "原始文本正则: 价税合计与双源不一致，以原始文本为准"
                    return confirmed
            return confirmed  # 金额关系成立且无原始文本反证，无需纠正

    # ===== 第三层: total 为空时交叉补齐 =====
    if total is None and amount is not None and tax is not None:
        # 先尝试原始文本
        if raw_amounts and raw_amounts.get("total_with_tax"):
            raw_total = _parse_amount(raw_amounts["total_with_tax"])
            if raw_total is not None:
                confirmed["total_with_tax"] = raw_amounts["total_with_tax"]
                logger.info(f"金额补齐(原始文本): total_with_tax={raw_total}")
                if raw_amounts.get("amount"):
                    confirmed["amount"] = raw_amounts["amount"]
                if raw_amounts.get("tax_amount"):
                    confirmed["tax_amount"] = raw_amounts["tax_amount"]
                for c in conflicts:
                    if c.get("field") in ("total_with_tax", "amount", "tax_amount"):
                        c["status"] = "RESOLVED"
                        c["resolved_by"] = "raw_text"
                        c["resolved_reason"] = "原始文本补齐: 价税合计"
                return confirmed

        # 再尝试从另一源补齐 total
        for src_name, src_fields in [("OCR", ocr_fields), ("LLM", llm_fields)]:
            src_total = _parse_amount(src_fields.get("total_with_tax"))
            if src_total is not None and abs(src_total - (amount + tax)) <= 0.02:
                confirmed["total_with_tax"] = src_fields.get("total_with_tax")
                logger.info(f"金额补齐: {src_name} 的 total_with_tax({src_total}) 满足 amount+tax 关系")
                return confirmed

        # 双源都没有可用的 total，尝试用 amount + tax 推算
        confirmed["total_with_tax"] = str(round(amount + tax, 2))
        logger.info(f"金额补齐(推算): total_with_tax={round(amount + tax, 2)} (amount={amount}+tax={tax})")
        return confirmed

    # ===== 第四层: 金额关系不成立，尝试自动纠正 =====
    if total is not None and (amount is not None or tax is not None):
        logger.warning(
            f"金额交叉验证失败: total={total}, amount={amount}, tax={tax}, 尝试自动纠正"
        )

        # 优先用原始文本纠正
        if raw_amounts and raw_amounts.get("total_with_tax"):
            raw_total = _parse_amount(raw_amounts["total_with_tax"])
            raw_amt = _parse_amount(raw_amounts.get("amount"))
            raw_tax = _parse_amount(raw_amounts.get("tax_amount"))
            if raw_total is not None:
                # 用原始文本的金额组替换
                confirmed["total_with_tax"] = raw_amounts["total_with_tax"]
                if raw_amt is not None:
                    confirmed["amount"] = raw_amounts["amount"]
                if raw_tax is not None:
                    confirmed["tax_amount"] = raw_amounts["tax_amount"]
                logger.info(
                    f"金额纠正(原始文本): total={raw_total}, "
                    f"amount={raw_amt}, tax={raw_tax}"
                )
                for c in conflicts:
                    if c.get("field") in ("total_with_tax", "amount", "tax_amount"):
                        c["status"] = "RESOLVED"
                        c["resolved_by"] = "raw_text"
                        c["resolved_reason"] = "原始文本纠正: 金额关系不成立"
                return confirmed

        # 逐源检查哪个源的金额三值满足关系
        for src_name, src_fields in [("OCR", ocr_fields), ("LLM", llm_fields)]:
            src_total = _parse_amount(src_fields.get("total_with_tax"))
            src_amount = _parse_amount(src_fields.get("amount"))
            src_tax = _parse_amount(src_fields.get("tax_amount"))
            if src_total is not None and src_amount is not None and src_tax is not None:
                if abs(src_total - round(src_amount + src_tax, 2)) <= 0.02:
                    # 该源的金额关系正确 → 采用该源的完整金额组
                    corrected = {}
                    if confirmed.get("total_with_tax") != src_fields.get("total_with_tax"):
                        corrected["total_with_tax"] = src_fields.get("total_with_tax")
                        confirmed["total_with_tax"] = src_fields.get("total_with_tax")
                    if confirmed.get("amount") != src_fields.get("amount"):
                        corrected["amount"] = src_fields.get("amount")
                        confirmed["amount"] = src_fields.get("amount")
                    if confirmed.get("tax_amount") != src_fields.get("tax_amount"):
                        corrected["tax_amount"] = src_fields.get("tax_amount")
                        confirmed["tax_amount"] = src_fields.get("tax_amount")
                    if corrected:
                        logger.info(
                            f"金额自动纠正: 采用 {src_name} 的金额组 "
                            f"(total={src_total}, amount={src_amount}, tax={src_tax})"
                        )
                        for c in conflicts:
                            if c.get("field") in ("total_with_tax", "amount", "tax_amount"):
                                c["status"] = "RESOLVED"
                                c["resolved_by"] = "cross_validation"
                                c["resolved_reason"] = f"金额关系验证: {src_name} 满足 价税合计=不含税+税额"
                    return confirmed

    # 所有纠正都失败 → 标记为 VALIDATION_WARNING 触发人工复核
    confirmed["_amount_validation_failed"] = True
    return confirmed


def _validate_buyer_seller(confirmed: dict, ocr_fields: dict, llm_fields: dict, conflicts: list) -> dict:
    """购买方和销售方不应相同（增值税发票场景）

    如果两者相同，说明其中一方识别有误。
    尝试用税号差异自动纠正；无法纠正时升级为 CONFLICT 触发人工复核。
    """
    buyer = normalize_value(confirmed.get("buyer_name"))
    seller = normalize_value(confirmed.get("seller_name"))

    if not (buyer and seller and buyer == seller):
        return confirmed

    logger.warning(f"购买方与销售方相同，疑似识别错误: {buyer}")

    # 尝试自动纠正: 遍历 OCR/LLM 双源的原始值，寻找 buyer≠seller 的组合
    sources = [
        ("OCR", ocr_fields),
        ("LLM", llm_fields),
    ]
    for src_name, src_fields in sources:
        src_buyer = src_fields.get("buyer_name")
        src_seller = src_fields.get("seller_name")
        src_buyer_norm = normalize_value(src_buyer)
        src_seller_norm = normalize_value(src_seller)
        if src_buyer_norm and src_seller_norm and src_buyer_norm != src_seller_norm:
            # 该源的买卖方不同 → 用该源的 seller 纠正
            old_seller = confirmed.get("seller_name")
            confirmed["seller_name"] = src_seller
            logger.info(
                f"买卖方相同纠正: {src_name} 的买卖方不同 "
                f"(buyer={src_buyer}, seller={src_seller}) → "
                f"采用 {src_name} 的 seller 替换错误值({old_seller})"
            )
            _mark_resolved(conflicts, "seller_name", f"买卖方相同验证: {src_name} 的 seller 纠正了双源一致错误")
            return confirmed

    # 尝试用税号差异推断: 如果 buyer_tax_id ≠ seller_tax_id，
    # 说明买卖方确实是不同实体，但名称被识别成一样的
    buyer_tax = normalize_value(confirmed.get("buyer_tax_id"))
    seller_tax = normalize_value(confirmed.get("seller_tax_id"))
    if buyer_tax and seller_tax and buyer_tax != seller_tax:
        # 税号不同 → 交叉查源中哪一方的 seller_name 与当前错误值不同
        for src_name, src_fields in sources:
            src_seller = src_fields.get("seller_name")
            src_seller_norm = normalize_value(src_seller)
            if src_seller_norm and src_seller_norm != seller:
                confirmed["seller_name"] = src_seller
                logger.info(
                    f"买卖方相同(税号不同)纠正: 税号差异证实买卖方不同, "
                    f"采用 {src_name} 的 seller({src_seller}) 替换错误值"
                )
                _mark_resolved(conflicts, "seller_name", f"税号差异验证: {src_name} 的 seller 纠正了买卖方混淆")
                return confirmed

    # 无法自动纠正 → 标记为 CONFLICT（而非 WARNING），触发人工复核
    logger.warning(f"买卖方相同且无法自动纠正，升级为 CONFLICT 触发人工复核")
    confirmed["_buyer_seller_same"] = True
    return confirmed


def _mark_resolved(conflicts: list, field: str, reason: str, resolver: str = "cross_validation"):
    """标记某个字段的冲突已被交叉验证解决（覆盖默认择优原因）"""
    for c in conflicts:
        if c.get("field") == field:
            c["status"] = "RESOLVED"
            c["resolved_by"] = resolver
            c["resolved_reason"] = reason
            logger.info(f"冲突已解决: {field} — {reason}")
            break


def _apply_cross_validation_rules(
    confirmed: dict,
    ocr_fields: dict,
    llm_fields: dict,
    conflicts: list,
) -> dict:
    """应用交叉验证规则，在冲突时利用业务逻辑进一步择优"""

    # 规则1: 发票号码格式校验
    # 如果 OCR 的发票号符合20位格式，LLM 的不符合 → 用 OCR
    # 如果 LLM 的符合，OCR 的不符合 → 用 LLM
    ocr_num = ocr_fields.get("invoice_number")
    llm_num = llm_fields.get("invoice_number")
    if ocr_num and llm_num and ocr_num != llm_num:
        ocr_valid = _validate_invoice_number(ocr_num)
        llm_valid = _validate_invoice_number(llm_num)
        if ocr_valid and not llm_valid:
            confirmed["invoice_number"] = ocr_num
            logger.info(f"发票号格式校验: OCR({ocr_num})合格, LLM({llm_num})不合格 → 采用OCR")
            _mark_resolved(conflicts, "invoice_number", "格式校验: OCR符合20位标准")
        elif llm_valid and not ocr_valid:
            confirmed["invoice_number"] = llm_num
            logger.info(f"发票号格式校验: LLM({llm_num})合格, OCR({ocr_num})不合格 → 采用LLM")
            _mark_resolved(conflicts, "invoice_number", "格式校验: LLM符合20位标准")

    # 规则2: 金额关系验证 — 价税合计 = 不含税 + 税额
    ocr_total = _parse_amount(ocr_fields.get("total_with_tax"))
    ocr_amount = _parse_amount(ocr_fields.get("amount"))
    ocr_tax = _parse_amount(ocr_fields.get("tax_amount"))
    llm_total = _parse_amount(llm_fields.get("total_with_tax"))
    llm_amount = _parse_amount(llm_fields.get("amount"))
    llm_tax = _parse_amount(llm_fields.get("tax_amount"))

    ocr_amount_ok = (
        ocr_total is not None and ocr_amount is not None and ocr_tax is not None
        and abs(ocr_total - (ocr_amount + ocr_tax)) <= 0.02
    )
    llm_amount_ok = (
        llm_total is not None and llm_amount is not None and llm_tax is not None
        and abs(llm_total - (llm_amount + llm_tax)) <= 0.02
    )

    # 如果 total_with_tax 有冲突
    ocr_total_raw = ocr_fields.get("total_with_tax")
    llm_total_raw = llm_fields.get("total_with_tax")
    total_with_tax_conflict = (
        ocr_total_raw and llm_total_raw
        and normalize_value(ocr_total_raw) != normalize_value(llm_total_raw)
    )
    if total_with_tax_conflict:
        if ocr_amount_ok and not llm_amount_ok:
            # OCR金额关系正确，LLM错误 → 全部采用OCR金额
            confirmed["total_with_tax"] = ocr_total_raw
            confirmed["amount"] = ocr_fields.get("amount")
            confirmed["tax_amount"] = ocr_fields.get("tax_amount")
            logger.info(f"金额验证: OCR通过交叉验证, LLM未通过 → 全部采用OCR金额")
            _mark_resolved(conflicts, "total_with_tax", "金额关系验证: OCR 价税合计=不含税+税额")
            _mark_resolved(conflicts, "amount", "金额关系验证: OCR 价税合计=不含税+税额")
            _mark_resolved(conflicts, "tax_amount", "金额关系验证: OCR 价税合计=不含税+税额")
        elif llm_amount_ok and not ocr_amount_ok:
            # LLM金额关系正确，OCR错误 → 全部采用LLM金额
            confirmed["total_with_tax"] = llm_total_raw
            confirmed["amount"] = llm_fields.get("amount")
            confirmed["tax_amount"] = llm_fields.get("tax_amount")
            logger.info(f"金额验证: LLM通过交叉验证, OCR未通过 → 全部采用LLM金额")
            _mark_resolved(conflicts, "total_with_tax", "金额关系验证: LLM 价税合计=不含税+税额")
            _mark_resolved(conflicts, "amount", "金额关系验证: LLM 价税合计=不含税+税额")
            _mark_resolved(conflicts, "tax_amount", "金额关系验证: LLM 价税合计=不含税+税额")
        # else: 双方都通过或都不通过，保持默认择优结果

    # 规则3: 购买方 ≠ 销售方
    # 如果 OCR 的 buyer=seller（错误），但 LLM 的 buyer≠seller → 用 LLM 的 seller
    ocr_buyer = normalize_value(ocr_fields.get("buyer_name"))
    ocr_seller = normalize_value(ocr_fields.get("seller_name"))
    llm_buyer = normalize_value(llm_fields.get("buyer_name"))
    llm_seller = normalize_value(llm_fields.get("seller_name"))

    if ocr_buyer and ocr_seller and ocr_buyer == ocr_seller:
        # OCR 混淆了购买方和销售方
        if llm_seller and llm_seller != ocr_seller:
            confirmed["seller_name"] = llm_fields.get("seller_name")
            logger.info(
                f"购买方≠销售方验证: OCR混淆了买卖双方(都是{ocr_buyer}), "
                f"LLM的seller({llm_seller})不同 → 采用LLM的seller"
            )
            _mark_resolved(conflicts, "seller_name", "买卖方不同验证: OCR混淆了买卖双方")

    # 规则4: 项目名称完整性 — 优先更完整的值
    ocr_item = ocr_fields.get("item_name")
    llm_item = llm_fields.get("item_name")
    if ocr_item and llm_item and normalize_value(ocr_item) != normalize_value(llm_item):
        # 如果一个值是另一个值的子串，取更完整的
        ocr_norm = normalize_value(ocr_item)
        llm_norm = normalize_value(llm_item)
        if ocr_norm and llm_norm:
            if ocr_norm in llm_norm and len(llm_norm) > len(ocr_norm):
                confirmed["item_name"] = llm_item
                logger.info(f"项目名称完整性: LLM({llm_item})包含OCR({ocr_item}) → 采用LLM更完整值")
                _mark_resolved(conflicts, "item_name", "完整性验证: LLM值更完整")
            elif llm_norm in ocr_norm and len(ocr_norm) > len(llm_norm):
                confirmed["item_name"] = ocr_item
                logger.info(f"项目名称完整性: OCR({ocr_item})包含LLM({llm_item}) → 采用OCR更完整值")
                _mark_resolved(conflicts, "item_name", "完整性验证: OCR值更完整")

    return confirmed


def get_best_value(field: str, ocr_val: Any, llm_val: Any) -> Any:
    """对特定冲突字段选择最佳值

    策略:
    - 数字/编码类字段 → 优先 OCR (逐字符识别精度高)
    - 文本类字段 → 优先 LLM (理解上下文, 不混淆买卖双方)
    - 其他字段 → 优先 OCR
    """
    if field in NUMERIC_FIELDS:
        return ocr_val or llm_val
    if field in TEXT_FIELDS:
        return llm_val or ocr_val
    return ocr_val or llm_val


def _extract_field_from_raw_text(field: str, raw_text: str) -> str | None:
    """从 OCR/LLM 原始文本中正则提取指定字段值

    适用于双源均为空时的回退补齐。支持:
      - seller_name: "销售方 ... 名称：xxx"
      - buyer_name: "购买方 ... 名称：xxx"
      - seller_tax_id: "统一社会信用代码/纳税人识别号:xxx"（在销售方信息段）
      - buyer_tax_id: 同上（在购买方信息段）
      - item_name: 项目名称行
      - tax_rate: 税率/征收率行
      - issue_date: 开票日期行
    """
    if not raw_text:
        return None

    flat = raw_text.replace("\n", " ").replace("\r", " ")
    flat = re.sub(r"\s+", " ", flat)

    if field == "seller_name":
        # 模式: 销售方信息 ... 名称：xxx（在"统一社会信用代码"之前）
        m = re.search(r"销售方信息.*?名称[：:]\s*([^\s]+?)(?:\s|统一社会|$)", flat)
        if not m:
            # 宽松: "名称：" 在销售方段附近
            m = re.search(r"名称[：:]\s*(.+?)\s*统一社会信用代码", flat)
            if m:
                # 可能有多个"名称"，取销售方的（第二个）
                names = re.findall(r"名称[：:]\s*([^\s]+?)(?:\s|统一社会|$)", flat)
                if len(names) >= 2:
                    return names[1].strip()
        if m:
            return m.group(1).strip()

    elif field == "buyer_name":
        # 模式: 购买方信息 ... 名称：xxx（在"统一社会信用代码"之前）
        names = re.findall(r"名称[：:]\s*([^\s]+?)(?:\s|统一社会|$)", flat)
        if len(names) >= 1:
            return names[0].strip()

    elif field == "seller_tax_id":
        # 模式: 统一社会信用代码/纳税人识别号:91xxxxxxxx（在销售方段）
        tax_ids = re.findall(r"统一社会信用代码/纳税人识别号[：:]\s*(\w+)", flat)
        if len(tax_ids) >= 2:
            return tax_ids[1].strip()

    elif field == "buyer_tax_id":
        tax_ids = re.findall(r"统一社会信用代码/纳税人识别号[：:]\s*(\w+)", flat)
        if len(tax_ids) >= 1:
            return tax_ids[0].strip()

    elif field == "item_name":
        # 模式: 项目名称 ... *快递服务*收派服务费
        m = re.search(r"\*[^\s*]+\*[^\s]+", flat)
        if m:
            return m.group(0).strip()

    elif field == "tax_rate":
        # 模式: 税率 6% 或 6%
        m = re.search(r"(\d+%)\s", flat)
        if m:
            return m.group(1)

    elif field == "issue_date":
        m = re.search(r"开票日期[：:]\s*(\d{4}年\d{1,2}月\d{1,2}日)", flat)
        if m:
            date_str = m.group(1)
            # 转换为 YYYY-MM-DD
            dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
            if dm:
                return f"{dm.group(1)}-{dm.group(2).zfill(2)}-{dm.group(3).zfill(2)}"

    return None


def _fill_from_raw_text(confirmed: dict, raw_text: str, conflicts: list) -> dict:
    """双源均为空的字段，尝试从 OCR 原始文本正则提取补齐

    仅补齐 confirmed 中值为 None 的字段。
    """
    if not raw_text:
        return confirmed

    fillable_fields = [
        "seller_name", "buyer_name", "seller_tax_id", "buyer_tax_id",
        "item_name", "tax_rate", "issue_date",
    ]

    filled_any = False
    for field in fillable_fields:
        if confirmed.get(field) is not None:
            continue  # 已有值，不需要补齐
        val = _extract_field_from_raw_text(field, raw_text)
        if val:
            confirmed[field] = val
            filled_any = True
            logger.info(f"原始文本字段补齐: {field}={val}")

    if filled_any:
        # 补齐的字段标记为已解决（如果之前有冲突的话）
        for c in conflicts:
            if c.get("field") in fillable_fields and c.get("status") != "RESOLVED":
                if confirmed.get(c["field"]) is not None:
                    c["status"] = "RESOLVED"
                    c["resolved_by"] = "raw_text"
                    c["resolved_reason"] = "原始文本正则提取补齐"

    return confirmed


def compare_results(ocr_fields: dict, llm_fields: dict) -> dict:
    """对比 OCR 和 LLM 的提取结果（增强版）

    改进:
    1. 冲突时按字段类型择优 (get_best_value)
    2. 交叉验证规则进一步修正冲突选择
    3. 金额关系验证标记

    Returns:
        {
            "confirmed_fields": dict,   # 确认的字段值
            "conflicts": list,          # 冲突字段列表
            "matched_count": int,
            "total_fields": int,
            "confidence": float,        # 0.0 - 1.0
        }
    """
    confirmed = {}
    conflicts = []
    matched = 0
    evaluated_fields = 0  # 至少一源有值的字段数（排除双空）

    for field in COMPARABLE_FIELDS:
        ocr_val = normalize_value(ocr_fields.get(field))
        llm_val = normalize_value(llm_fields.get(field))

        if ocr_val and llm_val:
            evaluated_fields += 1
            if ocr_val == llm_val:
                # 两源一致 → 自动确认
                confirmed[field] = ocr_fields.get(field)
                matched += 1
            else:
                # 冲突 → 按字段类型择优
                best = get_best_value(field, ocr_fields.get(field), llm_fields.get(field))
                confirmed[field] = best
                default_resolver = "ocr" if field in NUMERIC_FIELDS else "llm" if field in TEXT_FIELDS else "ocr"
                conflicts.append({
                    "field": field,
                    "ocr_value": ocr_fields.get(field),
                    "llm_value": llm_fields.get(field),
                    "status": "RESOLVED",
                    "resolved_by": default_resolver,
                    "resolved_reason": "字段类型择优: " + ("数字/编码类优先OCR" if field in NUMERIC_FIELDS else "文本类优先LLM" if field in TEXT_FIELDS else "默认优先OCR"),
                })
        elif ocr_val:
            evaluated_fields += 1
            confirmed[field] = ocr_fields.get(field)
            matched += 1
        elif llm_val:
            evaluated_fields += 1
            confirmed[field] = llm_fields.get(field)
            matched += 1
        else:
            # 双源均为空，不计入评估字段
            confirmed[field] = None

    # 交叉验证 — 利用业务规则进一步修正冲突选择
    confirmed = _apply_cross_validation_rules(confirmed, ocr_fields, llm_fields, conflicts)

    # 金额关系验证（传入原始文本用于正则提取）
    raw_text = ocr_fields.get("_raw_text", "") or llm_fields.get("_raw_text", "")
    confirmed = _cross_validate_amounts(confirmed, ocr_fields, llm_fields, conflicts, raw_text=raw_text)

    # 双源均为空的字段，尝试从 OCR 原始文本正则提取补齐
    confirmed = _fill_from_raw_text(confirmed, raw_text, conflicts)

    # 购买方≠销售方验证
    confirmed = _validate_buyer_seller(confirmed, ocr_fields, llm_fields, conflicts)

    # 如果交叉验证发现了问题，增加冲突标记
    if confirmed.pop("_amount_validation_failed", False):
        conflicts.append({
            "field": "amount_relation",
            "ocr_value": f"amount+tax vs total",
            "llm_value": f"amount+tax vs total",
            "status": "VALIDATION_WARNING",
            "resolved_by": "cross_validation",
        })

    if confirmed.pop("_buyer_seller_same", False):
        # 无法自动纠正的买卖方相同 → CONFLICT 触发人工复核
        conflicts.append({
            "field": "buyer_seller_same",
            "ocr_value": confirmed.get("buyer_name"),
            "llm_value": confirmed.get("seller_name"),
            "status": "CONFLICT",
            "resolved_by": "cross_validation",
            "resolved_reason": "买卖方相同且无法自动纠正，需人工确认销售方",
        })

    # 仅统计有值的字段数作为分母（双空字段不参与置信度计算）
    total = evaluated_fields if evaluated_fields > 0 else len(COMPARABLE_FIELDS)
    # 统计各类冲突状态
    unresolved_conflicts = [c for c in conflicts if c["status"] == "CONFLICT"]
    resolved_conflicts = [c for c in conflicts if c["status"] == "RESOLVED"]
    # 已解决冲突视为自动确认，计入置信度
    confidence = (matched + len(resolved_conflicts)) / total if total > 0 else 0.0

    logger.info(
        f"Dual-source comparison: {matched}/{total} matched, "
        f"{len(resolved_conflicts)} resolved, {len(unresolved_conflicts)} unresolved, "
        f"confidence={confidence:.2%} (evaluated {evaluated_fields}/{len(COMPARABLE_FIELDS)} fields)"
    )

    return {
        "confirmed_fields": confirmed,
        "conflicts": conflicts,
        "matched_count": matched,
        "total_fields": total,
        "confidence": round(confidence, 4),
    }
