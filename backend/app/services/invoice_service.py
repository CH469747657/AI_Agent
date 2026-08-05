"""核心编排服务 — 串联完整处理链路

处理流程:
  接收票据 → [并行] OCR识别 + LLM解析 → 双源比对 → 费用分类 → 项目归属 → 查重 → 保存

参考: Invoice-Manager invoice_service.py (并行线程池 + 双源比对)
"""

import os
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import (
    Invoice, OcrResult, LlmResult,
    InvoiceStatus, ReceiptType, VerifyStatus, DuplicateStatus,
)
from app.config import settings
from app.services.ocr_service import get_ocr_service, get_ocr_executor
from app.services.llm_service import get_llm_service, get_llm_executor
from app.services.diff_engine import compare_results
from app.services.classifier import FeeClassifier
from app.services.project_matcher import ProjectMatcher
from app.services.duplicate_checker import DuplicateChecker
from app.services.verify_service import get_verify_service
from app.services.verify_cross_check import cross_check_verified_fields
from app.services.invoice_prevalidator import precheck_invoice
from app.prompts.nonstandard_prompts import NONSTANDARD_RECEIPT_TYPES

logger = logging.getLogger(__name__)


class InvoiceService:
    """发票处理核心编排服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ocr = get_ocr_service()
        self.llm = get_llm_service()
        self.classifier = FeeClassifier()

    async def process_upload(
        self,
        file_data: bytes,
        file_type: str,
        receipt_type: str,
        user_id: str,
        user_description: str = "",
    ) -> Invoice:
        """完整处理一张票据：上传 → 识别 → 分类 → 查重 → 保存"""

        # 1. 保存原始文件
        filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file_type}"
        file_path = os.path.join(settings.upload_dir, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(file_data)

        # 2. 创建发票记录
        mime_map = {
            "pdf": "application/pdf",
            "ofd": "application/ofd",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }
        invoice = Invoice(
            receipt_type=ReceiptType(receipt_type),
            file_path=file_path,
            file_type=file_type,
            user_id=user_id,
            user_description=user_description,
            status=InvoiceStatus.processing,
        )
        self.db.add(invoice)
        await self.db.commit()
        await self.db.refresh(invoice)

        logger.info(f"Invoice #{invoice.id} created, starting processing...")

        try:
            # 2.5 非标票据分流 — 走纯VLM链路，不走OCR+验真
            receipt_type_value = invoice.receipt_type.value if invoice.receipt_type else ""
            if receipt_type_value in NONSTANDARD_RECEIPT_TYPES:
                logger.info(
                    f"Invoice #{invoice.id} detected as nonstandard receipt "
                    f"(type={receipt_type_value}), routing to VLM pipeline"
                )
                from app.services.nonstandard_service import NonStandardReceiptService
                nonstandard_svc = NonStandardReceiptService(self.db)
                invoice = await nonstandard_svc.process(
                    invoice=invoice,
                    file_data=file_data,
                    file_type=file_type,
                    user_description=user_description,
                )
                return invoice

            # 3. 并行执行 OCR + LLM
            ocr_result, llm_result = await self._run_dual_source(file_data, file_type)

            # 3.5. 根据OCR原始文本自动修正票据类型
            if ocr_result and ocr_result.get("raw_text"):
                raw = ocr_result["raw_text"]
                if "专用发票" in raw or ("专用" in raw and "发票" in raw):
                    if invoice.receipt_type != ReceiptType.vat_special:
                        logger.info(f"Invoice #{invoice.id} 票据类型自动修正: {invoice.receipt_type.value} → 增值税专用发票")
                        invoice.receipt_type = ReceiptType.vat_special
                elif "普通发票" in raw or ("普通" in raw and "发票" in raw):
                    if invoice.receipt_type != ReceiptType.vat_normal:
                        logger.info(f"Invoice #{invoice.id} 票据类型自动修正: {invoice.receipt_type.value} → 增值税普通发票")
                        invoice.receipt_type = ReceiptType.vat_normal

            # 4. 双源比对
            ocr_fields = ocr_result.get("extracted_fields", {}) if ocr_result else {}
            llm_fields = llm_result.get("extracted_fields", {}) if llm_result else {}
            # 将 OCR 原始文本传入 diff_engine，用于双源为空时的正则补齐
            ocr_raw_text = ocr_result.get("raw_text", "") if ocr_result else ""
            ocr_fields["_raw_text"] = ocr_raw_text
            comparison = compare_results(ocr_fields, llm_fields)
            # 清理内部字段，不应写入发票记录
            comparison["confirmed_fields"].pop("_raw_text", None)

            # 5. 更新发票字段（采用比对后的确认值）
            confirmed = comparison["confirmed_fields"]
            for field, value in confirmed.items():
                setattr(invoice, field, value)
            invoice.diff_confidence = comparison["confidence"]
            invoice.diff_conflicts = comparison["conflicts"] if comparison["conflicts"] else None

            # 6. 费用分类
            invoice_data_for_classify = {
                "receipt_type": invoice.receipt_type.value if invoice.receipt_type else None,
                "seller_name": confirmed.get("seller_name"),
                "total_with_tax": confirmed.get("total_with_tax"),
                "item_name": confirmed.get("item_name"),
            }
            classify_result = await self.classifier.classify(invoice_data_for_classify, user_description)
            invoice.fee_category = classify_result["category"]
            invoice.fee_subcategory = classify_result["subcategory"]
            invoice.classify_source = classify_result["source"]
            invoice.classify_confidence = classify_result["confidence"]

            # 7. 项目归属
            project_matcher = ProjectMatcher(self.db)
            project_result = await project_matcher.match_project(
                {"seller_name": confirmed.get("seller_name")},
                user_description,
                user_id,
            )
            invoice.project_id = project_result.get("project_id")
            invoice.project_match_source = project_result.get("source")

            # 8. 查重
            dup_checker = DuplicateChecker(self.db)
            dup_result = await dup_checker.check(
                {"invoice_number": confirmed.get("invoice_number"),
                 "total_with_tax": confirmed.get("total_with_tax"),
                 "issue_date": confirmed.get("issue_date"),
                 "seller_name": confirmed.get("seller_name")},
                file_data,
                file_type=file_type,
                current_invoice_id=invoice.id,
            )
            invoice.duplicate_status = (
                DuplicateStatus.duplicate if dup_result["is_duplicate"] else DuplicateStatus.unique
            )
            invoice.image_hash = dup_result["details"].get("image_hash")

            # 9. 基础字段校验（格式检查，非真伪验证）
            receipt_type_str = invoice.receipt_type.value if invoice.receipt_type else None
            invoice.verify_status = self._basic_verify(confirmed, receipt_type_str)

            # 9.5. 预校验 — 逻辑矛盾检测（无需调用外部 API）
            # 仅当基础校验通过时执行预校验
            if invoice.verify_status == VerifyStatus.pending:
                precheck_fields = dict(confirmed)
                if user_description:
                    precheck_fields["user_description"] = user_description
                precheck_result = precheck_invoice(precheck_fields)
                if not precheck_result.is_valid:
                    invoice.verify_status = VerifyStatus.invalid
                    invoice.verify_message = precheck_result.message
                    logger.warning(
                        f"Invoice #{invoice.id} 预校验失败: {precheck_result.message}"
                    )

            # 10. 在线验真（百度智能云）
            # 仅当格式校验通过（PENDING）且验真服务已配置时，自动执行在线验真
            if invoice.verify_status == VerifyStatus.pending:
                verify_service = get_verify_service()
                if verify_service.enabled:
                    logger.info(f"Invoice #{invoice.id} starting online verification...")
                    verify_data = {
                        "receipt_type": receipt_type_str or "增值税普通发票",
                        "invoice_number": confirmed.get("invoice_number", ""),
                        "invoice_code": confirmed.get("invoice_code", ""),
                        "issue_date": confirmed.get("issue_date", ""),
                        "check_code": confirmed.get("check_code", ""),
                        "amount": confirmed.get("amount", ""),
                        "total_with_tax": confirmed.get("total_with_tax", ""),
                    }
                    try:
                        verify_result = await verify_service.verify_invoice(verify_data)
                        if verify_result.is_valid is True:
                            invoice.verify_status = VerifyStatus.valid
                            invoice.verify_message = verify_result.message
                            logger.info(f"Invoice #{invoice.id} verification PASSED: {verify_result.message}")
                            # 验真通过后用国税票面做第三源交叉验证
                            if verify_result.verified_fields:
                                cross = cross_check_verified_fields(
                                    confirmed, verify_result.verified_fields
                                )
                                invoice.verify_cross_check = cross
                                if cross["mismatches"]:
                                    # 用国税权威数据回写本地识别错误的字段
                                    corrected_fields = {}
                                    for mm in cross["mismatches"]:
                                        field = mm["field"]
                                        verified_val = mm["verified"]
                                        if verified_val and field in (
                                            "seller_name", "seller_tax_id",
                                            "buyer_name", "buyer_tax_id",
                                        ):
                                            old_val = getattr(invoice, field, None)
                                            setattr(invoice, field, verified_val)
                                            corrected_fields[field] = {
                                                "old": old_val, "new": verified_val
                                            }
                                            logger.info(
                                                f"Invoice #{invoice.id} 验真第三源回写: "
                                                f"{field} {old_val} → {verified_val}"
                                            )
                                    if corrected_fields:
                                        # 更新 confirmed 供后续分类/项目归属使用
                                        for f, info in corrected_fields.items():
                                            confirmed[f] = info["new"]
                                        # seller_name 修正后重新分类
                                        if "seller_name" in corrected_fields:
                                            invoice_data_for_classify = {
                                                "receipt_type": invoice.receipt_type.value if invoice.receipt_type else None,
                                                "seller_name": confirmed.get("seller_name"),
                                                "total_with_tax": confirmed.get("total_with_tax"),
                                                "item_name": confirmed.get("item_name"),
                                            }
                                            classify_result = await self.classifier.classify(
                                                invoice_data_for_classify, user_description
                                            )
                                            invoice.fee_category = classify_result["category"]
                                            invoice.fee_subcategory = classify_result["subcategory"]
                                            invoice.classify_source = classify_result["source"]
                                            invoice.classify_confidence = classify_result["confidence"]
                                            logger.info(
                                                f"Invoice #{invoice.id} seller 修正后重新分类: "
                                                f"{classify_result['subcategory']}"
                                            )
                                    logger.warning(
                                        f"Invoice #{invoice.id} 验真通过但与本地识别有 "
                                        f"{len(cross['mismatches'])} 处差异"
                                        + (f"，已自动回写 {len(corrected_fields)} 个字段" if corrected_fields else "")
                                    )
                                    # 标记为人工复核，但保留 VALID 状态
                                    if invoice.status == InvoiceStatus.confirmed:
                                        invoice.status = InvoiceStatus.reviewing
                        elif verify_result.is_valid is False:
                            invoice.verify_status = VerifyStatus.invalid
                            invoice.verify_message = verify_result.message
                            logger.warning(f"Invoice #{invoice.id} verification FAILED: {verify_result.message}")
                        else:
                            # is_valid=None 表示无法验真（网络错误、配额不足等），保持 PENDING
                            invoice.verify_message = verify_result.message
                            logger.warning(f"Invoice #{invoice.id} verification inconclusive: {verify_result.message}")
                    except Exception as e:
                        logger.error(f"Invoice #{invoice.id} online verification error: {e}", exc_info=True)
                        # 验真异常不阻断流程，保持 PENDING

            # 更新状态：未解决冲突和验证警告都需要人工审核
            needs_review = [
                c for c in (comparison["conflicts"] or [])
                if c.get("status") in ("CONFLICT", "VALIDATION_WARNING")
            ]
            if needs_review:
                invoice.status = InvoiceStatus.reviewing  # 有未解决冲突 → 待人工复核
            else:
                invoice.status = InvoiceStatus.confirmed  # 冲突已全部解决或无冲突 → 自动确认

            # 11. 保存 OCR/LLM 结果
            if ocr_result:
                self.db.add(OcrResult(
                    invoice_id=invoice.id,
                    raw_text=ocr_result.get("raw_text"),
                    confidence=ocr_result.get("confidence"),
                    extracted_fields=ocr_result.get("extracted_fields"),
                    ocr_lines=ocr_result.get("ocr_lines"),
                ))
            if llm_result:
                self.db.add(LlmResult(
                    invoice_id=invoice.id,
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    extracted_fields=llm_result.get("extracted_fields"),
                    raw_response=llm_result.get("raw_response"),
                ))

            await self.db.commit()
            await self.db.refresh(invoice)

            logger.info(
                f"Invoice #{invoice.id} processed: "
                f"confidence={comparison['confidence']:.2%}, "
                f"category={invoice.fee_subcategory}, "
                f"duplicate={invoice.duplicate_status.value}"
            )
            return invoice

        except Exception as e:
            logger.error(f"Invoice #{invoice.id} processing failed: {e}", exc_info=True)
            await self.db.rollback()
            invoice.status = InvoiceStatus.reviewing
            await self.db.commit()
            raise

    async def _run_dual_source(self, file_data: bytes, file_type: str) -> tuple:
        """并行执行 OCR 和 LLM 解析

        参考: Invoice-Manager invoice_service.py
        - OCR 用 CPU 线程池
        - LLM 用 asyncio 异步调用
        """
        mime = {
            "pdf": "application/pdf",
            "ofd": "application/ofd",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }.get(file_type, "image/png")

        # OCR 在线程池中执行（CPU密集型）
        ocr_executor = get_ocr_executor(settings.ocr_max_workers)
        if file_type == "pdf":
            ocr_future = ocr_executor.submit(self.ocr.process_pdf, file_data)
        elif file_type == "ofd":
            ocr_future = ocr_executor.submit(self.ocr.process_ofd, file_data)
        else:
            ocr_future = ocr_executor.submit(self.ocr.process_image, file_data)

        # LLM 异步执行（I/O密集型）
        llm_task = asyncio.create_task(
            self.llm.parse_invoice_from_image(file_data, mime)
        )

        # 等待两者完成
        ocr_result = None
        llm_result = None

        try:
            ocr_result = ocr_future.result()
        except Exception as e:
            logger.error(f"OCR failed: {e}")

        try:
            llm_fields = await llm_task
            if llm_fields:
                llm_result = {"extracted_fields": llm_fields}
        except Exception as e:
            logger.error(f"LLM failed: {e}")

        return ocr_result, llm_result

    def _basic_verify(self, fields: dict, receipt_type: str = None) -> VerifyStatus:
        """基础字段校验（非国税API验真）

        本方法仅检查字段完整性、格式合理性，
        无法判断发票真伪。真伪验证需要接入国税API或人工确认。

        检查项：
        - 发票号：存在且按票据类型校验格式
          - 增值税普通/专用发票：20位纯数字（新版数电票）
          - 其他类型：>= 8位数字字母
        - 金额：total_with_tax 可解析为正数
        - 销售方信息：seller_name 非空
        - 税号：增值税发票要求 seller_tax_id 存在且 >= 15位

        Returns:
            VerifyStatus.pending — 字段格式校验通过，等待人工/外部验真
            VerifyStatus.unable — 关键字段缺失或格式异常
        """
        import re

        invoice_number = fields.get("invoice_number")
        total_with_tax = fields.get("total_with_tax")
        seller_name = fields.get("seller_name")
        seller_tax_id = fields.get("seller_tax_id")

        issues = []

        # 按票据类型确定发票号格式
        is_vat = receipt_type in ("增值税普通发票", "增值税专用发票")

        # 发票号校验
        if not invoice_number:
            issues.append("missing invoice_number")
        else:
            num = str(invoice_number).strip()
            if is_vat:
                # 增值税发票号码：8位（传统票）或 20位（数电票）
                if not re.match(r"^(\d{8}|\d{20})$", num):
                    issues.append(f"invalid invoice_number format for VAT (expected 8 or 20 digits): {num}")
            else:
                # 其他类型：至少8位数字/字母
                if not re.match(r"^[A-Za-z0-9]{8,}$", num):
                    issues.append(f"invalid invoice_number format: {num}")

        # 金额校验
        if not total_with_tax:
            issues.append("missing total_with_tax")
        else:
            try:
                amount_val = float(str(total_with_tax).replace(",", "").replace("￥", "").replace("¥", ""))
                if amount_val <= 0:
                    issues.append("total_with_tax <= 0")
            except ValueError:
                issues.append(f"invalid total_with_tax: {total_with_tax}")

        # 销售方校验
        if not seller_name or len(str(seller_name).strip()) < 2:
            issues.append("missing or invalid seller_name")

        # 税号校验
        if not seller_tax_id:
            if is_vat:
                # 增值税发票应有统一社会信用代码/纳税人识别号（15/18/20位）
                issues.append("missing seller_tax_id for VAT invoice")
        elif len(str(seller_tax_id).strip()) < 15:
            issues.append(f"suspicious seller_tax_id (too short): {seller_tax_id}")

        if issues:
            logger.warning(f"Basic field check issues: {issues}")
            return VerifyStatus.unable

        # 格式校验通过 → 仍为 PENDING，等待人工验真或外部API确认
        # 不返回 VALID，因为没有进行真实性验证
        logger.info("Basic field check passed, status=PENDING (awaiting manual/external verification)")
        return VerifyStatus.pending

    async def process_no_receipt(
        self, user_id: str, user_description: str, amount: str = ""
    ) -> Invoice:
        """处理无票报销场景

        纯 LLM 路径：用户描述 → LLM 提取金额/类别/项目 → 人工复核
        """
        invoice = Invoice(
            receipt_type=ReceiptType.no_receipt,
            file_path="",
            file_type="none",
            user_id=user_id,
            user_description=user_description,
            status=InvoiceStatus.processing,
            total_with_tax=amount,
        )
        self.db.add(invoice)
        await self.db.commit()
        await self.db.refresh(invoice)

        # LLM 分类
        classify_result = await self.classifier.classify(
            {"receipt_type": "no_receipt", "total_with_tax": amount},
            user_description,
        )
        invoice.fee_category = classify_result["category"]
        invoice.fee_subcategory = classify_result["subcategory"]
        invoice.classify_source = classify_result["source"]
        invoice.classify_confidence = classify_result["confidence"]

        # 项目归属
        project_matcher = ProjectMatcher(self.db)
        project_result = await project_matcher.match_project({}, user_description, user_id)
        invoice.project_id = project_result.get("project_id")
        invoice.project_match_source = project_result.get("source")

        # 无票不需要查重和验真
        invoice.duplicate_status = DuplicateStatus.unique
        invoice.verify_status = VerifyStatus.unable

        # 无票一律需要人工复核
        invoice.status = InvoiceStatus.reviewing
        await self.db.commit()
        await self.db.refresh(invoice)

        return invoice

    async def get_invoices_by_user(self, user_id: str, status: str = None) -> list[Invoice]:
        """获取用户的发票列表"""
        query = select(Invoice).where(Invoice.user_id == user_id)
        if status:
            query = query.where(Invoice.status == InvoiceStatus(status))
        query = query.order_by(Invoice.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_statistics(self) -> dict:
        """获取统计数据"""
        result = await self.db.execute(select(Invoice))
        invoices = list(result.scalars().all())

        total = len(invoices)
        total_amount = sum(float(i.total_with_tax) for i in invoices if i.total_with_tax)
        total_tax = sum(float(i.tax_amount) for i in invoices if i.tax_amount)
        pending_review = len([i for i in invoices if i.status == InvoiceStatus.reviewing])
        confirmed = len([i for i in invoices if i.status == InvoiceStatus.confirmed])
        duplicates = len([i for i in invoices if i.duplicate_status == DuplicateStatus.duplicate])
        nonstandard_count = len([i for i in invoices if i.is_nonstandard])
        high_risk_count = len([i for i in invoices if i.is_nonstandard and i.risk_level == "high"])

        return {
            "total_invoices": total,
            "total_amount": round(total_amount, 2),
            "total_tax": round(total_tax, 2),
            "pending_review": pending_review,
            "confirmed": confirmed,
            "duplicates": duplicates,
            "nonstandard_count": nonstandard_count,
            "high_risk_count": high_risk_count,
        }
