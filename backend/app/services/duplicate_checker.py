"""发票查重服务（三级查重策略）

参考项目: mattpodulak/duplicate-img-detection (35⭐) pHash + 最近邻搜索
技术路线:
  Level 1: 精确查重 — 发票号码+发票代码 唯一索引
  Level 2: 模糊查重 — 金额+日期+销售方 组合查询
  Level 3: 图像查重 — 感知哈希(pHash) 检测PS/裁剪过的重复票据
"""

import logging
from io import BytesIO
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, DuplicateStatus

logger = logging.getLogger(__name__)

# pHash Hamming 距离阈值，小于此值视为相似图片
# 发票是高度模板化图像，同类型发票版式的 pHash 距离天然很小（4~8），
# 阈值需严格控制在 3 以内，仅匹配近全等同图（重扫描/重截图），
# 同时配合 _has_matching_field 交叉验证防止同模板误判。
PHASH_HAMMING_THRESHOLD = 3


def compute_phash(file_data: bytes, file_type: str = "") -> str | None:
    """计算图片的感知哈希值

    对图片轻微修改（裁剪/压缩/PS）仍能匹配
    参考: imagehash 库 phash
    """
    try:
        from PIL import Image
        import imagehash

        if file_type.lower() == "pdf":
            from pdf2image import convert_from_bytes
            images = convert_from_bytes(file_data, dpi=150, first_page=1, last_page=1)
            if not images:
                return None
            img = images[0]
        elif file_type.lower() == "ofd":
            from app.services.ofd_parser import get_ofd_parser
            parsed = get_ofd_parser().parse(file_data)
            img_bytes = parsed.get("image_bytes")
            if not img_bytes:
                return None
            img = Image.open(BytesIO(img_bytes))
        else:
            img = Image.open(BytesIO(file_data))

        return str(imagehash.phash(img))
    except Exception as e:
        logger.error(f"pHash computation failed: {e}")
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """计算两个哈希值的 Hamming 距离（按比特位 XOR）

    pHash 返回的是十六进制字符串，必须转为整数后按位计算：
    'f' vs 'e' 真实差异 = 1 位（1111 ^ 1110 = 0001），
    而非按字符比较的 1。字符比较会导致距离值偏小、阈值意义失真。
    """
    try:
        n1 = int(hash1, 16)
        n2 = int(hash2, 16)
        return bin(n1 ^ n2).count("1")
    except (ValueError, TypeError):
        return 64


