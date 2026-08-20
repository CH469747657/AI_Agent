"""核心编排服务 — 串联完整处理链路

处理流程:
  接收票据 → [并行] OCR识别 + LLM解析 → 双源比对 → 费用分类 → 项目归属 → 查重 → 保存

参考: Invoice-Manager invoice_service.py (并行线程池 + 双源比对)
"""

import os
import asyncio
import io
import logging
from datetime import datetime
from typing import Optional

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
from app.services.duplicate_checker import DuplicateChecker
from app.services.verify_service import get_verify_service
from app.services.verify_cross_check import cross_check_verified_fields
from app.services.invoice_prevalidator import precheck_invoice
from app.prompts.nonstandard_prompts import NONSTANDARD_RECEIPT_TYPES

logger = logging.getLogger(__name__)


class InvoiceService:
    """发票处理核心编排服务"""

    # VLM 调用用的压缩参数：长边 ≤768 触发网关快速路径（25s→7s），
    # 实测识别字段数与金额准确率与原图一致。
    _VLM_MAX_SIDE = 768
    _VLM_JPEG_QUALITY = 85

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ocr = get_ocr_service()
        self.llm = get_llm_service()
        self.classifier = FeeClassifier()

    def _compress_image_for_vlm(self, file_data: bytes) -> bytes:
        """压缩图片用于 VLM 调用（长边 ≤768，JPEG q85）

        原图保留在磁盘，此处仅生成 VLM 调用用的压缩副本以降低延迟。
        非图片或压缩失败时原样返回。
        """
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(file_data))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            if max(img.size) > self._VLM_MAX_SIDE:
                img.thumbnail((self._VLM_MAX_SIDE, self._VLM_MAX_SIDE))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self._VLM_JPEG_QUALITY)
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"Image compress failed, using original: {e}")
            return file_data

    async def process_upload(
        self,
        file_data: bytes,
        file_type: str,
        receipt_type: str,
        user_id: str,
        user_description: str = "",
    ) -> Invoice:
        """完整处理一张票据：上传 → 识别 → 分类 → 查重 → 保存

        无感上传模式（receipt_type 为空时）：
        - 初始默认为 vat_normal，避免 DB NotNull 约束失败
        - LLM Vision 识别后，根据返回字段自动修正为真实类型
        """

        # 1. 保存原始文件
        filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file_type}"
        file_path = os.path.join(settings.upload_dir, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(file_data)

        # 1.5 图片压缩用于 VLM 调用（原图已存盘，此处生成压缩副本降低 VLM 延迟）
        if file_type in ("jpg", "jpeg", "png"):
            file_data = self._compress_image_for_vlm(file_data)

        # 1.6 从 user_description 拆分日期 + 纯用途（支持"8月9号 项目投标费"等写法）
        from app.services.expense_date_engine import extract_date_and_purpose
        parsed_expense_date, clean_purpose = extract_date_and_purpose(user_description)
        if parsed_expense_date:
            user_description = clean_purpose or user_description

        # 2. 创建发票记录（receipt_type 为空时默认 vat_normal，后续 LLM 识别后修正）
        actual_receipt_type = receipt_type if receipt_type else ReceiptType.vat_normal.value
        mime_map = {
            "pdf": "application/pdf",
            "ofd": "application/ofd",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }
        invoice = Invoice(
            receipt_type=ReceiptType(actual_receipt_type),
            file_path=file_path,
            file_type=file_type,
            user_id=user_id,
            user_description=user_description,
            expense_date=parsed_expense_date,
            expense_date_source="note" if parsed_expense_date else None,
            status=InvoiceStatus.processing,
        )
        self.db.add(invoice)
        await self.db.commit()
        await self.db.refresh(invoice)

        # 无感上传：receipt_type 为空时，单次 VLM 同时判断类型 + 提取字段
        vlm_fields = None
        if not receipt_type:
            try:
                detected_type, vlm_fields = await self._detect_and_extract_by_vision(file_data, file_type)
                if detected_type and detected_type != actual_receipt_type:
                    logger.info(
                        f"Invoice #{invoice.id} VLM 自动识别票据类型: {actual_receipt_type} → {detected_type}"
                    )
                    invoice.receipt_type = ReceiptType(detected_type)
                    actual_receipt_type = detected_type
                    await self.db.commit()
                    await self.db.refresh(invoice)
            except Exception as e:
                logger.warning(f"Invoice #{invoice.id} VLM 合并识别失败，回退默认值: {e}")

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
                    predefined_fields=vlm_fields,
                )

                # 非标票据处理完成，不自动归集报销单
                # 归集时机：管理员主动生成或每月21号定时生成
                return invoice

            # 3. 字段提取：优先用合并 VLM 的结果，否则走双源（OCR+LLM）
            if vlm_fields:
                llm_result = {"extracted_fields": vlm_fields}
                ocr_result = None
            else:
                ocr_result, llm_result = await self._run_dual_source(file_data, file_type)

            # 票据类型判定责任收敛到 VLM（_detect_receipt_type_by_vision）
            # 不再用 OCR 文本关键词二次修正类型 —— 关键词规则覆盖不全，
            # 与 VLM 视觉判断冲突时难定优先级，分散了判定责任。
            # VLM 判错时由用户在对话框补充（如"这是收据"）修正类型。

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
                                    if invoice.status == InvoiceStatus.reviewed:
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
                invoice.status = InvoiceStatus.reviewed  # 冲突已全部解决或无冲突 → 自动确认

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

            # 12. 发票处理完成，不自动归集报销单
            # 归集时机：管理员主动调用 /api/reimbursements/aggregate 或每月21号定时任务
            # 发票以「游离」状态保存（reimbursement_id=None），可随时删除

            return invoice

        except Exception as e:
            # 识别失败/取消/超时 → 删除发票记录和原始文件，杜绝脏数据残留
            # 规则：发票必须识别完成（reviewing/confirmed/reimbursed）才能出现在列表中
            # 注意：用 __dict__ 直接拿已加载的属性值，避免触发 lazy refresh（rollback 后 session 异常态会 MissingGreenlet）
            inv_dict = invoice.__dict__ if invoice else {}
            invoice_id = inv_dict.get("id")
            file_path = inv_dict.get("file_path")
            logger.error(f"Invoice #{invoice_id} processing failed, cleaning up: {e}", exc_info=True)
            try:
                await self.db.rollback()
            except Exception:
                pass
            # 清理用独立 session，避免主 session 处于异常态导致 MissingGreenlet
            from app.database import get_async_sessionmaker
            try:
                async with get_async_sessionmaker()() as cleanup_db:
                    if invoice_id is not None:
                        ocr_rows = await cleanup_db.execute(
                            select(OcrResult).where(OcrResult.invoice_id == invoice_id)
                        )
                        for ocr in ocr_rows.scalars().all():
                            await cleanup_db.delete(ocr)
                        llm_rows = await cleanup_db.execute(
                            select(LlmResult).where(LlmResult.invoice_id == invoice_id)
                        )
                        for llm in llm_rows.scalars().all():
                            await cleanup_db.delete(llm)
                        inv_row = await cleanup_db.execute(
                            select(Invoice).where(Invoice.id == invoice_id)
                        )
                        inv = inv_row.scalar_one_or_none()
                        if inv:
                            await cleanup_db.delete(inv)
                        await cleanup_db.commit()
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
                    logger.info(f"Invoice #{invoice_id} and file cleaned up (recognition failed)")
            except Exception as cleanup_err:
                logger.error(f"Invoice #{invoice_id} cleanup also failed: {cleanup_err}")
            raise

    async def _detect_and_extract_by_vision(
        self, file_data: bytes, file_type: str
    ) -> tuple[Optional[str], Optional[dict]]:
        """单次 VLM 调用同时返回票据类型 + 字段（替代 detect + extract 两次调用）

        Returns: (receipt_type_value, fields_dict) — 失败时对应项为 None
        """
        try:
            from app.services.llm_service import get_llm_service
            from app.prompts.invoice_prompts import COMBINED_VISION_PROMPT
            svc = get_llm_service()
            if not svc.is_available() or not svc._supports_vision():
                return None, None

            mime_map = {
                "pdf": "application/pdf", "ofd": "application/ofd",
                "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            }
            mime_type = mime_map.get(file_type, "image/jpeg")

            # PDF/OFD 转图片（复用现有逻辑）
            actual_data = file_data
            actual_mime = mime_type
            if mime_type == "application/pdf":
                try:
                    from pdf2image import convert_from_bytes
                    from io import BytesIO
                    images = convert_from_bytes(file_data, dpi=300, first_page=1, last_page=1)
                    if images:
                        buf = BytesIO()
                        images[0].save(buf, format="PNG")
                        actual_data = buf.getvalue()
                        actual_mime = "image/png"
                except Exception as e:
                    logger.warning(f"PDF to image failed for combined detect: {e}")
                    return None, None
            elif mime_type == "application/ofd":
                try:
                    from app.services.ofd_parser import get_ofd_parser
                    parsed = get_ofd_parser().parse(file_data)
                    img_bytes = parsed.get("image_bytes")
                    if img_bytes:
                        actual_data = img_bytes
                        actual_mime = "image/png"
                    else:
                        return None, None
                except Exception as e:
                    logger.warning(f"OFD parse failed for combined detect: {e}")
                    return None, None

            import base64
            b64_image = base64.b64encode(actual_data).decode()
            response = await svc.client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "user", "content": [
                        {"type": "text", "text": COMBINED_VISION_PROMPT},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{actual_mime};base64,{b64_image}"
                        }}
                    ]}
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=2000,
            )
            content = response.choices[0].message.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            import json
            data = json.loads(content)

            raw_type = data.get("receipt_type", "")
            type_mapping = {
                "增值税普通发票": ReceiptType.vat_normal.value,
                "增值税专用发票": ReceiptType.vat_special.value,
                "火车票": ReceiptType.train_ticket.value,
                "机票": ReceiptType.flight_ticket.value,
                "收据": ReceiptType.receipt.value,
                "支付截图": ReceiptType.payment_screenshot.value,
                "交易流水单": ReceiptType.bank_statement.value,
            }
            receipt_type = None
            for keyword, value in type_mapping.items():
                if keyword in raw_type:
                    receipt_type = value
                    break
            fields = data.get("fields") or {}
            logger.info(
                f"Combined VLM: type={receipt_type} fields_count={sum(1 for v in fields.values() if v)}"
            )
            return receipt_type, fields
        except Exception as e:
            logger.warning(f"_detect_and_extract_by_vision error: {e}")
            return None, None

    async def _detect_receipt_type_by_vision(
        self,
        file_data: bytes,
        file_type: str,
    ) -> Optional[str]:
        """无感上传：用 LLM Vision 自动判断票据类型

        通过轻量级 prompt 让 LLM 看图判断属于哪种票据类型。
        返回 ReceiptType 的 value（如"增值税普通发票"），失败返回 None。

        判断策略：
        1. 优先用 LLM Vision 直接判断（一次调用）
        2. 失败时返回 None，由调用方使用默认值
        """
        try:
            from app.services.llm_service import get_llm_service
            svc = get_llm_service()
            if not svc.is_available() or not svc._supports_vision():
                return None

            # PDF/OFD 转图片（复用 parse_invoice_from_image 的逻辑）
            mime_map = {
                "pdf": "application/pdf",
                "ofd": "application/ofd",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "png": "image/png",
            }
            mime_type = mime_map.get(file_type, "image/jpeg")

            # 构造轻量级判断 prompt — 强调视觉布局差异而非仅文本关键词
            detect_prompt = """请仔细观察这张图片的**视觉布局和整体样式**，判断属于以下哪种票据类型。

只返回类型名称，不要其他文字。

## 类型特征（按视觉布局区分）

**增值税普通发票** — 国家税务总局监制的官方标准格式：
- 顶部有红色/蓝色边框，标题为"XX省/市增值税普通发票"
- **必须有"发票代码"（20位）、"发票号码"（20位）、"校验码"等官方字段**
- 分为购买方、销售方、货物明细、金额等标准区块
- 底部有"国家税务总局监制"字样
- **关键判据**：标题明确含"增值税普通发票"，且含发票代码/号码/校验码

**增值税专用发票** — 与普票类似但标题含"专用"：
- 顶部标题为"XX省/市增值税**专用**发票"
- 其他布局与普通发票相同
- **关键判据**：标题含"增值税专用发票"

**火车票** — 12306标准格式：
- 票面较小，横向布局
- 包含车次、座位号、乘车人身份证号
- 有"中国铁路"标识

**机票** — 航空电子客票：
- 包含航班号（如CA1234）、乘机人姓名
- 有出发/到达机场、登机时间
- 通常有航空公司Logo

**收据** — 手写或简易打印的收款凭证，**非发票**：
- 标题含"收据""收条""收款凭证""缴费凭证""收款收据"等
- 格式简单，**无"发票代码""发票号码""校验码"等官方字段**
- 可能为手写体或简易打印
- 可能含"实收金额""人民币大写""收款员工号"等字样
- **关键判据**：标题含"收据/收款凭证/缴费凭证"且**不含**"发票代码/校验码"
- **特别注意**：即使票面有"号码"字段，只要不是"发票代码/发票号码/校验码"，仍应判为收据

**支付截图** — 手机App截图，**非发票**：
- **明显是手机App界面截图**，非正式票据
- 顶部有微信/支付宝的绿色或蓝色导航栏
- 显示"支付成功""交易完成"等状态
- 包含"收款方""付款金额""交易时间""交易单号"
- 有手机状态栏（信号、电量、时间）
- **无"发票代码""发票号码""校验码"等官方字段**

**交易流水单** — 银行/支付平台流水：
- 表格形式，多行交易记录
- 包含日期、金额、余额、交易类型等列
- 有账户信息或银行Logo

## 关键判别规则（防止误判为增值税发票）

1. **出租车发票**（含"车费发票""TAXI""客运出租"字样）→ **收据**（不是增值税发票）
   - 虽含"发票"字样，但不是增值税发票，归为收据类
2. **缴费凭证/收款凭证**（电信/水电/燃气等）→ **收据**
   - 标题含"收款凭证""缴费凭证"，明确不是发票
3. **手写收据** → **收据**
4. **支付App截图** → **支付截图**（不是增值税发票）
5. **必须含"发票代码+发票号码+校验码"3个官方字段**才能判为增值税发票（普通/专用）
   - 缺任一字段 → 不是增值税发票，按其他类型判断

若无法判断，返回"未知"。"""

            import base64
            b64_image = base64.b64encode(file_data).decode()

            # PDF 先转图片（复用 parse_invoice_from_image 内的 PDF 转换逻辑）
            actual_data = file_data
            actual_mime = mime_type
            if mime_type == "application/pdf":
                try:
                    from pdf2image import convert_from_bytes
                    images = convert_from_bytes(file_data, dpi=300, first_page=1, last_page=1)
                    if images:
                        from io import BytesIO
                        buf = BytesIO()
                        images[0].save(buf, format="PNG")
                        actual_data = buf.getvalue()
                        actual_mime = "image/png"
                except Exception as e:
                    logger.warning(f"PDF to image conversion failed for type detection: {e}")
                    return None
            elif mime_type == "application/ofd":
                # OFD 用内嵌图片或结构化解析判断
                try:
                    from app.services.ofd_parser import get_ofd_parser
                    parsed = get_ofd_parser().parse(file_data)
                    fields = parsed.get("fields", {})
                    if any(v for v in fields.values()):
                        # 有结构化字段 → 增值税发票
                        return ReceiptType.vat_normal.value
                    img_bytes = parsed.get("image_bytes")
                    if img_bytes:
                        actual_data = img_bytes
                        actual_mime = "image/png"
                    else:
                        return None
                except Exception as e:
                    logger.warning(f"OFD parse failed for type detection: {e}")
                    return None

            try:
                response = await svc.client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "user", "content": [
                            {"type": "text", "text": detect_prompt},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{actual_mime};base64,{base64.b64encode(actual_data).decode()}"
                            }}
                        ]}
                    ],
                    temperature=0,
                    max_tokens=20,
                    timeout=10.0,
                )
                result = response.choices[0].message.content.strip()

                # 映射 LLM 输出到 ReceiptType
                type_mapping = {
                    "增值税普通发票": ReceiptType.vat_normal.value,
                    "增值税专用发票": ReceiptType.vat_special.value,
                    "火车票": ReceiptType.train_ticket.value,
                    "机票": ReceiptType.flight_ticket.value,
                    "收据": ReceiptType.receipt.value,
                    "支付截图": ReceiptType.payment_screenshot.value,
                    "交易流水单": ReceiptType.bank_statement.value,
                }
                for keyword, receipt_value in type_mapping.items():
                    if keyword in result:
                        return receipt_value

                logger.info(f"VLM 票据类型识别结果未匹配: {result!r}")
                return None
            except Exception as e:
                logger.warning(f"VLM 票据类型识别调用失败: {e}")
                return None
        except Exception as e:
            logger.warning(f"_detect_receipt_type_by_vision error: {e}")
            return None

    async def _run_dual_source(self, file_data: bytes, file_type: str) -> tuple:
        """按文件类型分层路由识别源（避免冗余调用 + 保留 PDF 双源兜底）

        file_type 路由策略（基于 vlt_mm_31_vis 实测，详见 docs/OCR-替代视觉模型评估.md）:
        - OFD：单源 ofd_parser（矢量文字零误差，LLM 路径对 OFD 本就跳过 Vision 走 ofd_parser，调用冗余）
        - 图片（jpg/jpeg/png）：单源 LLM（OCR 对图片样本 0% 字段命中，纯噪声且污染 diff_engine）
        - PDF：双源（OCR 兜底 + LLM 精度，diff_engine 做交叉验证）

        Returns:
            (ocr_result, llm_result) — 单源场景下另一源为 None，
            下游消费方已用 `if x_result:` 守卫（见 339-357 行持久化、131 行 raw_text 修正、169-172 行 diff 输入）。
        """
        mime = {
            "pdf": "application/pdf",
            "ofd": "application/ofd",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }.get(file_type, "image/png")

        ocr_result = None
        llm_result = None

        # ===== 图片：单源 LLM（OCR 对图片样本无字段语义） =====
        if file_type in ("jpg", "jpeg", "png"):
            try:
                llm_fields = await self.llm.parse_invoice_from_image(file_data, mime)
                if llm_fields:
                    llm_result = {"extracted_fields": llm_fields}
            except Exception as e:
                logger.error(f"LLM failed (image path): {e}")
            return ocr_result, llm_result

        # ===== OFD：单源 ofd_parser（LLM 对 OFD 检测到矢量字段后跳过 Vision，调用冗余） =====
        if file_type == "ofd":
            ocr_executor = get_ocr_executor(settings.ocr_max_workers)
            ocr_future = ocr_executor.submit(self.ocr.process_ofd, file_data)
            try:
                ocr_result = ocr_future.result()
            except Exception as e:
                logger.error(f"OFD parse failed: {e}")
            return ocr_result, llm_result

        # ===== PDF：保留双源（OCR 兜底 + LLM 精度） =====
        ocr_executor = get_ocr_executor(settings.ocr_max_workers)
        ocr_future = ocr_executor.submit(self.ocr.process_pdf, file_data)

        llm_task = asyncio.create_task(
            self.llm.parse_invoice_from_image(file_data, mime)
        )

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

        # 无票不需要查重和验真
        invoice.duplicate_status = DuplicateStatus.unique
        invoice.verify_status = VerifyStatus.unable

        # 无票一律需要人工复核
        invoice.status = InvoiceStatus.reviewing
        await self.db.commit()
        await self.db.refresh(invoice)

        # 无票报销不自动归集，与标准/非标票据保持一致
        # 归集时机：管理员主动生成或每月21号定时生成

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
        def _safe_float(val) -> float:
            """安全转换金额字符串（如 '500元'、'¥3,840.00'）为浮点数"""
            if val is None:
                return 0.0
            import re
            cleaned = re.sub(r'[^\d.\-]', '', str(val).replace(',', ''))
            try:
                return float(cleaned) if cleaned else 0.0
            except ValueError:
                return 0.0

        total_amount = sum(_safe_float(i.total_with_tax) for i in invoices)
        total_tax = sum(_safe_float(i.tax_amount) for i in invoices)
        pending_review = len([i for i in invoices if i.status == InvoiceStatus.reviewing])
        confirmed = len([i for i in invoices if i.status == InvoiceStatus.reviewed])
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

    # ============================================================
    # 删除发票（硬删除 — 物理删除记录 + 关联数据 + 原始文件）
    # ============================================================

    async def delete_invoice(
        self,
        invoice_id: int,
        user_id: str | None = None,
    ) -> dict:
        """删除发票及其关联的 OCR/LLM 结果

        仅供「未关联报销单」的发票删除（已提交报销单的发票不允许删除）。

        Args:
            invoice_id: 发票 ID
            user_id: 可选的用户 ID，传入则校验归属归属

        Returns:
            {"message": "发票 #N 已删除", "deleted": True}

        Raises:
            HTTPException: 404 不存在 / 403 无权操作 / 409 已关联报销单
        """
        from fastapi import HTTPException

        result = await self.db.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        invoice = result.scalars().first()
        if not invoice:
            raise HTTPException(status_code=404, detail="发票不存在")

        # 归属校验（user_id 传入时才校验）
        if user_id and invoice.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权操作该发票")

        # 关联报销单检查 — 已关联的不允许删除
        if invoice.reimbursement_id is not None:
            raise HTTPException(
                status_code=409,
                detail="该发票已关联报销单，无法删除。请先从报销单中移除。",
            )

        # 删除关联的 OCR / LLM 结果
        ocr_results = await self.db.execute(
            select(OcrResult).where(OcrResult.invoice_id == invoice_id)
        )
        for ocr in ocr_results.scalars().all():
            await self.db.delete(ocr)

        llm_results = await self.db.execute(
            select(LlmResult).where(LlmResult.invoice_id == invoice_id)
        )
        for llm in llm_results.scalars().all():
            await self.db.delete(llm)

        # 删除关联的报销单明细行（reimbursement_items）并在有变更时重算报销单
        from app.models.reimbursement import ReimbursementItem
        from app.services.aggregation_service import detach_invoice_from_cycle
        affected_reimb = await detach_invoice_from_cycle(self.db, invoice)
        if affected_reimb:
            await self.db.commit()  # 保存重算结果

        # 删除原始文件
        if invoice.file_path and os.path.exists(invoice.file_path):
            try:
                os.remove(invoice.file_path)
            except OSError:
                pass  # 文件删除失败不阻塞

        # 删除发票记录
        await self.db.delete(invoice)
        await self.db.commit()

        logger.info("Invoice deleted: id=%s user=%s", invoice_id, user_id or "N/A")
        return {"message": f"发票 #{invoice_id} 已删除", "deleted": True}
