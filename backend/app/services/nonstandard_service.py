"""非标准票据处理服务

纯VLM视觉分析链路：类型确认 → 结构化提取 → 语义校验 → 风险评估 → 语义去重
不接入OCR或第三方验真API。
"""

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import (
    Invoice, LlmResult, InvoiceStatus, ReceiptType,
    VerifyStatus, DuplicateStatus,
)
from app.prompts.nonstandard_prompts import (
    NONSTANDARD_RECEIPT_TYPES,
    EXTRACT_PROMPT_MAP,
    NONSTANDARD_CONSISTENCY_CHECK_PROMPT,
    NONSTANDARD_CLASSIFY_RULES,
)
from app.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


# ===================== 语义校验器 =====================

class ValidationIssue:
    def __init__(self, field: str, level: str, message: str):
        self.field = field
        self.level = level  # ERROR / WARNING
        self.message = message


class ValidationResult:
    def __init__(self, is_valid: bool, issues: list, risk_level: str):
        self.is_valid = is_valid
        self.issues = issues
        self.risk_level = risk_level

    @property
    def has_errors(self):
        return any(i.level == "ERROR" for i in self.issues)

    @property
    def warning_count(self):
        return sum(1 for i in self.issues if i.level == "WARNING")


class NonStandardValidator:
    """非标准票据语义校验器"""

    CRITICAL_FIELDS = {
        "支付截图": ["amount", "payer_name", "payee_name"],
        "收据": ["amount", "payee_name"],
        "交易流水单": ["amount", "transaction_date", "counterpart_name"],
    }

    def validate(self, fields: dict, receipt_type: str) -> ValidationResult:
        issues = []

        # 1. 关键字段完整性
        critical = self.CRITICAL_FIELDS.get(receipt_type, ["amount"])
        for f in critical:
            if not fields.get(f):
                issues.append(ValidationIssue(
                    field=f, level="WARNING", message=f"关键信息缺失: {f}"
                ))

        # 2. 金额合理性
        amount = fields.get("amount") or fields.get("total_with_tax")
        if amount:
            try:
                amt = float(str(amount).replace(",", "").replace("￥", "").replace("¥", ""))
                if amt <= 0:
                    issues.append(ValidationIssue(
                        field="amount", level="ERROR", message="金额无效：非正数"
                    ))
                elif amt > 100000:
                    issues.append(ValidationIssue(
                        field="amount", level="WARNING",
                        message=f"金额较大({amt}元)，建议人工复核"
                    ))
            except ValueError:
                issues.append(ValidationIssue(
                    field="amount", level="ERROR", message=f"金额格式异常: {amount}"
                ))
        else:
            issues.append(ValidationIssue(
                field="amount", level="ERROR", message="金额缺失"
            ))

        # 3. 大小写金额一致性（收据类）
        amt_cap = fields.get("amount_capital")
        if amt_cap and amount:
            # 简单校验：如果大写包含数字，尝试比对
            cap_match = _extract_amount_from_chinese(amt_cap)
            if cap_match:
                try:
                    amt_val = float(str(amount).replace(",", ""))
                    if abs(cap_match - amt_val) > 0.01:
                        issues.append(ValidationIssue(
                            field="amount", level="ERROR",
                            message=f"大小写金额不一致: 大写={cap_match}, 小写={amt_val}"
                        ))
                except ValueError:
                    pass

        # 4. 日期合理性
        date_str = fields.get("issue_date") or fields.get("transaction_time") or fields.get("transaction_date")
        if date_str:
            try:
                # 尝试解析日期
                date_part = str(date_str)[:10]  # 取 YYYY-MM-DD 部分
                d = datetime.strptime(date_part, "%Y-%m-%d")
                if d > datetime.now():
                    issues.append(ValidationIssue(
                        field="date", level="ERROR",
                        message="交易日期不能晚于当前日期"
                    ))
            except ValueError:
                issues.append(ValidationIssue(
                    field="date", level="WARNING",
                    message=f"日期格式异常: {date_str}"
                ))

        # 5. 交易方矛盾
        payer = fields.get("payer_name") or fields.get("buyer_name")
        payee = fields.get("payee_name") or fields.get("seller_name") or fields.get("counterpart_name")
        if payer and payee and str(payer).strip() == str(payee).strip() and str(payer).strip():
            issues.append(ValidationIssue(
                field="payer/payee", level="WARNING",
                message="付款方与收款方相同，请确认"
            ))

        # 计算风险等级
        error_count = sum(1 for i in issues if i.level == "ERROR")
        warning_count = sum(1 for i in issues if i.level == "WARNING")
        if error_count > 0:
            risk_level = "high"
        elif warning_count >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        is_valid = error_count == 0
        return ValidationResult(is_valid=is_valid, issues=issues, risk_level=risk_level)


