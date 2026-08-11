"""Context Resolver — 对话上下文继承层

在 LLM NLU 之后、Role Gate/FSM 之前运行，为当前轮注入历史上下文，
解决多轮对话中「答非所问」的核心痛点。

三种继承策略：
1. 省略意图继承：识别「XX呢？」「换成XX」「今年呢」等省略句式，
   继承上一轮查询意图的全部可继承槽位，再用当前轮提取的槽位覆盖。
   典型：查张三上月差旅费 → 交通费呢？→ 张三上月交通费
2. 同意图槽位补全：当前轮识别了查询意图且与上轮相同，
   从历史补全当前轮未提供的可继承槽位（如 period）。
   典型：上月公司总额 → 今年总额（period 已提供，不补）/ 查李四费用（period 缺失，补上月）
3. （预留）指代消解：识别「这张/那个/上一个」等指代词，从历史 referents 注入实体

设计原则：
- 纯槽位继承，不改写 LLM prompt，不破坏响应缓存
- 仅查询/洞察类意图参与跨轮继承（提单、审批操作不继承）
- 继承是"补全"而非"覆盖"：当前轮明确提供的槽位始终优先
- 强实体（person/project_name 等）跨意图不继承，避免污染
"""

from __future__ import annotations

import re
import logging

from .models import (
    DialogContext, NluResult, NluLevel,
    OVERRIDABLE_SLOT_NAMES,
)

logger = logging.getLogger(__name__)


# ============================================================
# 查询类意图判定
# ============================================================

# 查询/洞察类意图前缀 — 仅这些意图参与跨轮继承
_QUERY_PREFIXES = (
    "insight_", "self_insight_",
    "emp_query_", "admin_query_", "admin_export",
)

# 强实体槽位 — 跨意图继承风险高，仅"同意图"时才补全
_STRONG_ENTITY_SLOTS = frozenset({
    "person", "project_name", "department",
    "reimbursement_id", "invoice_id",
})


def is_query_intent(intent_name: str) -> bool:
    """判断是否为查询类意图（参与跨轮继承）"""
    return bool(intent_name) and any(
        intent_name.startswith(p) for p in _QUERY_PREFIXES
    )


# ============================================================
# 省略意图检测
# ============================================================

# 省略句式正则 — 特征：短语 + 语气词，省略了主语/谓语，意图靠前文
_ELLIPSIS_PATTERNS: list[re.Pattern] = [
    # "交通费呢" "今年呢？" "高风险的呢" "李四的情况呢"
    re.compile(r"^(.{1,10}?)呢[？?？]*$"),
    # "差旅费怎么样" "张三怎么样"
    re.compile(r"^(.{1,10}?)怎么样[？?？]*$"),
    # "换成高风险的" "改成今年的"
    re.compile(r"^换成(.{1,12})[？?？]*$"),
    re.compile(r"^改成(.{1,12})[？?？]*$"),
    # "再来一次" "还有吗" "再看看"
    re.compile(r"^(再|还有|再看看|再来).{0,6}[呢吗？?？]*$"),
]


def detect_ellipsis(text: str) -> bool:
    """检测是否为省略意图句式"""
    text = (text or "").strip()
    if not text or len(text) > 20:
        return False
    for pattern in _ELLIPSIS_PATTERNS:
        if pattern.search(text):
            return True
    return False


# ============================================================
# 指代词检测（预留 — 本期暂不启用实体注入）
# ============================================================

_REFERENT_PATTERN = re.compile(r"(这|那|上一|刚)(张|个|条|份)")


def has_referent(text: str) -> bool:
    """检测文本是否包含指代词"""
    return bool(_REFERENT_PATTERN.search(text or ""))


# ============================================================
# 上下文继承主入口
# ============================================================

