"""OFD 文件解析器（纯 Python，零外部依赖）

OFD（GB/T 33190-2016）是中国版式文档格式，数电票（全电发票）常用。
本质是 ZIP 包 + XML，内嵌矢量文字可直接提取，精度远超 OCR。

三层提取策略：
  L1 — OFD.xml 的 CustomDatas：数电票元数据（发票号/金额/税号等），最精准
  L2 — CustomTag.xml 的 ID→语义映射 + TextObject ID：结构化提取每个字段
  L3 — 所有 Content.xml 的 TextCode 文字拼接：兜底全文，喂给现有正则提取器

输出字段命名与 diff_engine.COMPARABLE_FIELDS 完全对齐，可无缝替换 OCR/LLM 双源结果。

依赖：仅 Python 标准库（zipfile / xml.etree.ElementTree / re）
"""

import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

# CustomTag 标签名 → comparable 字段名
# 仅映射"合计/单值"字段，明细行字段（Price/Quantity/明细Amount）不映射，避免覆盖合计
TAG_TO_FIELD = {
    "InvoiceNo": "invoice_number",
    "IssueDate": "issue_date",
    "BuyerName": "buyer_name",
    "BuyerTaxID": "buyer_tax_id",
    "SellerName": "seller_name",
    "SellerTaxID": "seller_tax_id",
    "TaxExclusiveTotalAmount": "amount",          # 合计金额（不含税）
    "TaxTotalAmount": "tax_amount",               # 合计税额
    "TaxInclusiveTotalAmount": "total_with_tax",  # 价税合计
    "Item": "item_name",
    "TaxScheme": "tax_rate",
}

# OFD.xml CustomDatas 中文名 → comparable 字段名（常见别名都收录）
CUSTOMDATA_TO_FIELD = {
    "发票号码": "invoice_number",
    "开票日期": "issue_date",
    "购买方纳税人识别号": "buyer_tax_id",
    "购买方识别号": "buyer_tax_id",
    "销售方纳税人识别号": "seller_tax_id",
    "销售方识别号": "seller_tax_id",
    "合计金额": "amount",
    "合计税额": "tax_amount",
    "价税合计": "total_with_tax",
    "价税合计金额": "total_with_tax",
}

# 全部可比字段（与 diff_engine.COMPARABLE_FIELDS 对齐）
ALL_FIELDS = [
    "invoice_number", "invoice_code", "check_code", "issue_date",
    "buyer_name", "buyer_tax_id", "seller_name", "seller_tax_id",
    "item_name", "total_with_tax", "amount", "tax_amount", "tax_rate",
]


def _local(tag: str) -> str:
    """去掉命名空间：{http://...}Name → Name"""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _clean_amount(val: Optional[str]) -> Optional[str]:
    """金额清洗：¥471.70 → 471.70；已是 471.70 则原样返回"""
    if not val:
        return None
    s = str(val).replace("¥", "").replace("￥", "").replace("Y", "").strip()
    m = re.search(r"\d+\.?\d*", s)
    return m.group(0) if m else None


def _normalize_date(val: Optional[str]) -> Optional[str]:
    """日期标准化：2025年11月24日 → 2025-11-24；2025-11-24 → 原样"""
    if not val:
        return None
    m = re.search(r"(\d{4})\D*(\d{1,2})\D*(\d{1,2})", str(val))
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return str(val).strip() or None


def _normalize_tax_rate(val: Optional[str]) -> Optional[str]:
    """税率标准化：6 → 6%；6% → 6%；13% → 13%"""
    if not val:
        return None
    s = str(val).strip().replace("％", "%")
    if "%" in s:
        return s
    m = re.search(r"(\d+\.?\d*)", s)
    return f"{m.group(0)}%" if m else None