# ===================== 语义去重 =====================

class SemanticDeduplicator:
    """基于VLM提取结果的语义去重（含交易号精确查重 + 图像哈希查重）"""

    async def check_duplicate(
        self, fields: dict, user_id: str, db: AsyncSession,
        file_data: bytes = None, file_type: str = "",
        current_invoice_id: int = None,
    ) -> dict:
        """返回 {"is_duplicate": bool, "confidence": float, "detail": str}"""

        # Level 1: 交易号/收据号精确查重（全用户）
        txn_id = fields.get("transaction_id") or fields.get("receipt_number")
        if txn_id:
            conditions = [
                Invoice.invoice_number == str(txn_id),
            ]
            if current_invoice_id:
                conditions.append(Invoice.id != current_invoice_id)
            result = await db.execute(select(Invoice).where(*conditions))
            exact_match = result.scalars().first()
            if exact_match:
                return {
                    "is_duplicate": True,
                    "confidence": 1.0,
                    "detail": f"交易号/收据号 {txn_id} 与发票#{exact_match.id}完全一致",
                }

        # Level 2: 语义匹配（全用户，不限同一用户）
        amount = fields.get("amount") or fields.get("total_with_tax")
        if not amount:
            return {"is_duplicate": False, "confidence": 0, "detail": "无金额可比较"}

        try:
            amt = float(str(amount).replace(",", "").replace("￥", "").replace("¥", ""))
        except ValueError:
            return {"is_duplicate": False, "confidence": 0, "detail": "金额无法解析"}

        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=90)
        result = await db.execute(
            select(Invoice).where(
                Invoice.receipt_type.in_([
                    ReceiptType.receipt,
                    ReceiptType.payment_screenshot,
                    ReceiptType.bank_statement,
                ]),
                Invoice.is_nonstandard == True,
                Invoice.created_at >= cutoff,
            )
        )
        existing = list(result.scalars().all())

        for inv in existing:
            # 排除自身
            if current_invoice_id and inv.id == current_invoice_id:
                continue
            score = 0
            # 金额匹配（±0.01容差）
            if inv.total_with_tax:
                try:
                    inv_amt = float(str(inv.total_with_tax).replace(",", ""))
                    if abs(amt - inv_amt) < 0.01:
                        score += 40
                except ValueError:
                    pass
            # 日期匹配
            date_str = fields.get("issue_date") or fields.get("transaction_time") or fields.get("transaction_date")
            date_val = str(date_str)[:10] if date_str else None
            if date_val and inv.issue_date and date_val == inv.issue_date:
                score += 25
            # 收款方匹配
            payee = fields.get("payee_name") or fields.get("seller_name") or fields.get("counterpart_name")
            if payee and inv.seller_name and str(payee).strip() == str(inv.seller_name).strip():
                score += 20
            # 用途匹配
            purpose = fields.get("purpose") or fields.get("remark")
            if purpose and inv.item_name and _text_similarity(str(purpose), str(inv.item_name)) > 0.8:
                score += 15

            if score >= 70:
                return {
                    "is_duplicate": True,
                    "confidence": score / 100,
                    "detail": f"语义相似度{score}分，与发票#{inv.id}匹配",
                }

        # Level 3: 图像哈希查重（pHash）
        if file_data:
            from app.services.duplicate_checker import compute_phash, hamming_distance, PHASH_HAMMING_THRESHOLD
            img_hash = compute_phash(file_data, file_type)
            if img_hash:
                # 查询所有有 image_hash 的发票
                hash_query = select(Invoice).where(
                    Invoice.image_hash.isnot(None),
                )
                if current_invoice_id:
                    hash_query = hash_query.where(Invoice.id != current_invoice_id)
                hash_result = await db.execute(hash_query)
                for inv in hash_result.scalars().all():
                    if inv.image_hash and hamming_distance(img_hash, inv.image_hash) <= PHASH_HAMMING_THRESHOLD:
                        return {
                            "is_duplicate": True,
                            "confidence": 0.95,
                            "detail": f"图像哈希匹配，与发票#{inv.id}相似(pHash距离={hamming_distance(img_hash, inv.image_hash)})",
                        }

        return {"is_duplicate": False, "confidence": 0, "detail": "无重复"}


