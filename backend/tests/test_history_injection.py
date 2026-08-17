"""历史注入与 ContextResolver 精简测试 — Step 2.2.5

覆盖：
- DialogContext.get_history_summary 输出格式与边界
- LlmNlu 缓存 key 含 history_hash（跨历史隔离）
- ContextResolver 精简后行为：
  - 场景A（LLM 未识别 + 省略句式）仍触发继承
  - 场景B（同意图槽位补全）已删除，不再默默补全
- is_query_intent / detect_ellipsis 辅助函数行为不变
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.dialog.models import (
    DialogContext, DialogState, UserRole, NluResult, NluLevel,
)


# ============================================================
# get_history_summary
# ============================================================

class TestGetHistorySummary:
    """Step 2.2.1/2.2.2：历史摘要生成"""

    def test_empty_history_returns_empty_string(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        assert ctx.get_history_summary() == ""

    def test_single_turn_summary(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        ctx.add_history(
            intent="insight_total",
            slots={"period": "current_month"},
            text="我花了多少",
        )
        s = ctx.get_history_summary()
        assert "T-1" in s  # 单轮 → T-1
        assert "insight_total" in s
        assert "current_month" in s
        assert "[当前状态] state=idle" in s

    def test_multi_turn_summary_labels(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        ctx.add_history(intent="insight_person", slots={"person": "陈辉"}, text="查陈辉")
        ctx.add_history(intent="insight_category_amount", slots={"fee_category_keyword": "差旅"}, text="差旅费")
        ctx.add_history(intent="insight_trend", slots={}, text="趋势")
        s = ctx.get_history_summary()
        assert "T-3" in s and "T-2" in s and "T-1" in s

    def test_max_turns_limit(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        for i in range(5):
            ctx.add_history(intent=f"intent_{i}", slots={}, text=f"text_{i}")
        s = ctx.get_history_summary(max_turns=3)
        # 只应包含最近 3 轮
        assert "intent_2" in s and "intent_3" in s and "intent_4" in s
        assert "intent_0" not in s and "intent_1" not in s

    def test_empty_slot_values_filtered(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        ctx.add_history(
            intent="x",
            slots={"a": "value", "b": "", "c": None, "d": "ok"},
            text="t",
        )
        s = ctx.get_history_summary()
        assert "a:value" in s and "d:ok" in s
        assert "b:" not in s and "c:" not in s  # 空值过滤

    def test_current_intent_included(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        ctx.add_history(intent="x", slots={}, text="t")
        ctx.current_intent = "emp_upload_invoice"
        s = ctx.get_history_summary()
        assert "[当前意图] current_intent=emp_upload_invoice" in s

    def test_long_values_truncated(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        long_val = "A" * 100
        ctx.add_history(intent="x", slots={"k": long_val}, text="t")
        s = ctx.get_history_summary()
        # 值应被截断到 30 字符 + "..."
        assert "..." in s
        assert long_val not in s

    def test_max_tokens_truncation(self):
        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        # 加 10 轮超长历史
        for i in range(10):
            ctx.add_history(
                intent=f"intent_{i}",
                slots={"k": "v" * 50},
                text=f"text_{i}" * 20,
            )
        s = ctx.get_history_summary(max_turns=10, max_tokens=100)
        # 应被截断
        assert len(s) <= 250  # 100 tokens * ~2 chars + 余量
        assert "..." in s or "省略" in s


# ============================================================
# LlmNluCache history_hash 隔离
# ============================================================

class TestCacheHistoryIsolation:
    """Step 2.2.3：缓存 key 含 history_hash"""

    def setup_method(self):
        os.environ.pop("LLM_NLU_MODEL", None)

    def test_same_text_different_history_isolated(self):
        from app.dialog.llm_nlu import LlmNluCache
        from app.dialog.models import NluResult, NluLevel

        cache = LlmNluCache(ttl=60)
        text, role, model = "交通费呢", "employee", "qwen-turbo"

        r1 = NluResult(
            intent_name="insight_category_amount", confidence=0.9,
            level=NluLevel.L3_LLM, raw_text=text, extracted_slots={},
        )
        r2 = NluResult(
            intent_name="self_insight_category_amount", confidence=0.85,
            level=NluLevel.L3_LLM, raw_text=text, extracted_slots={},
        )

        cache.set(text, role, r1, model, history_hash="hash_a")
        cache.set(text, role, r2, model, history_hash="hash_b")

        got_a = cache.get(text, role, model, history_hash="hash_a")
        got_b = cache.get(text, role, model, history_hash="hash_b")
        got_empty = cache.get(text, role, model, history_hash="")

        assert got_a is not None and got_a.intent_name == "insight_category_amount"
        assert got_b is not None and got_b.intent_name == "self_insight_category_amount"
        assert got_empty is None, "empty history_hash should not hit other hashes"

    def test_empty_history_hash_backward_compat(self):
        """无历史时 history_hash="" 仍可正常 get/set"""
        from app.dialog.llm_nlu import LlmNluCache
        from app.dialog.models import NluResult, NluLevel

        cache = LlmNluCache(ttl=60)
        r = NluResult(
            intent_name="x", confidence=0.9,
            level=NluLevel.L3_LLM, raw_text="t", extracted_slots={},
        )
        cache.set("t", "employee", r, "qwen-turbo", history_hash="")
        got = cache.get("t", "employee", "qwen-turbo", history_hash="")
        assert got is not None and got.intent_name == "x"

    def test_default_ttl_is_120s(self):
        """Step 2.2.3：TTL 从 300s 缩短到 120s"""
        from app.dialog.llm_nlu import LlmNluCache
        assert LlmNluCache.DEFAULT_TTL == 120


# ============================================================
# ContextResolver 精简后行为
# ============================================================

class TestContextResolverSimplified:
    """Step 2.2.4：场景B删除，场景A保留"""

    def test_scenario_a_ellipsis_inherit_still_works(self):
        """场景A：LLM 未识别 + 省略句式 → 继承上轮意图"""
        from app.dialog.context_resolver import resolve, detect_ellipsis, is_query_intent

        # 省略句式检测
        assert detect_ellipsis("交通费呢") is True
        assert detect_ellipsis("今年呢") is True
        assert detect_ellipsis("查张三的报销") is False  # 非省略

        # is_query_intent
        assert is_query_intent("insight_total") is True
        assert is_query_intent("self_insight_total") is True
        assert is_query_intent("emp_query_status") is True
        assert is_query_intent("emp_upload_invoice") is False

    def test_scenario_b_removed(self):
        """场景B已删除：当前轮识别查询意图时，不再默默补全槽位"""
        from app.dialog.context_resolver import resolve
        from app.dialog.models import NluResult, NluLevel, DialogContext, UserRole

        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        ctx.add_history(
            intent="insight_person",
            slots={"person": "陈辉", "period": "last_month"},
            text="查陈辉上月报销",
        )

        # 当前轮识别了同意图但缺 person 槽位
        nlu = NluResult(
            intent_name="insight_person",
            confidence=0.9,
            level=NluLevel.L3_LLM,
            raw_text="查李四的报销",
            extracted_slots={"period": "current_month"},  # 缺 person
        )

        result = resolve(nlu, ctx, "查李四的报销")
        # 场景B已删除：不再默默从历史补全 person=陈辉
        assert "person" not in result.extracted_slots, \
            f"scenario B should be removed, but person was inherited: {result.extracted_slots}"
        # 当前轮明确提供的 period 仍在
        assert result.extracted_slots.get("period") == "current_month"

    def test_scenario_a_ellipsis_no_intent_inherits_last(self):
        """场景A：LLM 未识别 + 省略句式 → 继承上轮意图 + 槽位"""
        from app.dialog.context_resolver import resolve
        from app.dialog.models import NluResult, NluLevel, DialogContext, UserRole

        ctx = DialogContext(user_id="test", role=UserRole.EMPLOYEE)
        ctx.add_history(
            intent="insight_category_amount",
            slots={"fee_category_keyword": "差旅", "period": "last_month"},
            text="差旅费花了多少",
        )

        # 当前轮 LLM 未识别（空 intent），但省略句式
        nlu = NluResult(
            intent_name="",  # 未识别
            confidence=0.0,
            level=NluLevel.L3_LLM,
            raw_text="交通费呢",
            extracted_slots={},
        )

        result = resolve(nlu, ctx, "交通费呢")
        # 场景A 触发：继承上轮 intent + 可继承槽位
        assert result.intent_name == "insight_category_amount", \
            f"scenario A should inherit last intent, got {result.intent_name}"
        assert result.confidence >= 0.85  # 降级后略降置信度


# ============================================================
# LlmNlu user message 含历史摘要
# ============================================================

class TestUserMessageContainsHistory:
    """Step 2.2.3：LLM user message 注入历史摘要"""

    def test_user_message_with_history(self):
        """验证 _call_llm_classify 构造的 user message 含历史摘要"""
        import inspect
        from app.dialog.llm_nlu import LlmNlu

        src = inspect.getsource(LlmNlu._call_llm_classify)
        assert "get_history_summary" in src, "history summary not injected"
        assert "history_summary" in src
        print("[1] _call_llm_classify injects history_summary OK")

    def test_classify_uses_history_hash_in_cache(self):
        """验证 classify 方法使用 history_hash 做 cache key"""
        import inspect
        from app.dialog.llm_nlu import LlmNlu

        src = inspect.getsource(LlmNlu.classify)
        assert "history_hash" in src, "history_hash not used in classify"
        assert "history_hash" in src
        print("[2] classify uses history_hash OK")
