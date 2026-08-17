"""分层模型路由单元测试 — Step 1.1.6

覆盖：
- MODEL_ROUTING 默认路由表完整性
- settings.get_model_for_task() 默认命中
- 环境变量覆盖优先级（LLM_<SHORT>_MODEL）
- 未知 task_type 兜底逻辑
- _TASK_ENV_MAP 与 MODEL_ROUTING 键一致
- LlmNluCache 跨模型缓存隔离
- LlmNlu 多 client 管理
"""

import os
import sys

# 确保能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.config import settings, MODEL_ROUTING, _TASK_ENV_MAP


# ============================================================
# 默认路由表完整性
# ============================================================

class TestModelRoutingTable:
    """MODEL_ROUTING 默认路由表静态检查"""

    def test_routing_table_has_all_expected_tasks(self):
        """6 类任务全部在路由表中"""
        expected_tasks = {
            "nlu_classify", "fee_classify", "project_extract",
            "invoice_ocr", "insight_narrate", "batch_describe",
        }
        assert set(MODEL_ROUTING.keys()) == expected_tasks

    def test_routing_table_models_non_empty(self):
        """所有默认模型名非空"""
        for task, model in MODEL_ROUTING.items():
            assert model, f"task {task} has empty model"

    def test_invoice_ocr_uses_vision_model(self):
        """invoice_ocr 必须路由到 VL 模型（含 -vl 标记）"""
        assert "vl" in MODEL_ROUTING["invoice_ocr"].lower(), \
            f"invoice_ocr should use VL model, got {MODEL_ROUTING['invoice_ocr']}"

    def test_task_env_map_keys_match_routing(self):
        """_TASK_ENV_MAP 与 MODEL_ROUTING 键完全一致"""
        assert set(_TASK_ENV_MAP.keys()) == set(MODEL_ROUTING.keys())

    def test_task_env_map_values_non_empty(self):
        """所有环境变量名非空且符合 LLM_<X>_MODEL 命名约定"""
        for task, env_var in _TASK_ENV_MAP.items():
            assert env_var.startswith("LLM_") and env_var.endswith("_MODEL"), \
                f"task {task} env_var {env_var} violates naming convention"
            assert env_var != "LLM__MODEL", f"task {task} env_var is empty placeholder"


# ============================================================
# settings.get_model_for_task 默认命中
# ============================================================

class TestDefaultRouting:
    """无环境变量覆盖时，get_model_for_task 命中 MODEL_ROUTING"""

    def setup_method(self):
        """每个测试前清掉所有路由相关环境变量"""
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def test_nlu_classify_uses_fast_model(self):
        assert settings.get_model_for_task("nlu_classify") == MODEL_ROUTING["nlu_classify"]

    def test_fee_classify_uses_fast_model(self):
        assert settings.get_model_for_task("fee_classify") == MODEL_ROUTING["fee_classify"]

    def test_project_extract_uses_fast_model(self):
        assert settings.get_model_for_task("project_extract") == MODEL_ROUTING["project_extract"]

    def test_invoice_ocr_uses_vision_model(self):
        assert settings.get_model_for_task("invoice_ocr") == MODEL_ROUTING["invoice_ocr"]

    def test_insight_narrate_uses_strong_model(self):
        assert settings.get_model_for_task("insight_narrate") == MODEL_ROUTING["insight_narrate"]

    def test_batch_describe_uses_strong_model(self):
        assert settings.get_model_for_task("batch_describe") == MODEL_ROUTING["batch_describe"]


# ============================================================
# 环境变量覆盖优先级
# ============================================================

