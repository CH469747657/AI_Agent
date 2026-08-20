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

# 常见日期正则模式（按优先级排序：长格式优先，避免短格式误匹配）
_DATE_PATTERNS = [
    # YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD
    re.compile(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})'),
    # YYYY年M月D日/号
    re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]'),
    # YYYY年M月D（不带日/号）
    re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})(?![日号月])'),
    # YYYYMMDD 紧凑 8 位
    re.compile(r'(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)'),
    # M月D日/号（补当前年）
    re.compile(r'(\d{1,2})月(\d{1,2})[日号]'),
    # M月D（不带日/号，补当前年，要求 D≤31 且后非数字避免误匹配"8月9号"的"9"被吞）
    re.compile(r'(\d{1,2})月(\d{1,2})(?![日号月\d])'),
    # M-D 或 M/D 或 M.D（补当前年，要求月份1-12）
    # 排除金额（后跟元/块/毛/分）和编号（前跟编号/序号/号）
    re.compile(r'(?<![\d编号序号])(\d{1,2})[-/.](\d{1,2})(?![\d元块毛分号])'),
]

# 中文数字映射（用于"八月九日"等中文日期）
_CN_DIGIT = {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
             '十一':11,'十二':12,'二十':20,'二十一':21,'二十二':22,'二十三':23,'二十四':24,
             '二十五':25,'二十六':26,'二十七':27,'二十八':28,'二十九':29,'三十':30,'三十一':31,
             '初一':1,'初二':2,'初三':3,'初四':4,'初五':5,'初六':6,'初七':7,'初八':8,'初九':9,'初十':10}
_CN_MONTH_DAY = {v:k for k,v in _CN_DIGIT.items() if 1<=v<=31}

# 中文日期正则：M月D日/号（中文数字）
_CN_DATE_PATTERN = re.compile(r'([一二两三四五六七八九十]+)月([一二两三四五六七八九十]+)[日号]')


def _cn_to_int(s: str) -> Optional[int]:
    """中文数字转 int（支持 一~三十一、初一~初十）"""
    if not s:
        return None
    if s in _CN_DIGIT:
        return _CN_DIGIT[s]
    # 处理"十几""二十几"组合：十一/十二.../二十/二十一...
    if s.startswith('十'):
        if len(s) == 1:
            return 10
        v = _CN_DIGIT.get(s[1])
        return 10 + v if v else None
    if s.startswith('二十') or s.startswith('三十'):
        base = 20 if s.startswith('二十') else 30
        if len(s) == 2:
            return base
        v = _CN_DIGIT.get(s[2])
        return base + v if v else None
    return None


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

    # 中文数字日期兜底（如"八月九日""十月一日"）
    if not candidates:
        for m in _CN_DATE_PATTERN.finditer(str(text)):
            mo = _cn_to_int(m.group(1))
            d = _cn_to_int(m.group(2))
            if mo and d and 1 <= mo <= 12 and 1 <= d <= 31:
                try:
                    parsed = date(today.year, mo, d)
                    if parsed <= today:
                        candidates.append(parsed)
                    else:
                        candidates.append(date(today.year - 1, mo, d))
                except ValueError:
                    continue

    if not candidates:
        return None

    return min(candidates)  # 取最早日期（保守归属）


def extract_date_and_purpose(text: str, today: date | None = None) -> tuple[Optional[date], str]:
    """从用户描述提取日期 + 剩余纯用途文本

    用于上传时拆分"8月9号 项目投标费" → (2026-08-09, "项目投标费")
    返回 (date, remaining_text)；无日期返回 (None, 原文)
    """
    if not text or not str(text).strip():
        return None, ""
    today = today or date.today()
    s = str(text)

    # 遍历模式找第一个匹配的日期子串，从原文移除后返回剩余
    for pattern in _DATE_PATTERNS:
        m = pattern.search(s)
        if m:
            try:
                groups = m.groups()
                if len(groups) == 3:
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                elif len(groups) == 2:
                    y, mo, d = today.year, int(groups[0]), int(groups[1])
                else:
                    continue
                parsed = date(y, mo, d)
                if parsed > today:
                    parsed = date(y - 1, mo, d)
                # 从原文移除匹配的日期子串 + 前后多余空格/分隔符
                remaining = (s[:m.start()] + s[m.end():]).strip()
                # 清理前后残留分隔符
                remaining = re.sub(r'^[\s,，、|/:-]+|[\s,，、|/:-]+$', '', remaining)
                return parsed, remaining
            except ValueError:
                continue

    # 中文数字日期兜底（如"八月九日 餐饮费"）
    m = _CN_DATE_PATTERN.search(s)
    if m:
        mo = _cn_to_int(m.group(1))
        d = _cn_to_int(m.group(2))
        if mo and d and 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                parsed = date(today.year, mo, d)
                if parsed > today:
                    parsed = date(today.year - 1, mo, d)
                remaining = (s[:m.start()] + s[m.end():]).strip()
                remaining = re.sub(r'^[\s,，、|/:-]+|[\s,，、|/:-]+$', '', remaining)
                return parsed, remaining
            except ValueError:
                pass

    return None, s.strip()


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
    """判定费用发生日期（优先用户备注，不使用发票开票日期）

    测试场景多用老发票，issue_date 可能是几年前，不代表费用发生时间。
    费用明细日期应以用户上传时备注的日期为准；无备注时用上传时间兜底。

    Returns: (date, source) — source 为 note/upload_time
    """
    today = today or date.today()

    # ── Level 1: 用户备注时间 ──
    note_text = _collect_note_text(inv)
    d = parse_note_date(note_text, today)
    if d:
        logger.debug(f"Invoice #{inv.id} expense_date=note ({d}) from: {note_text[:80]}")
        return (d, "note")

    # ── Level 2: 上传时间兜底 ──
    d = _as_local_date(inv.created_at)
    return (d, "upload_time")
