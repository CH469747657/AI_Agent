"""页面配置优先级测试 — 管理页设置的模型优先于环境变量和 MODEL_ROUTING

优先级（spec: 2026-10-16-model-routing-page-config-design.md）：
1. 页面配置（settings.llm_model / llm_text_model，DB 覆写）
2. 环境变量 LLM_<SHORT>_MODEL
3. MODEL_ROUTING 硬编码
4. 兜底 text_model / llm_model
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.config import settings, MODEL_ROUTING, _TASK_ENV_MAP


@pytest.fixture(autouse=True)
def clean_env_and_settings():
    """每个测试前：清空路由环境变量 + 保存/恢复 settings 字段"""
    saved = (settings.llm_model, settings.llm_text_model)
    for env_var in _TASK_ENV_MAP.values():
        os.environ.pop(env_var, None)
    yield
    settings.llm_model, settings.llm_text_model = saved
    for env_var in _TASK_ENV_MAP.values():
        os.environ.pop(env_var, None)


class TestPageConfigPriority:
    """页面配置（DB 覆写字段）优先于一切"""

    def test_text_model_page_config_wins_for_text_tasks(self):
        settings.llm_text_model = "page-model-x"
        assert settings.get_model_for_task("nlu_classify") == "page-model-x"
        assert settings.get_model_for_task("insight_narrate") == "page-model-x"

    def test_text_model_page_config_wins_over_env(self):
        settings.llm_text_model = "page-model-x"
        os.environ["LLM_NARRATE_MODEL"] = "env-model"
        assert settings.get_model_for_task("insight_narrate") == "page-model-x"

    def test_vision_model_page_config_wins_for_ocr(self):
        settings.llm_model = "page-vision-x"
        os.environ["LLM_OCR_MODEL"] = "env-model"
        assert settings.get_model_for_task("invoice_ocr") == "page-vision-x"


class TestPageConfigEmpty:
    """页面留空时回落到环境变量 / MODEL_ROUTING（与旧行为兼容）"""

    def test_empty_text_model_falls_to_env(self):
        settings.llm_text_model = ""
        os.environ["LLM_NLU_MODEL"] = "env-model"
        assert settings.get_model_for_task("nlu_classify") == "env-model"

    def test_empty_text_model_falls_to_routing(self):
        settings.llm_text_model = ""
        assert settings.get_model_for_task("nlu_classify") == MODEL_ROUTING["nlu_classify"]

    def test_whitespace_text_model_treated_as_empty(self):
        settings.llm_text_model = "   "
        assert settings.get_model_for_task("fee_classify") == MODEL_ROUTING["fee_classify"]


class TestBackwardCompat:
    """未知 task_type 兜底与 OCR 主路径行为不变"""

    def test_unknown_task_falls_back_to_text_model(self):
        assert settings.get_model_for_task("nonexistent") == settings.text_model

    def test_env_override_still_works_when_page_empty(self):
        # invoice_ocr 的页面配置层读 llm_model，需一并清空才能模拟"页面留空"
        settings.llm_model = ""
        settings.llm_text_model = ""
        os.environ["LLM_OCR_MODEL"] = "env-ocr"
        assert settings.get_model_for_task("invoice_ocr") == "env-ocr"