class OfdParser:
    """OFD 发票解析器（纯 Python，零外部依赖）"""

    def parse(self, file_data: bytes) -> dict:
        """解析 OFD bytes

        Returns:
            {
                "full_text": str,                # 所有页面 TextCode 文字拼接（兜底全文）
                "fields": dict[str, str|None],   # 13 个 comparable 字段
                "image_bytes": bytes | None,     # 最大图片资源（扫描件/印章兜底用）
            }
        """
        result = {"full_text": "", "fields": {f: None for f in ALL_FIELDS}, "image_bytes": None}
        if not file_data:
            return result

        try:
            zf = zipfile.ZipFile(BytesIO(file_data))
        except zipfile.BadZipFile as e:
            logger.error(f"OFD 不是有效 ZIP 包: {e}")
            return result

        names = zf.namelist()
        fields = result["fields"]

        # ===== L1: OFD.xml CustomDatas（数电票元数据优先）=====
        self._extract_custom_datas(zf, fields)

        # ===== 定位 Document.xml =====
        doc_root_path = self._find_doc_root(zf)
        if not doc_root_path:
            doc_root_path = next((n for n in names if n.endswith("/Document.xml") or n == "Document.xml"), None)
        doc_dir = doc_root_path.rsplit("/", 1)[0] if (doc_root_path and "/" in doc_root_path) else ""

        # ===== 解析 Document.xml，收集页面与模板页 =====
        page_paths, tpl_paths = [], []
        if doc_root_path:
            page_paths, tpl_paths = self._parse_document(zf, doc_root_path, doc_dir)

        # ===== 解析所有 Content.xml（模板页在前，主页在后）=====
        # 模板页含固定标签（"发票号码："等），主页含数据值；拼接顺序保证正则可命中
        content_paths = tpl_paths + page_paths
        id_to_text: dict[str, str] = {}
        all_text_segments: list[str] = []
        for cp in content_paths:
            text_by_id, texts = self._parse_content(zf, cp)
            for k, v in text_by_id.items():
                id_to_text.setdefault(k, v)
            all_text_segments.extend(texts)

        # ===== L2: CustomTag.xml ID→语义映射，结构化提取字段 =====
        custom_tag_path = self._find_custom_tag_path(zf, doc_dir)
        if custom_tag_path:
            tag_id_map = self._parse_custom_tag(zf, custom_tag_path)
            self._apply_tag_to_fields(tag_id_map, id_to_text, fields)

        # ===== L3: 全文拼接（兜底 + 供分类器/正则使用）=====
        full_text = "\n".join(all_text_segments)
        result["full_text"] = full_text

        # ===== 正则补齐 invoice_code（OFD 数电票一般无，但兼容传统 OFD）=====
        if not fields.get("invoice_code"):
            m = re.search(r"发票代码[:：\s]*(\d{10,12})", full_text)
            if m:
                fields["invoice_code"] = m.group(1)

        # ===== 统一字段清洗（L1 原始值也需标准化）=====
        if fields.get("issue_date"):
            fields["issue_date"] = _normalize_date(fields["issue_date"])
        if fields.get("tax_rate"):
            fields["tax_rate"] = _normalize_tax_rate(fields["tax_rate"])
        for af in ("total_with_tax", "amount", "tax_amount"):
            if fields.get(af):
                cleaned = _clean_amount(fields[af])
                if cleaned:
                    fields[af] = cleaned

        # ===== 图片资源提取（兜底用：扫描件式 OFD 或印章）=====
        result["image_bytes"] = self._extract_main_image(zf, names)

        logger.info(
            f"OFD 解析完成: invoice_number={fields.get('invoice_number')}, "
            f"seller={fields.get('seller_name')}, total={fields.get('total_with_tax')}, "
            f"text_len={len(full_text)}"
        )
        return result

    # ===== L1: CustomDatas =====
    def _extract_custom_datas(self, zf: zipfile.ZipFile, fields: dict) -> None:
        try:
            root = ET.fromstring(zf.read("OFD.xml"))
        except (KeyError, ET.ParseError) as e:
            logger.warning(f"解析 OFD.xml 失败: {e}")
            return
        for el in root.iter():
            if _local(el.tag) != "CustomData":
                continue
            name = el.get("Name", "")
            val = (el.text or "").strip()
            if not name or not val:
                continue
            # 精确匹配 + 包含匹配（兼容"价税合计(小写)"等变体）
            field = CUSTOMDATA_TO_FIELD.get(name)
            if not field:
                for key, fld in CUSTOMDATA_TO_FIELD.items():
                    if key in name:
                        field = fld
                        break
            if field and val and not fields.get(field):
                fields[field] = val

    def _find_doc_root(self, zf: zipfile.ZipFile) -> Optional[str]:
        try:
            root = ET.fromstring(zf.read("OFD.xml"))
        except (KeyError, ET.ParseError):
            return None
        for el in root.iter():
            if _local(el.tag) == "DocRoot":
                return (el.text or "").strip()
        return None

    # ===== Document.xml =====
    def _parse_document(self, zf: zipfile.ZipFile, doc_path: str, doc_dir: str):
        page_paths, tpl_paths = [], []
        try:
            root = ET.fromstring(zf.read(doc_path))
        except (KeyError, ET.ParseError) as e:
            logger.warning(f"解析 Document.xml 失败: {e}")
            return page_paths, tpl_paths
        for el in root.iter():
            tag = _local(el.tag)
            base = (el.get("BaseLoc") or "").strip()
            if not base:
                continue
            full = f"{doc_dir}/{base}" if doc_dir else base
            if tag == "Page":
                page_paths.append(full)
            elif tag == "TemplatePage":
                tpl_paths.append(full)
        return page_paths, tpl_paths

    # ===== Content.xml：提取 ID→text 与全文 =====
    def _parse_content(self, zf: zipfile.ZipFile, content_path: str):
        text_by_id: dict[str, str] = {}
        texts: list[str] = []
        try:
            root = ET.fromstring(zf.read(content_path))
        except (KeyError, ET.ParseError):
            return text_by_id, texts
        for el in root.iter():
            if _local(el.tag) != "TextObject":
                continue
            obj_id = el.get("ID")
            if not obj_id:
                continue
            parts = [
                sub.text for sub in el.iter()
                if _local(sub.tag) == "TextCode" and sub.text
            ]
            text = "".join(parts).strip()
            if text:
                text_by_id[obj_id] = text
                texts.append(text)
        return text_by_id, texts

    # ===== CustomTag.xml：ID→语义映射 =====
    def _find_custom_tag_path(self, zf: zipfile.ZipFile, doc_dir: str) -> Optional[str]:
        candidates = []
        if doc_dir:
            candidates.append(f"{doc_dir}/Tags/CustomTag.xml")
        candidates.append("Doc_0/Tags/CustomTag.xml")
        for c in candidates:
            try:
                zf.getinfo(c)
                return c
            except KeyError:
                continue
        return None

    def _parse_custom_tag(self, zf: zipfile.ZipFile, tag_path: str) -> dict:
        """递归解析 CustomTag.xml，返回 {标签名: [ObjectRef ID 列表]}"""
        tag_id_map: dict[str, list[str]] = {}
        try:
            root = ET.fromstring(zf.read(tag_path))
        except (KeyError, ET.ParseError) as e:
            logger.warning(f"解析 CustomTag.xml 失败: {e}")
            return tag_id_map

        def walk(el):
            tag = _local(el.tag)
            # 收集直接子 ObjectRef（保持出现顺序）
            ids = [
                child.text.strip()
                for child in el
                if _local(child.tag) == "ObjectRef" and child.text and child.text.strip()
            ]
            if ids:
                tag_id_map.setdefault(tag, []).extend(ids)
            for child in el:
                if _local(child.tag) != "ObjectRef":
                    walk(child)

        walk(root)
        return tag_id_map

    def _apply_tag_to_fields(self, tag_id_map: dict, id_to_text: dict, fields: dict) -> None:
        for tag, ids in tag_id_map.items():
            field = TAG_TO_FIELD.get(tag)
            if not field or fields.get(field):
                continue  # 已有值（L1 优先）或非目标字段
            parts = [id_to_text.get(i, "") for i in ids]
            raw = "".join(p for p in parts if p).strip()
            if not raw:
                continue
            # 按字段类型清洗
            if field in ("total_with_tax", "amount", "tax_amount"):
                cleaned = _clean_amount(raw)
            elif field == "issue_date":
                cleaned = _normalize_date(raw)
            elif field == "tax_rate":
                cleaned = _normalize_tax_rate(raw)
            else:
                cleaned = raw
            if cleaned and not fields.get(field):
                fields[field] = cleaned

    # ===== 图片资源 =====
    def _extract_main_image(self, zf: zipfile.ZipFile, names: list) -> Optional[bytes]:
        """提取最大的图片资源作为主图（兜底用：扫描件 OFD 或发票印章）"""
        img_exts = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
        best, best_size = None, 0
        for n in names:
            if n.lower().endswith(img_exts):
                try:
                    data = zf.read(n)
                except KeyError:
                    continue
                if len(data) > best_size and len(data) > 500:
                    best, best_size = data, len(data)
        return best


# ===== 单例 =====
_ofd_parser: Optional[OfdParser] = None


def get_ofd_parser() -> OfdParser:
    global _ofd_parser
    if _ofd_parser is None:
        _ofd_parser = OfdParser()
    return _ofd_parser