class DuplicateChecker:
    """三级查重服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check(self, invoice_data: dict, file_data: bytes, file_type: str = "", current_invoice_id: int = None) -> dict:
        """
        执行三级查重

        Returns:
        {
            "is_duplicate": bool,
            "level": str,           # exact / fuzzy / image / none
            "matched_invoice_id": int | None,
            "details": dict,
        }
        """
        # Level 1: 精确查重（发票号码+代码）
        exact_match = await self._check_exact(invoice_data, current_invoice_id)
        if exact_match:
            logger.warning(f"Exact duplicate found: invoice #{exact_match.id}")
            return {
                "is_duplicate": True,
                "level": "exact",
                "matched_invoice_id": exact_match.id,
                "details": {"invoice_number": invoice_data.get("invoice_number")},
            }

        # Level 2: 模糊查重（金额+日期+销售方）
        fuzzy_matches = await self._check_fuzzy(invoice_data, current_invoice_id)
        if fuzzy_matches:
            logger.warning(f"Fuzzy duplicate found: {len(fuzzy_matches)} matches")
            return {
                "is_duplicate": True,
                "level": "fuzzy",
                "matched_invoice_id": fuzzy_matches[0].id,
                "details": {"match_count": len(fuzzy_matches)},
            }

        # Level 3: 图像哈希查重（附加交叉验证，防止同模板不同发票误判）
        img_hash = compute_phash(file_data, file_type)
        if img_hash:
            image_match = await self._check_image_hash(img_hash, invoice_data, current_invoice_id)
            if image_match:
                logger.warning(f"Image duplicate found: invoice #{image_match.id}")
                return {
                    "is_duplicate": True,
                    "level": "image",
                    "matched_invoice_id": image_match.id,
                    "details": {"image_hash": img_hash},
                }

        return {
            "is_duplicate": False,
            "level": "none",
            "matched_invoice_id": None,
            "details": {"image_hash": img_hash},
        }

    async def _check_exact(self, invoice_data: dict, exclude_id: int = None) -> Invoice | None:
        """Level 1: 发票号码+代码精确查重

        有发票代码时：号码+代码双字段匹配
        无发票代码时（数电票）：仅号码匹配
        """
        invoice_number = invoice_data.get("invoice_number")
        if not invoice_number:
            return None

        invoice_code = invoice_data.get("invoice_code", "") or ""

        conditions = [
            Invoice.invoice_number == invoice_number,
            Invoice.id != exclude_id if exclude_id else True,
        ]
        # 有发票代码时，要求代码也一致
        if invoice_code:
            conditions.append(Invoice.invoice_code == invoice_code)

        query = select(Invoice).where(*conditions)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _check_fuzzy(self, invoice_data: dict, exclude_id: int = None) -> list[Invoice]:
        """Level 2: 金额+日期+销售方模糊查重"""
        amount = invoice_data.get("total_with_tax")
        date = invoice_data.get("issue_date")
        seller = invoice_data.get("seller_name")

        if not amount or not date:
            return []

        conditions = [
            Invoice.total_with_tax == amount,
            Invoice.issue_date == date,
        ]
        if seller:
            conditions.append(Invoice.seller_name == seller)

        query = select(Invoice).where(
            *conditions,
            Invoice.id != exclude_id if exclude_id else True,
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _check_image_hash(self, img_hash: str, invoice_data: dict, exclude_id: int = None) -> Invoice | None:
        """Level 3: 图像感知哈希查重

        附加交叉验证：pHash 匹配后，需至少一个业务字段（销方/金额/日期）
        也一致才确认重复，防止同模板不同发票因版式相似而误判。
        """
        query = select(Invoice).where(
            Invoice.image_hash.isnot(None),
            Invoice.id != exclude_id if exclude_id else True,
        )
        result = await self.db.execute(query)
        for inv in result.scalars().all():
            if inv.image_hash and hamming_distance(img_hash, inv.image_hash) <= PHASH_HAMMING_THRESHOLD:
                if self._has_matching_field(invoice_data, inv):
                    return inv
                logger.info(
                    f"pHash match with #{inv.id} (distance={hamming_distance(img_hash, inv.image_hash)}) "
                    f"but all business fields differ, skipping (template similarity)"
                )
        return None

    @staticmethod
    def _has_matching_field(invoice_data: dict, matched: Invoice) -> bool:
        """交叉验证：当前发票与 pHash 匹配发票是否至少两个业务字段相同

        仅匹配一个字段（如金额 500.00）太容易撞车，改为要求至少两个字段一致。
        发票号码一致则直接判重（发票号具有唯一标识性）。
        """
        current_number = invoice_data.get("invoice_number")
        current_seller = invoice_data.get("seller_name")
        current_amount = invoice_data.get("total_with_tax")
        current_date = invoice_data.get("issue_date")

        # 发票号码一致 → 直接判重（发票号具有唯一标识性）
        if current_number and matched.invoice_number and current_number == matched.invoice_number:
            return True

        # 统计匹配字段数
        match_count = 0

        if current_seller and matched.seller_name and current_seller == matched.seller_name:
            match_count += 1
        if current_amount is not None and matched.total_with_tax is not None:
            try:
                if float(current_amount) == float(matched.total_with_tax):
                    match_count += 1
            except (ValueError, TypeError):
                pass
        if current_date and matched.issue_date and current_date == matched.issue_date:
            match_count += 1

        return match_count >= 2