class TestEnvOverride:
    """LLM_<SHORT>_MODEL 环境变量优先于 MODEL_ROUTING"""

    def setup_method(self):
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def teardown_method(self):
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def test_nlu_model_env_overrides_default(self):
        os.environ["LLM_NLU_MODEL"] = "deepseek-chat"
        assert settings.get_model_for_task("nlu_classify") == "deepseek-chat"

    def test_narrate_model_env_overrides_default(self):
        os.environ["LLM_NARRATE_MODEL"] = "qwen-max"
        assert settings.get_model_for_task("insight_narrate") == "qwen-max"

    def test_ocr_model_env_overrides_default(self):
        os.environ["LLM_OCR_MODEL"] = "gpt-4o"
        assert settings.get_model_for_task("invoice_ocr") == "gpt-4o"

    def test_single_env_override_does_not_affect_others(self):
        """覆盖单个任务不影响其他任务的默认路由"""
        os.environ["LLM_NLU_MODEL"] = "deepseek-chat"
        assert settings.get_model_for_task("nlu_classify") == "deepseek-chat"
        # 其他任务仍走默认
        assert settings.get_model_for_task("fee_classify") == MODEL_ROUTING["fee_classify"]
        assert settings.get_model_for_task("batch_describe") == MODEL_ROUTING["batch_describe"]

    def test_empty_env_value_falls_back_to_default(self):
        """空字符串的环境变量视为未设置，走默认路由"""
        os.environ["LLM_NLU_MODEL"] = "   "
        assert settings.get_model_for_task("nlu_classify") == MODEL_ROUTING["nlu_classify"]

    def test_all_tasks_overridable(self):
        """6 类任务都可被环境变量覆盖"""
        overrides = {
            "LLM_NLU_MODEL":             "model-nlu",
            "LLM_FEE_CLASSIFY_MODEL":    "model-fee",
            "LLM_PROJECT_EXTRACT_MODEL": "model-project",
            "LLM_OCR_MODEL":             "model-ocr",
            "LLM_NARRATE_MODEL":         "model-narrate",
            "LLM_BATCH_MODEL":           "model-batch",
        }
        for env_var, val in overrides.items():
            os.environ[env_var] = val

        assert settings.get_model_for_task("nlu_classify") == "model-nlu"
        assert settings.get_model_for_task("fee_classify") == "model-fee"
        assert settings.get_model_for_task("project_extract") == "model-project"
        assert settings.get_model_for_task("invoice_ocr") == "model-ocr"
        assert settings.get_model_for_task("insight_narrate") == "model-narrate"
        assert settings.get_model_for_task("batch_describe") == "model-batch"


# ============================================================
# 未知 task_type 兜底
# ============================================================

class TestUnknownTaskFallback:
    """未知 task_type 兜底逻辑"""

    def setup_method(self):
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def test_unknown_task_falls_back_to_text_model(self):
        """未知任务兜底到 settings.text_model"""
        assert settings.get_model_for_task("nonexistent_task") == settings.text_model

    def test_empty_task_falls_back_to_text_model(self):
        assert settings.get_model_for_task("") == settings.text_model


# ============================================================
# LlmNluCache 跨模型缓存隔离
# ============================================================

class TestLlmNluCacheModelIsolation:
    """缓存 key 含 model 字段，避免跨模型污染"""

    def setup_method(self):
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def test_same_text_different_models_isolated(self):
        from app.dialog.llm_nlu import LlmNluCache
        from app.dialog.models import NluResult, NluLevel

        cache = LlmNluCache(ttl=60)
        text, role = "公司花了多少", "boss"

        r_turbo = NluResult(
            intent_name="insight_total", confidence=0.9,
            level=NluLevel.L3_LLM, raw_text=text, extracted_slots={},
        )
        r_plus = NluResult(
            intent_name="insight_by_dept", confidence=0.85,
            level=NluLevel.L3_LLM, raw_text=text, extracted_slots={},
        )

        cache.set(text, role, r_turbo, model="qwen-turbo")
        cache.set(text, role, r_plus, model="qwen-plus")

        got_turbo = cache.get(text, role, model="qwen-turbo")
        got_plus = cache.get(text, role, model="qwen-plus")
        got_other = cache.get(text, role, model="deepseek-chat")

        assert got_turbo is not None and got_turbo.intent_name == "insight_total"
        assert got_plus is not None and got_plus.intent_name == "insight_by_dept"
        assert got_other is None, "unrelated model should miss cache"

    def test_make_key_uniqueness_across_models(self):
        from app.dialog.llm_nlu import LlmNluCache

        cache = LlmNluCache()
        text, role = "测试", "employee"
        keys = {
            cache._make_key(text, role, "qwen-turbo"),
            cache._make_key(text, role, "qwen-plus"),
            cache._make_key(text, role, "deepseek-chat"),
            cache._make_key(text, role, ""),  # 空 model（向后兼容）
        }
        assert len(keys) == 4, f"keys not unique: {keys}"

    def test_backward_compat_no_model_arg(self):
        """不传 model 时仍可正常 get/set（向后兼容）"""
        from app.dialog.llm_nlu import LlmNluCache
        from app.dialog.models import NluResult, NluLevel

        cache = LlmNluCache(ttl=60)
        r = NluResult(
            intent_name="common_help", confidence=0.99,
            level=NluLevel.L1_KEYWORD, raw_text="帮助", extracted_slots={},
        )
        cache.set("帮助", "employee", r)
        got = cache.get("帮助", "employee")
        assert got is not None and got.intent_name == "common_help"

    def test_invalidate_all_clears_everything(self):
        from app.dialog.llm_nlu import LlmNluCache
        from app.dialog.models import NluResult, NluLevel

        cache = LlmNluCache(ttl=60)
        r = NluResult(
            intent_name="x", confidence=0.9,
            level=NluLevel.L3_LLM, raw_text="t", extracted_slots={},
        )
        cache.set("t", "employee", r, model="m1")
        cache.set("t", "employee", r, model="m2")

        count = cache.invalidate()
        assert count == 2
        assert cache.get("t", "employee", "m1") is None
        assert cache.get("t", "employee", "m2") is None

    def test_invalidate_single_entry_by_model(self):
        from app.dialog.llm_nlu import LlmNluCache
        from app.dialog.models import NluResult, NluLevel

        cache = LlmNluCache(ttl=60)
        r = NluResult(
            intent_name="x", confidence=0.9,
            level=NluLevel.L3_LLM, raw_text="t", extracted_slots={},
        )
        cache.set("t", "employee", r, model="m1")
        cache.set("t", "employee", r, model="m2")

        n = cache.invalidate("t", "employee", model="m1")
        assert n == 1
        assert cache.get("t", "employee", "m1") is None
        assert cache.get("t", "employee", "m2") is not None  # m2 仍在


