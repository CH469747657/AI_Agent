"""费用发生日期判定引擎

三级优先（命中即停）：
  Level 1: 备注时间 — user_description / receipt_detail.remark / 明细说明 中解析出明确日期
  Level 2: 凭证识别日期 — 发票类取 issue_date；非标支付凭证取 receipt_detail 中交易日期
  Level 3: 上传时间 — created_at 转 UTC+8 当地日期

source 枚举值：note / issue_date / receipt_date / upload_time
"""

import re
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from app.models.invoice import Invoice

logger = logging.getLogger(__name__)

# 发票类票据（有票面日期的凭证）
INVOICE_TYPED = {"增值税普通发票", "增值税专用发票", "火车票", "机票"}

# 非标票据 receipt_detail 中可能的交易日期字段
_TRADE_DATE_KEYS = ("transaction_time", "transaction_date", "trade_date", "trade_time")

# 时区：遵循中国习惯 UTC+8
TZ_OFFSET = 8


# ============================================================
# Level 1: 备注时间解析
# ============================================================

# 常见日期正则模式（按优先级排序）
_DATE_PATTERNS = [
    # YYYY-MM-DD / YYYY/MM/DD
    re.compile(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})'),
    # YYYY年M月D日
    re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日'),
    # M月D日（补当前年）
    re.compile(r'(\d{1,2})月(\d{1,2})日'),
    # M-D 或 M/D（补当前年，要求月份1-12）
    re.compile(r'(?<!\d)(\d{1,2})[-/](\d{1,2})(?!\d)'),
]


def parse_note_date(text: str, today: date | None = None) -> Optional[date]:
    """从备注/描述文本中解析日期

    正则优先匹配常见日期写法。一个备注解析出多个日期时取最早一个（保守归属）。
    """
    if not text or not str(text).strip():
        return None

    today = today or date.today()
    candidates: list[date] = []

    for pattern in _DATE_PATTERNS:
        matches = pattern.findall(str(text))
        for m in matches:
            try:
                if len(m) == 3:
                    # YYYY-MM-DD 或 YYYY年M月D日
                    y, mo, d = int(m[0]), int(m[1]), int(m[2])
                elif len(m) == 2:
                    # M月D日 或 M-D（补当前年）
                    y, mo, d = today.year, int(m[0]), int(m[1])
                else:
                    continue
                parsed = date(y, mo, d)
                # 防止未来日期（明显错误）
                if parsed <= today:
                    candidates.append(parsed)
                else:
                    # 可能是去年同月日
                    candidates.append(date(y - 1, mo, d))
            except (ValueError, IndexError):
                continue
        if candidates:
            # 正则命中即不再用后面的宽泛模式，避免误匹配
            break

    if not candidates:
        return None

    return min(candidates)  # 取最早日期（保守归属）


def _collect_note_text(inv: Invoice) -> str:
    """收集发票相关的所有备注/描述文本"""
    parts = [inv.user_description or ""]

    # 非标票据的 receipt_detail 中可能有 remark/note/description 字段
    if inv.receipt_detail and isinstance(inv.receipt_detail, dict):
        for key in ("remark", "note", "description", "memo"):
            val = inv.receipt_detail.get(key)
            if val:
                parts.append(str(val))

    return " ".join(p for p in parts if p)


# ============================================================
# Level 2: 凭证识别日期
# ============================================================

def _parse_date_str(s: str | None) -> Optional[date]:
    """解析日期字符串（支持 YYYY-MM-DD、YYYY/MM/DD、YYYY年M月D日 等）"""
    if not s or not str(s).strip():
        return None
    s = str(s).strip()

    # 尝试常见格式
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    # 正则兜底
    m = re.match(r'(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def _parse_receipt_trade_date(receipt_detail: dict | None) -> Optional[date]:
    """从非标票据 receipt_detail 中提取交易日期"""
    if not receipt_detail or not isinstance(receipt_detail, dict):
        return None

    for key in _TRADE_DATE_KEYS:
        val = receipt_detail.get(key)
        if val:
            d = _parse_date_str(str(val))
            if d:
                return d
    return None


# ============================================================
# Level 3: 上传时间
# ============================================================

def _as_local_date(dt: datetime) -> date:
    """把带时区的 datetime 转为 UTC+8 当地日期"""
    if dt is None:
        return date.today()
    from datetime import timezone, timedelta
    if dt.tzinfo is None:
        # 假设已是 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(hours=TZ_OFFSET)).date() if dt.tzinfo == timezone.utc else dt.astimezone(timezone(timedelta(hours=TZ_OFFSET))).date()


# ============================================================
# 统一入口：三级判定
# ============================================================

def determine_expense_date(inv: Invoice, today: date | None = None) -> tuple[Optional[date], str]:
    """三级优先判定费用发生日期

    Returns: (date, source) — source 为 note/issue_date/receipt_date/upload_time
    """
    today = today or date.today()

    # ── Level 1: 备注时间 ──
    note_text = _collect_note_text(inv)
    d = parse_note_date(note_text, today)
    if d:
        logger.debug(f"Invoice #{inv.id} expense_date=note ({d}) from: {note_text[:80]}")
        return (d, "note")

    # ── Level 2: 凭证识别日期 ──
    receipt_type_val = inv.receipt_type.value if inv.receipt_type else ""
    if receipt_type_val in INVOICE_TYPED:
        d = _parse_date_str(inv.issue_date)
        if d:
            return (d, "issue_date")
    else:
        d = _parse_receipt_trade_date(inv.receipt_detail)
        if d:
            return (d, "receipt_date")

    # ── Level 3: 上传时间兜底 ──
    d = _as_local_date(inv.created_at)
    return (d, "upload_time")
