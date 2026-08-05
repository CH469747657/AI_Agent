"""OCR 票据识别服务（基于 PaddleOCR）

参考项目: PaddlePaddle/PaddleOCR (86.4k⭐)
参考项目: stone16/Invoice-Manager ocr_service.py
"""

import re
import logging
import threading
from io import BytesIO
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

_ocr_lock = threading.Lock()
_ocr_instance: Optional["OCRService"] = None
_executor_pool: Optional[ThreadPoolExecutor] = None


class FieldExtractor:
    """从 OCR 原始文本中通过正则规则提取发票字段

    参考: Invoice-Manager ocr_service.py FieldExtractor
    参考: inmine2/InvoiceOCRer (30⭐) 中国发票正则模板
    """

    def extract_fields(self, raw_text: str, ocr_lines: list = None) -> dict:
        """提取12个结构化字段"""
        amount = self._extract_amount(raw_text, r"金额[:：\s]*(\d+\.?\d*)")
        tax_amount = self._extract_amount(raw_text, r"税额[:：\s]*(\d+\.?\d*)")
        total = self._extract_amount(raw_text, r"(?:价税合计|小写)[））：:¥￥\s]*(\d+\.?\d*)")

        # 兜底：表格列头与数值分行时，用 ￥/¥/Y 前缀匹配
        if amount is None or tax_amount is None or total is None:
            yen_amounts = re.findall(r"[¥￥Y](\d+\.?\d*)", raw_text)
            # 通常前两个是金额和税额，最后一个是价税合计
            if amount is None and len(yen_amounts) >= 1:
                amount = yen_amounts[0]
            if tax_amount is None and len(yen_amounts) >= 2:
                tax_amount = yen_amounts[1]

        return {
            "invoice_number": self._extract_invoice_number(raw_text),
            "invoice_code": self._extract_invoice_code(raw_text),
            "check_code": self._extract_check_code(raw_text),
            "issue_date": self._extract_date(raw_text),
            "buyer_name": self._extract_buyer_name(raw_text),
            "buyer_tax_id": self._extract_tax_id(raw_text, is_buyer=True),
            "seller_name": self._extract_seller_name(raw_text),
            "seller_tax_id": self._extract_tax_id(raw_text, is_buyer=False),
            "item_name": self._extract_item_name(raw_text),
            "total_with_tax": total,
            "amount": amount,
            "tax_amount": tax_amount,
            "tax_rate": self._extract_tax_rate(raw_text),
        }

    def _extract_invoice_number(self, text: str) -> str | None:
        m = re.search(r"发票号码[:：\s]*(\d{8,20})", text)
        return m.group(1) if m else None

    def _extract_invoice_code(self, text: str) -> str | None:
        m = re.search(r"发票代码[:：\s]*(\d{10,12})", text)
        return m.group(1) if m else None

    def _extract_check_code(self, text: str) -> str | None:
        """提取校验码（后6位，用于在线验真）

        增值税发票校验码位于发票右上角，通常为20位数字。
        OCR 文本中常见格式:
          - "校验码：12345678901234567890"
          - "校验码 12345678901234567890"
          - 部分发票仅显示后6位
        在线验真只需后6位。
        """
        # 优先匹配"校验码"标签后的数字
        m = re.search(r"校验码[:：\s]*(\d{6,20})", text)
        if m:
            return m.group(1)[-6:]  # 取后6位
        return None

    def _extract_date(self, text: str) -> str | None:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", text)
        if m:
            parts = re.split(r"[-/]", m.group(1))
            return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        return None

    def _extract_buyer_name(self, text: str) -> str | None:
        # 只取"名称："后的同一行内容，避免 DOTALL 跨行捕获销售方信息
        m = re.search(r"购买方.*?名称[:：\s]*([^\n]+)", text, re.DOTALL)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"\s+", "", name)
            return name if name else None
        return None

    def _extract_seller_name(self, text: str) -> str | None:
        """提取销售方名称

        改进: 增值税发票中"销售方"出现在文本后半部分，
        其"名称:"标签后的公司名才是销售方。
        使用非贪婪匹配，并排除括号内的提示文字。
        """
        # 策略1: 匹配"销售方"后的"名称:"标签
        m = re.search(r"销售方.*?名称[:：\s]*([^\n]+)", text, re.DOTALL)
        if m:
            name = m.group(1).strip()
            # 清理: 去除括号说明、多余空格
            name = re.sub(r"\s+", "", name)
            name = re.sub(r"（.*?）", "", name)
            # 过滤: 如果拿到的是"名称:"说明没匹配到实际公司名
            if name and not name.startswith("名称") and len(name) >= 4:
                return name

        # 策略2: 如果上面失败, 尝试匹配所有"名称:"标签, 取最后一个（销售方通常在最后）
        all_names = re.findall(r"名称[:：\s]*([^\n]+)", text)
        if all_names:
            # 过滤掉太短的或明显的噪音
            candidates = []
            for n in all_names:
                clean = re.sub(r"\s+", "", n.strip())
                clean = re.sub(r"（.*?）", "", clean)
                if clean and len(clean) >= 4 and not clean.startswith("名称"):
                    candidates.append(clean)
            if len(candidates) >= 2:
                # 购买方是第一个, 销售方是最后一个
                return candidates[-1]
            elif candidates:
                return candidates[0]

        return None

    def _extract_tax_id(self, text: str, is_buyer: bool = True) -> str | None:
        """提取纳税人识别号
        
        OCR 文本通常将买卖双方税号连续排列，需取不同位置的匹配。
        买方取第一个，卖方取最后一个。
        """
        ids = re.findall(r"([A-Z0-9]{15,20})", text)
        if not ids:
            return None
        # 过滤掉明显不是税号的纯数字（如发票号码）
        tax_ids = [i for i in ids if any(c.isalpha() for c in i)]
        if not tax_ids:
            tax_ids = ids
        if is_buyer:
            return tax_ids[0]
        else:
            return tax_ids[-1] if len(tax_ids) > 1 else tax_ids[0]

    def _extract_field_after_label(self, text: str, pattern: str) -> str | None:
        m = re.search(pattern, text, re.DOTALL)
        return m.group(1).strip() if m else None

    def _extract_item_name(self, text: str) -> str | None:
        """提取商品项目名称

        改进: 保留完整的 *分类*商品名称 格式，
        而非截断为仅商品名部分。
        例如: *其他咨询服务*服务费 而非 服务费
        """
        # 匹配完整的 *分类*商品名称 格式
        m = re.search(r"\*([^*]+)\*([^\s*]+)", text)
        if m:
            category = m.group(1).strip()
            item = m.group(2).strip()
            # 返回完整格式: 分类*商品名
            return f"{category}*{item}" if category and item else None
        return None

    def _extract_amount(self, text: str, pattern: str) -> str | None:
        m = re.search(pattern, text)
        if m:
            return m.group(1).replace(",", "").replace("￥", "").replace("¥", "")
        return None

    def _extract_tax_rate(self, text: str) -> str | None:
        m = re.search(r"(\d{1,2}%)", text)
        if m:
            return m.group(1)
        if "免税" in text:
            return "免税"
        return None