# ===================== 风险评估 =====================

class NonStandardRiskAssessor:
    """非标准票据风险评估"""

    async def assess(
        self, fields: dict, receipt_type: str, user_id: str,
        db: AsyncSession, vlm_consistency: dict = None,
    ) -> dict:
        """返回 {"risk_level": str, "risk_factors": list}"""
        factors = []

        # 1. VLM置信度（由外部传入时使用）
        # 2. 金额为整数且>=1000元
        amount = fields.get("amount") or fields.get("total_with_tax")
        if amount:
            try:
                amt = float(str(amount).replace(",", ""))
                if amt >= 1000 and amt == int(amt):
                    factors.append("金额为整数且>=1000元")
            except ValueError:
                pass

        # 3. 关键信息大面积缺失
        all_values = [v for k, v in fields.items() if v is not None and v != "" and k != "currency"]
        null_count = sum(1 for k, v in fields.items() if v is None or v == "")
        total_count = len(fields)
        if total_count > 0 and null_count / total_count > 0.5:
            factors.append("关键信息大面积缺失(>50%字段为null)")

        # 4. 收据无印章且为手写
        if receipt_type == "收据":
            if fields.get("seal_present") is False and fields.get("is_handwritten") is True:
                factors.append("手写收据且无印章")

        # 5. 同一收款方30天内出现3次以上
        payee = fields.get("payee_name") or fields.get("seller_name") or fields.get("counterpart_name")
        if payee and db:
            try:
                from datetime import timedelta
                cutoff = datetime.now() - timedelta(days=30)
                result = await db.execute(
                    select(Invoice).where(
                        Invoice.seller_name == str(payee).strip(),
                        Invoice.created_at >= cutoff,
                    )
                )
                rows = list(result.scalars().all())
                if len(rows) >= 3:
                    factors.append(f"同一收款方30天内出现{len(rows)}次")
            except Exception:
                pass

        # 6. VLM语义校验结果
        if vlm_consistency:
            # VLM发现可疑特征
            suspicious = vlm_consistency.get("suspicious_features") or []
            if suspicious:
                factors.append(f"VLM检测到可疑特征: {'; '.join(suspicious)}")
            # VLM发现矛盾
            contradictions = vlm_consistency.get("contradictions") or []
            if contradictions:
                factors.append(f"VLM发现矛盾: {'; '.join(contradictions)}")
            # VLM判定高风险（独立计为1个因素）
            if vlm_consistency.get("risk_level") == "high":
                factors.append("VLM语义校验判定高风险")

        # 确定风险等级
        if len(factors) >= 2:
            risk_level = "high"
        elif len(factors) == 1:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {"risk_level": risk_level, "risk_factors": factors}


# ===================== 非标分类 =====================

def classify_nonstandard(fields: dict, receipt_type: str, user_description: str = "") -> dict:
    """规则驱动的非标票据分类，返回 {category, subcategory, source, confidence}"""
    rules = NONSTANDARD_CLASSIFY_RULES.get(receipt_type, {})
    text_source = " ".join([
        str(fields.get("purpose") or ""),
        str(fields.get("payee_name") or fields.get("seller_name") or fields.get("counterpart_name") or ""),
        str(fields.get("remark") or ""),
        user_description,
    ]).lower()

    for subcategory, keywords in rules.items():
        for kw in keywords:
            if kw.lower() in text_source:
                # 根据子类别推断大类
                category = _subcategory_to_category(subcategory)
                return {
                    "category": category,
                    "subcategory": subcategory,
                    "source": "rule",
                    "confidence": 0.8,
                }

    # 规则未匹配，返回默认
    return {
        "category": "company",
        "subcategory": "运营费",
        "source": "rule",
        "confidence": 0.3,
    }