# ============================================================
# LlmNlu 多 client 管理
# ============================================================

class TestLlmNluMultiClient:
    """LlmNlu 按 task_type 路由 + 多 client 复用"""

    def setup_method(self):
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def test_default_task_type_is_nlu_classify(self):
        from app.dialog.llm_nlu import LlmNlu
        nlu = LlmNlu()
        assert nlu._task_type == "nlu_classify"
        assert nlu._clients == {}
        assert nlu._initialized is False

    def test_custom_task_type(self):
        from app.dialog.llm_nlu import LlmNlu
        nlu = LlmNlu(task_type="batch_describe")
        assert nlu._task_type == "batch_describe"

    def test_resolve_model_matches_routing(self):
        from app.dialog.llm_nlu import LlmNlu
        assert LlmNlu()._resolve_model() == MODEL_ROUTING["nlu_classify"]
        assert LlmNlu(task_type="batch_describe")._resolve_model() == MODEL_ROUTING["batch_describe"]
        assert LlmNlu(task_type="invoice_ocr")._resolve_model() == MODEL_ROUTING["invoice_ocr"]

    def test_reset_client_clears_state(self):
        from app.dialog.llm_nlu import LlmNlu
        nlu = LlmNlu()
        nlu._clients["fake"] = object()
        nlu._initialized = True
        nlu.reset_client()
        assert nlu._clients == {}
        assert nlu._initialized is False

    def test_singleton_returns_same_instance(self):
        from app.dialog.llm_nlu import get_llm_nlu
        a = get_llm_nlu()
        b = get_llm_nlu()
        assert a is b
        assert a._task_type == "nlu_classify"  # 单例默认 task_type


# ============================================================
# 环境变量热更新（运行时切换 model）
# ============================================================

class TestRuntimeModelSwitch:
    """运行时修改环境变量后，下次 _resolve_model 立即生效"""

    def setup_method(self):
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def teardown_method(self):
        for env_var in _TASK_ENV_MAP.values():
            os.environ.pop(env_var, None)

    def test_env_change_reflects_on_next_call(self):
        from app.dialog.llm_nlu import LlmNlu
        nlu = LlmNlu()

        # 初始：默认 qwen-turbo
        assert nlu._resolve_model() == "qwen-turbo"

        # 运行时切换
        os.environ["LLM_NLU_MODEL"] = "gpt-4o-mini"
        assert nlu._resolve_model() == "gpt-4o-mini"

        # 切回
        del os.environ["LLM_NLU_MODEL"]
        assert nlu._resolve_model() == "qwen-turbo"