class OCRService:
    """PaddleOCR 票据识别服务

    参考: Invoice-Manager ocr_service.py
    - 线程安全懒加载 PaddleOCR 实例
    - 支持 PDF（先转图片再 OCR）
    - 返回原始文本行 + 置信度 + 结构化字段
    """

    def __init__(self):
        self._ocr = None
        self._lock = threading.Lock()
        self._extractor = FieldExtractor()

    @property
    def ocr(self):
        if self._ocr is None:
            with self._lock:
                if self._ocr is None:
                    from rapidocr_onnxruntime import RapidOCR
                    logger.info("Initializing RapidOCR...")
                    self._ocr = RapidOCR()
                    logger.info("RapidOCR initialized successfully")
        return self._ocr

    def process_image(self, file_data: bytes) -> dict:
        """处理图片，返回 OCR 识别结果"""
        img = Image.open(BytesIO(file_data))
        # 转为 RGB（处理 RGBA/灰度图）
        if img.mode != "RGB":
            img = img.convert("RGB")
        img_array = np.array(img)

        result, _ = self.ocr(img_array)

        text_lines = []
        all_text = []
        if result:
            for item in result:
                # RapidOCR 返回格式: [box, text, confidence]
                bbox, text, confidence = item[0], item[1], item[2]
                if text:
                    conf = confidence * 100 if confidence <= 1.0 else confidence
                    text_lines.append({
                        "text": text,
                        "confidence": round(conf, 2),
                        "bbox": bbox,
                    })
                    all_text.append(text)

        raw_text = "\n".join(all_text)
        extracted = self._extractor.extract_fields(raw_text, text_lines)

        return {
            "raw_text": raw_text,
            "confidence": sum(l["confidence"] for l in text_lines) / max(len(text_lines), 1),
            "extracted_fields": extracted,
            "ocr_lines": text_lines,
        }

    def process_pdf(self, file_data: bytes) -> dict:
        """PDF 先转图片(300DPI)再 OCR"""
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(file_data, dpi=300)
        all_text = []
        all_lines = []
        all_conf = []

        for img in images:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img_array = np.array(img)
            result, _ = self.ocr(img_array)

            if result:
                for item in result:
                    bbox, text, confidence = item[0], item[1], item[2]
                    if text:
                        conf = confidence * 100 if confidence <= 1.0 else confidence
                        all_lines.append({"text": text, "confidence": round(conf, 2), "bbox": bbox})
                        all_text.append(text)
                        all_conf.append(conf)

        raw_text = "\n".join(all_text)
        extracted = self._extractor.extract_fields(raw_text, all_lines)

        return {
            "raw_text": raw_text,
            "confidence": sum(all_conf) / max(len(all_conf), 1),
            "extracted_fields": extracted,
            "ocr_lines": all_lines,
        }

    def process_ofd(self, file_data: bytes) -> dict:
        """OFD 解析：纯 Python 提取矢量文字（精度 100%），无矢量文字时回落图片 OCR

        数电票 OFD 内嵌结构化矢量文字，直接从 XML 提取，无需 OCR，
        精度远超 OCR 且无识别误差。扫描件式 OFD（无矢量文字）才回落图片 OCR。
        """
        from app.services.ofd_parser import get_ofd_parser

        parsed = get_ofd_parser().parse(file_data)
        full_text = parsed.get("full_text", "")
        fields = parsed.get("fields", {})

        # 有矢量文字或结构化字段 → 直接用 OFD 解析结果（精度 100%）
        if full_text or any(v for v in fields.values()):
            logger.info(
                f"OFD 矢量文字解析成功: invoice_number={fields.get('invoice_number')}, "
                f"seller={fields.get('seller_name')}, text_len={len(full_text)}"
            )
            return {
                "raw_text": full_text,
                "confidence": 1.0,
                "extracted_fields": fields,
                "ocr_lines": [],
            }

        # 无矢量文字（扫描件式 OFD）→ 提取内嵌图片走 OCR
        img_bytes = parsed.get("image_bytes")
        if img_bytes:
            logger.info("OFD 无矢量文字，回落内嵌图片 OCR")
            return self.process_image(img_bytes)

        logger.warning("OFD 解析无文字无图片")
        return {
            "raw_text": "",
            "confidence": 0.0,
            "extracted_fields": {},
            "ocr_lines": [],
        }


# ===== 单例管理 =====
def get_ocr_service() -> OCRService:
    global _ocr_instance
    if _ocr_instance is None:
        with _ocr_lock:
            if _ocr_instance is None:
                _ocr_instance = OCRService()
    return _ocr_instance


def get_field_extractor() -> FieldExtractor:
    return get_ocr_service()._extractor


def get_ocr_executor(max_workers: int = 2) -> ThreadPoolExecutor:
    """获取 OCR 专用线程池（CPU密集型）"""
    global _executor_pool
    if _executor_pool is None:
        _executor_pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ocr")
    return _executor_pool