# ===================== 核心处理服务 =====================

class NonStandardReceiptService:
    """非标准票据处理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_service()
        self.validator = NonStandardValidator()
        self.deduplicator = SemanticDeduplicator()
        self.risk_assessor = NonStandardRiskAssessor()

    async def process(self, invoice: Invoice, file_data: bytes, file_type: str, user_description: str = "") -> Invoice:
        """处理非标准票据完整链路"""

        mime_map = {
            "pdf": "application/pdf",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/jpeg",
            "bmp": "image/jpeg",
            "webp": "image/jpeg",
        }
        mime = mime_map.get(file_type, "image/png")

        receipt_type = invoice.receipt_type.value if invoice.receipt_type else "支付截图"
        extract_prompt = EXTRACT_PROMPT_MAP.get(receipt_type, EXTRACT_PROMPT_MAP["支付截图"])

        # 阶段1+2: 结构化字段提取（合并类型确认与提取，减少VLM调用）
        logger.info(f"Invoice #{invoice.id} nonstandard: VLM extraction starting (type={receipt_type})")
        extract_result = await self._vlm_extract(file_data, mime, extract_prompt)
        fields = extract_result or {}

        if not fields:
            # VLM完全失败
            logger.warning(f"Invoice #{invoice.id} nonstandard: VLM extraction returned empty")
            invoice.vlm_confidence = 0
            invoice.risk_level = "high"
            invoice.verify_status = VerifyStatus.unable
            invoice.verify_message = "VLM识别失败，请人工审核"
            invoice.status = InvoiceStatus.reviewing
            invoice.is_nonstandard = True
            invoice.processing_pipeline = "nonstandard"
            await self.db.commit()
            return invoice

        # 存储VLM原始结果
        invoice.vlm_raw_result = fields
        vlm_confidence = fields.pop("_confidence", None)
        if vlm_confidence is None:
            # 估算置信度：非null字段占比
            non_null = sum(1 for v in fields.values() if v is not None)
            total = max(len(fields), 1)
            vlm_confidence = non_null / total
        invoice.vlm_confidence = round(vlm_confidence, 2)

        # 阶段3: 语义一致性校验
        consistency = await self._vlm_consistency_check(fields, receipt_type)
        if consistency:
            # 用VLM校验结果覆盖/补充置信度
            if consistency.get("overall_confidence") is not None:
                invoice.vlm_confidence = round(
                    (invoice.vlm_confidence + consistency["overall_confidence"]) / 2, 2
                )
            # 将VLM校验结果合并到raw_result中
            invoice.vlm_raw_result = {**fields, "_consistency_check": consistency}

        # 映射字段到Invoice
        self._map_to_invoice(invoice, fields, receipt_type)

        # 语义校验
        validation = self.validator.validate(fields, receipt_type)
        logger.info(
            f"Invoice #{invoice.id} nonstandard: validation "
            f"valid={validation.is_valid}, issues={len(validation.issues)}, "
            f"risk={validation.risk_level}"
        )

        # 设置验真状态
        invoice.verify_status = VerifyStatus.unable
        invoice.verify_message = "非标准票据，不支持在线验真"

        # 风险评估（传入VLM语义校验结果）
        risk_result = await self.risk_assessor.assess(
            fields, receipt_type, invoice.user_id, self.db, consistency
        )
        risk_level = risk_result["risk_level"]
        # 如果语义校验风险更高，采用更高的等级
        risk_levels = {"low": 0, "medium": 1, "high": 2}
        if risk_levels.get(validation.risk_level, 0) > risk_levels.get(risk_level, 0):
            risk_level = validation.risk_level
        invoice.risk_level = risk_level

        # 状态决定
        if risk_level == "low" and validation.is_valid:
            invoice.status = InvoiceStatus.reviewed
        else:
            invoice.status = InvoiceStatus.reviewing

        # 去重（三级：交易号精确 → 语义匹配 → 图像哈希）
        dup_result = await self.deduplicator.check_duplicate(
            fields, invoice.user_id, self.db,
            file_data=file_data, file_type=file_type,
            current_invoice_id=invoice.id,
        )
        invoice.duplicate_status = (
            DuplicateStatus.duplicate if dup_result["is_duplicate"]
            else DuplicateStatus.unique
        )
        if dup_result["is_duplicate"]:
            logger.info(f"Invoice #{invoice.id} nonstandard: duplicate detected - {dup_result['detail']}")

        # 计算并存储图像哈希（无论是否判重都存储，供后续比对）
        if not invoice.image_hash:
            from app.services.duplicate_checker import compute_phash
            img_hash = compute_phash(file_data, file_type)
            if img_hash:
                invoice.image_hash = img_hash

        # 分类
        classify_result = classify_nonstandard(fields, receipt_type, user_description)
        invoice.fee_category = classify_result["category"]
        invoice.fee_subcategory = classify_result["subcategory"]
        invoice.classify_source = classify_result["source"]
        invoice.classify_confidence = classify_result["confidence"]

        # 项目归属（复用现有逻辑）
        from app.services.project_matcher import ProjectMatcher
        project_matcher = ProjectMatcher(self.db)
        project_result = await project_matcher.match_project(
            {"seller_name": invoice.seller_name},
            user_description,
            invoice.user_id,
        )
        invoice.project_id = project_result.get("project_id")
        invoice.project_match_source = project_result.get("source")

        # 标记非标票据
        invoice.is_nonstandard = True
        invoice.processing_pipeline = "nonstandard"

        # 保存LlmResult
        self.db.add(LlmResult(
            invoice_id=invoice.id,
            provider="vlm-nonstandard",
            model=None,
            extracted_fields=fields,
            raw_response=json.dumps(extract_result or {}, ensure_ascii=False) if extract_result else None,
        ))

        await self.db.commit()
        await self.db.refresh(invoice)

        logger.info(
            f"Invoice #{invoice.id} nonstandard processed: "
            f"vlm_conf={invoice.vlm_confidence:.2f}, "
            f"risk={invoice.risk_level}, "
            f"category={invoice.fee_subcategory}, "
            f"duplicate={invoice.duplicate_status.value}"
        )
        return invoice

    async def _vlm_extract(self, file_data: bytes, mime: str, prompt: str) -> Optional[dict]:
        """调用VLM进行结构化提取（含重试+JSON修复）"""
        import base64
        b64_image = base64.b64encode(file_data).decode()

        from app.config import settings
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.llm.client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": "你是专业的财务票据分析助手，严格按照JSON格式返回结果。"},
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{mime};base64,{b64_image}"
                            }}
                        ]}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=4000,
                )

                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                if not content:
                    logger.warning(f"VLM extract attempt {attempt}: empty content, finish_reason={finish_reason}")
                    if attempt < max_attempts:
                        continue
                    return None

                # 尝试直接解析
                try:
                    return json.loads(content)
                except json.JSONDecodeError as je:
                    logger.warning(
                        f"VLM extract attempt {attempt}: JSON parse failed: {je}, "
                        f"finish_reason={finish_reason}, content_len={len(content)}"
                    )
                    # 尝试修复截断的JSON
                    repaired = self._repair_json(content)
                    if repaired is not None:
                        logger.info(f"VLM extract attempt {attempt}: JSON repaired successfully")
                        return repaired
                    # 记录原始响应尾巴用于调试
                    logger.error(
                        f"VLM extract raw tail (last 300 chars): ...{content[-300:]}"
                    )
                    if attempt < max_attempts:
                        continue
                    return None

            except Exception as e:
                logger.error(f"VLM extract attempt {attempt} exception: {e}")
                if attempt < max_attempts:
                    continue
                return None

        return None

    @staticmethod
    def _repair_json(text: str) -> Optional[dict]:
        """尝试修复截断/不完整的JSON"""
        text = text.strip()

        # 移除可能的markdown包裹
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.strip().startswith("```"))

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 找到第一个 { 和最后一个 }
        first_brace = text.find("{")
        if first_brace == -1:
            return None
        last_brace = text.rfind("}")
        if last_brace > first_brace:
            candidate = text[first_brace:last_brace + 1]
        else:
            candidate = text[first_brace:]

        # 尝试直接解析截取的部分
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # 尝试逐字符截断修复：从尾部往前找到最后一个完整字段边界
        for i in range(len(candidate) - 1, 0, -1):
            ch = candidate[i]
            if ch == "," or ch == "}":
                fragment = candidate[:i]
                # 补全右括号
                open_count = fragment.count("{") - fragment.count("}")
                fragment = fragment.rstrip().rstrip(",")
                fragment = fragment + "}" * max(open_count, 1)
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError:
                    continue

        return None

    async def _vlm_consistency_check(self, fields: dict, receipt_type: str) -> Optional[dict]:
        """调用VLM进行语义一致性校验（含重试+JSON修复）"""
        from app.config import settings
        prompt = NONSTANDARD_CONSISTENCY_CHECK_PROMPT.format(
            receipt_type=receipt_type,
            extracted_fields=json.dumps(fields, ensure_ascii=False),
            current_date=datetime.now().strftime("%Y-%m-%d"),
        )

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.llm.client.chat.completions.create(
                    model=settings.text_model,  # 文本模型即可
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=1500,
                )
                content = response.choices[0].message.content
                if not content:
                    if attempt < max_attempts:
                        continue
                    return None
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    repaired = self._repair_json(content)
                    if repaired is not None:
                        return repaired
                    if attempt < max_attempts:
                        continue
                    return None
            except Exception as e:
                logger.error(f"VLM consistency check attempt {attempt} failed: {e}")
                if attempt < max_attempts:
                    continue
                return None
        return None

    def _map_to_invoice(self, invoice: Invoice, fields: dict, receipt_type: str):
        """将VLM提取的字段映射到Invoice模型"""
        # 通用映射
        amount = fields.get("amount") or fields.get("total_with_tax")
        if amount:
            invoice.total_with_tax = str(amount)

        # 日期
        date_val = fields.get("transaction_time") or fields.get("issue_date") or fields.get("transaction_date")
        if date_val:
            # 提取 YYYY-MM-DD 部分
            invoice.issue_date = str(date_val)[:10]

        # 交易方
        payer = fields.get("payer_name") or fields.get("buyer_name")
        if payer:
            invoice.buyer_name = str(payer)

        payee = fields.get("payee_name") or fields.get("seller_name") or fields.get("merchant_name")
        if payee:
            invoice.seller_name = str(payee)

        # 交易单号/收据号
        txn_id = fields.get("transaction_id") or fields.get("receipt_number")
        if txn_id:
            invoice.invoice_number = str(txn_id)

        # 用途
        purpose = fields.get("purpose") or fields.get("remark")
        if purpose:
            invoice.item_name = str(purpose)

        # 扩展信息存入receipt_detail
        detail = {}
        platform_fields = [
            "payment_platform", "payment_method", "payer_account", "payee_account",
            "currency", "transaction_status", "merchant_name", "bank_name",
            "account_name", "account_number", "transaction_type", "balance",
            "counterpart_name", "counterpart_account",
            "receipt_title", "amount_capital", "receipt_method",
            "issuer_signature", "seal_present", "is_handwritten",
        ]
        for f in platform_fields:
            if fields.get(f) is not None:
                detail[f] = fields[f]
        if detail:
            invoice.receipt_detail = detail


# ===================== 工具函数 =====================

def _extract_amount_from_chinese(chinese: str) -> Optional[float]:
    """从中文大写金额中提取数字（简单实现）"""
    mapping = {"零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
               "陆": 6, "柒": 7, "捌": 8, "玖": 9,
               "拾": 10, "佰": 100, "仟": 1000, "万": 10000,
               "亿": 100000000, "元": 1, "整": 1, "角": 0.1, "分": 0.01}
    # 简单匹配：如果大写金额中包含阿拉伯数字，直接提取
    import re
    nums = re.findall(r'\d+\.?\d*', chinese)
    if nums:
        return float(nums[0])
    return None


def _text_similarity(a: str, b: str) -> float:
    """简单文本相似度（Jaccard）"""
    if not a or not b:
        return 0.0
    set_a = set(a.lower())
    set_b = set(b.lower())
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _subcategory_to_category(subcategory: str) -> str:
    """子类别到大类映射 — 与标准分类器 RULES 对齐"""
    personal_subs = {"差旅-交通", "差旅-住宿", "差旅-餐饮", "通讯费", "培训费", "补贴"}
    if subcategory in personal_subs:
        return "personal"
    return "company"