def resolve(
    nlu_result: NluResult,
    context: DialogContext,
    text: str,
) -> NluResult:
    """上下文继承主入口

    在 LLM NLU 之后调用，根据对话历史补全或继承上下文。
    不会降低已有意图的置信度，只做槽位补全与省略意图继承。
    返回新的 NluResult 对象，不修改入参。

    Args:
        nlu_result: 当前轮 NLU 结果（可能已识别意图+槽位，也可能为空）
        context: 对话上下文（含 history）
        text: 用户原始输入

    Returns:
        继承上下文后的 NluResult
    """
    last = context.last_history()
    if not last:
        return nlu_result  # 无历史，不继承

    last_intent = last.get("intent", "")
    if not last_intent or not is_query_intent(last_intent):
        return nlu_result  # 上轮非查询类，不继承

    last_slots = last.get("slots", {}) or {}
    last_referents = last.get("referents", {}) or {}

    def _history_value(slot_name: str):
        """从历史取槽位值（referents 优先，slots 兜底）"""
        return last_referents.get(slot_name) or last_slots.get(slot_name)

    is_ellipsis = detect_ellipsis(text)

    # ===== 场景A：省略意图且当前轮未识别 → 强制继承上轮意图 + 可继承槽位 =====
    # 仅当 LLM 未识别出意图时才强制继承，避免与当前轮明确意图冲突
    # （如 "重复的发票呢" LLM 已识别 invoice_filter，不应强制继承上轮 total）
    if is_ellipsis and not nlu_result.intent_name:
        # 继承上轮所有可覆盖槽位
        inherited: dict = {}
        for slot_name in OVERRIDABLE_SLOT_NAMES:
            val = _history_value(slot_name)
            if val is not None:
                inherited[slot_name] = val

        # 从当前文本轻量提取实体（period/filter_type/fee_category_keyword）覆盖继承值
        # 解决 "今年呢" 继承上轮 last_month 却应取 current_year 的问题
        text_slots = _extract_referent_slots(text)
        if text_slots:
            inherited.update(text_slots)

        # LLM 已提取的槽位（即使意图未识别，槽位可能已提取）也覆盖
        if nlu_result.extracted_slots:
            inherited.update(nlu_result.extracted_slots)

        logger.info(
            "Context ellipsis inherit (no intent): text=%r last_intent=%s slots=%s",
            text[:40], last_intent, list(inherited.keys()),
        )
        return NluResult(
            intent_name=last_intent,
            confidence=max(nlu_result.confidence, 0.85),
            level=_bump_level(nlu_result.level),
            raw_text=text,
            extracted_slots=inherited,
        )

    # ===== 场景B：当前轮识别了查询意图 → 补全可继承槽位 =====
    current_intent = nlu_result.intent_name
    if current_intent and is_query_intent(current_intent):
        merged_slots = dict(nlu_result.extracted_slots)
        same_intent = (current_intent == last_intent)
        # 省略句式（"交通费呢"）是强延续信号，强实体也跨意图补全
        allow_strong_cross = is_ellipsis

        for slot_name in OVERRIDABLE_SLOT_NAMES:
            if slot_name in merged_slots:
                continue
            val = _history_value(slot_name)
            if val is None:
                continue
            # 强实体继承策略：
            # - person：换人查询是高频显式操作，同意图下不应默默继承，
            #   否则"陈辉有多少发票→全公司有多少发票"会被旧 person 污染。
            #   仅省略延续（"本月呢"等场景A）才补全 person。
            # - 其他强实体：仅"同意图"或"省略延续"时补全，避免跨意图污染
            if slot_name == "person":
                if not allow_strong_cross:
                    continue
            elif slot_name in _STRONG_ENTITY_SLOTS and not (same_intent or allow_strong_cross):
                continue
            # fee_category_keyword 跨意图补全需当前意图能消费
            if slot_name in ("fee_category_keyword", "fee_category_aliases"):
                if not _intent_accepts_slot(current_intent, slot_name):
                    continue
            merged_slots[slot_name] = val

        added = [k for k in merged_slots if k not in nlu_result.extracted_slots]
        if added:
            logger.info(
                "Context slot inherit: text=%r intent=%s same=%s ellipsis=%s inherited=[%s]",
                text[:40], current_intent, same_intent, is_ellipsis, ",".join(added),
            )
            return NluResult(
                intent_name=current_intent,
                confidence=nlu_result.confidence,
                level=nlu_result.level,
                raw_text=text,
                extracted_slots=merged_slots,
            )

    return nlu_result


# ============================================================
# 辅助
# ============================================================

# 接受费用分类槽位的意图（required 或 optional）
_CATEGORY_INTENTS = frozenset({
    "insight_category_amount", "self_insight_category_amount",
    "insight_by_category", "self_insight_category",
    "insight_person", "admin_query_person",
    "insight_invoice_filter", "self_insight_invoice_filter",
    "insight_anomaly",
})

# 省略句式中的轻量实体提取（LLM 未识别时的兜底）
_PERIOD_KEYWORDS = [
    ("今天", "today"), ("今日", "today"),
    ("昨天", "yesterday"), ("昨日", "yesterday"),
    ("本周", "current_week"), ("这周", "current_week"), ("这一周", "current_week"),
    ("上周", "last_week"), ("上一周", "last_week"),
    ("最近半年", "last_6_months"), ("近半年", "last_6_months"),
    ("最近一年", "last_12_months"), ("近一年", "last_12_months"),
    ("这个月", "current_month"), ("本月", "current_month"),
    ("上个月", "last_month"), ("上月", "last_month"),
    ("今年", "current_year"), ("去年", "last_year"),
]
_FILTER_KEYWORDS = [
    ("验真失败", "invalid"), ("高风险", "high_risk"),
    ("待审核", "pending"), ("重复", "duplicate"), ("收据", "receipt"),
]
_CATEGORY_KEYWORDS = ["差旅", "交通", "住宿", "餐饮", "培训", "快递", "办公", "投标", "运营"]


def _extract_referent_slots(text: str) -> dict:
    """从省略句式文本中轻量提取实体（period/filter_type/fee_category_keyword）

    仅在场景A（LLM 未识别意图）兜底使用，避免继承值覆盖用户明确表达。
    """
    slots: dict = {}
    for kw, val in _PERIOD_KEYWORDS:
        if kw in text:
            slots["period"] = val
            break
    for kw, val in _FILTER_KEYWORDS:
        if kw in text:
            slots["filter_type"] = val
            break
    for kw in _CATEGORY_KEYWORDS:
        if kw in text:
            slots["fee_category_keyword"] = kw
            break
    return slots


def _intent_accepts_slot(intent_name: str, slot_name: str) -> bool:
    """判断意图是否消费某槽位（用于跨意图补全时的安全过滤）"""
    if slot_name in ("fee_category_keyword", "fee_category_aliases"):
        return intent_name in _CATEGORY_INTENTS
    return True


def _bump_level(level: NluLevel) -> NluLevel:
    """省略继承后提升 NLU 等级标记（语义层而非纯关键词）"""
    if level == NluLevel.L1_KEYWORD:
        return NluLevel.L2_SEMANTIC
    return level
