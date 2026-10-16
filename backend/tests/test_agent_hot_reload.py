"""AgentCore 模型热更新测试 — 设置页改模型后无需重启即生效"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.config import settings
from app.dialog.agent_core import AgentCore, reset_agent_core, get_agent_core
from app.config import _TASK_ENV_MAP


@pytest.fixture(autouse=True)
def clean_state():
    saved = (settings.llm_model, settings.llm_text_model)
    for env_var in _TASK_ENV_MAP.values():
        os.environ.pop(env_var, None)
    yield
    settings.llm_model, settings.llm_text_model = saved
    for env_var in _TASK_ENV_MAP.values():
        os.environ.pop(env_var, None)
    reset_agent_core()


class TestResolveModel:
    def test_resolve_model_reads_routing_each_call(self):
        core = AgentCore()
        settings.llm_text_model = "page-m1"
        assert core._resolve_model() == "page-m1"
        settings.llm_text_model = "page-m2"
        assert core._resolve_model() == "page-m2"

    def test_resolve_model_env_fallback(self):
        settings.llm_text_model = ""
        os.environ["LLM_NARRATE_MODEL"] = "env-m"
        core = AgentCore()
        assert core._resolve_model() == "env-m"


class TestClientCache:
    def test_ensure_client_caches_by_model(self):
        core = AgentCore()
        settings.llm_text_model = "model-a"
        core._ensure_client()
        assert "model-a" in core._clients

        settings.llm_text_model = "model-b"
        core._ensure_client()
        assert "model-b" in core._clients
        assert len(core._clients) == 2  # model-a 的 client 仍缓存（复用不泄漏）

    def test_same_model_reuses_client(self):
        core = AgentCore()
        settings.llm_text_model = "model-a"
        core._ensure_client()
        c1 = core._clients["model-a"]
        core._ensure_client()
        assert core._clients["model-a"] is c1


class TestSingletonReset:
    def test_reset_agent_core_creates_fresh_instance(self):
        a = get_agent_core()
        a._clients["stale"] = object()
        reset_agent_core()
        b = get_agent_core()
        assert b is not a
        assert b._clients == {}
