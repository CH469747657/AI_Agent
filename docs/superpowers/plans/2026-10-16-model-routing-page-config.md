# 模型路由页面化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `get_model_for_task` 优先读管理页配置（DB 覆写的 `llm_model`/`llm_text_model`），AgentCore 支持模型热更新——设置页改模型后全部六类任务立即生效，无需重启。

**Architecture:** 三处小改：(1) `config.py get_model_for_task` 在现有三层链路前插入"页面配置"层（`invoice_ocr` 读 `settings.llm_model`，文本任务读 `settings.llm_text_model`）；(2) `agent_core.py` 仿照 `llm_nlu.py` 的模式改为按 model 缓存 client、每次调用解析模型；(3) `routers/settings.py` 保存后追加 `reset_agent_core()`。

**Tech Stack:** Python 3.10 / FastAPI / Pydantic Settings / pytest（在 docker 容器内运行，本地 pydantic 版本不兼容）

**Spec:** `docs/superpowers/specs/2026-10-16-model-routing-page-config-design.md`

## Global Constraints

- 测试必须在 docker 容器内运行：`docker exec ai-reimbursement-agent-backend-1 python -m pytest ...`（本地 macOS python3.13 的 pydantic 版本不兼容，会报 `extra_forbidden`）
- 改动 `backend/app/` 下代码后，容器内代码是旧的（镜像构建，未挂载源码）——验证需 `docker cp` 同步文件进容器或重建镜像
- 不改 `.env` 的六个 `LLM_*_MODEL` 变量（保留为第二优先级灰度手段）
- 不动 `backend/tests/test_model_routing.py`（整个文件 pre-existing skip，修复不在本任务范围）
- 提交信息用中文，风格参照 `git log`（如 `feat: 切换 LLM 网关 + Agent 模式表格强制输出`）

---

### Task 1: get_model_for_task 页面配置优先层

**Files:**
- Modify: `backend/app/config.py:93-109`（`get_model_for_task` 方法）
- Test: `backend/tests/test_model_page_priority.py`（新建）

**Interfaces:**
- Consumes: `settings.llm_model`（str，DB 可覆写）、`settings.llm_text_model`（str，DB 可覆写，可为空串）
- Produces: `get_model_for_task(task_type) -> str`，新优先级：页面配置 > 环境变量 > MODEL_ROUTING > 兜底。后续任务（Task 2 AgentCore）通过 `settings.get_model_for_task("insight_narrate")` 消费

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_model_page_priority.py`：

```python
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
        settings.llm_text_model = ""
        os.environ["LLM_OCR_MODEL"] = "env-ocr"
        assert settings.get_model_for_task("invoice_ocr") == "env-ocr"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_model_page_priority.py -v --no-header
```

预期：`TestPageConfigPriority` 3 个用例 FAIL（当前环境变量优先级最高）；`TestPageConfigEmpty`/`TestBackwardCompat` 可能 PASS（旧逻辑已满足）

注意：容器内还没有新测试文件，先同步：

```bash
docker cp backend/tests/test_model_page_priority.py ai-reimbursement-agent-backend-1:/app/tests/
docker cp backend/app/config.py ai-reimbursement-agent-backend-1:/app/app/
```

（同步 config.py 是为了让容器内的 `tests/` import 与本地一致；此时尚未实现新逻辑，两份代码相同）

- [ ] **Step 3: 实现 get_model_for_task 页面优先层**

修改 `backend/app/config.py:93-109`，替换整个 `get_model_for_task` 方法：

```python
    def get_model_for_task(self, task_type: str) -> str:
        """根据任务类型获取对应模型名（分层模型路由）

        优先级：
        1. 页面配置（settings.llm_model / llm_text_model，由管理页 DB 覆写）
           - invoice_ocr 用 llm_model（视觉模型）
           - 其他任务用 llm_text_model（文本模型），留空则跳过本层
        2. 环境变量 LLM_<SHORT>_MODEL（如 LLM_NLU_MODEL）— 灰度切换
        3. MODEL_ROUTING[task_type] — 默认路由表
        4. 兜底：invoice_ocr 用 llm_model（Vision），其他用 text_model
        """
        # 1. 页面配置（DB 覆写的 settings 字段）
        if task_type == "invoice_ocr":
            if self.llm_model.strip():
                return self.llm_model.strip()
        elif self.llm_text_model.strip():
            return self.llm_text_model.strip()

        # 2. 环境变量
        env_var = _TASK_ENV_MAP.get(task_type)
        if env_var:
            env_val = os.getenv(env_var, "").strip()
            if env_val:
                return env_val

        # 3. 默认路由表
        routing = MODEL_ROUTING.get(task_type)
        if routing:
            return routing

        # 4. 兜底
        return self.llm_model if task_type == "invoice_ocr" else self.text_model
```

- [ ] **Step 4: 同步并运行测试确认通过**

```bash
docker cp backend/app/config.py ai-reimbursement-agent-backend-1:/app/app/
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_model_page_priority.py -v --no-header
```

预期：11 passed

- [ ] **Step 5: 回归现有路由测试**

```bash
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/ -q --no-header -k "routing or config or settings"
```

预期：无新失败（test_model_routing.py 整文件 pre-existing skip 不受影响）

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/tests/test_model_page_priority.py
git commit -m "feat(config): get_model_for_task 优先读管理页配置的 llm_model/llm_text_model"
```

---

### Task 2: AgentCore 按模型缓存客户端 + 热更新

**Files:**
- Modify: `backend/app/dialog/agent_core.py:77-109`（`__init__` + `_ensure_client`）、`:130-134`（`run()` 的 client 检查）、`:556-588`（`_call_llm`）
- Test: `backend/tests/test_agent_hot_reload.py`（新建）

**Interfaces:**
- Consumes: `settings.get_model_for_task("insight_narrate")`（Task 1 产出）、`settings.llm_api_key`、`settings.llm_base_url`
- Produces: `AgentCore._resolve_model() -> str`；`AgentCore._clients: dict[str, OpenAI]`（按 model 缓存）；`reset_agent_core()`（已有，行为不变：置空单例）。Task 3 在 settings 保存后调用 `reset_agent_core()`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_agent_hot_reload.py`：

```python
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
```

- [ ] **Step 2: 同步测试进容器并运行确认失败**

```bash
docker cp backend/tests/test_agent_hot_reload.py ai-reimbursement-agent-backend-1:/app/tests/
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_agent_hot_reload.py -v --no-header
```

预期：FAIL（`AgentCore` 无 `_resolve_model`/`_clients` 属性，`AttributeError`）

- [ ] **Step 3: 改造 AgentCore**

修改 `backend/app/dialog/agent_core.py`：

3a. 替换 `__init__` 和 `_ensure_client`（77-109 行）：

```python
    def __init__(self):
        self._clients: dict[str, Any] = {}  # model → OpenAI client（按模型缓存，支持热更新）
        self._role_gate = RoleGate()

    def _resolve_model(self) -> str:
        """解析当前应使用的模型名（每次调用都读，支持页面配置热更新）"""
        from app.config import settings
        return settings.get_model_for_task("insight_narrate")

    def _ensure_client(self):
        """确保当前模型的 LLM 客户端存在（按 model 缓存，仿照 LlmNlu._ensure_client）

        页面改模型后下次调用自动用新模型新建 client；旧 client 保留复用不销毁。
        """
        model = self._resolve_model()
        if model in self._clients:
            return
        try:
            from app.config import settings, LLM_PROVIDERS
            from openai import OpenAI

            base_url = settings.llm_base_url
            if not base_url:
                provider = settings.llm_provider.lower()
                provider_info = LLM_PROVIDERS.get(provider, {})
                base_url = provider_info.get("base_url", "")

            self._clients[model] = OpenAI(
                api_key=settings.llm_api_key,
                base_url=base_url,
            )
            logger.info("AgentCore client created for model=%s", model)
        except Exception as e:
            logger.warning("Failed to init AgentCore client for %s: %s", model, e)
```

3b. 修改 `run()` 中的 client 检查（原 129-134 行）：

```python
        self._ensure_client()
        model = self._resolve_model()
        if model not in self._clients:
            return AgentResponse(
                text="Agent 模式不可用：LLM 客户端未初始化",
                error="client_unavailable",
            )
```

3c. 修改 `_call_llm`（原 556 行起），接受 model 参数并更新错误日志：

```python
    async def _call_llm(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
        """调用 LLM（带 tools）"""
        try:
            resp = await asyncio.to_thread(
                self._clients[model].chat.completions.create,
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1000,
                timeout=self.TIMEOUT_SECONDS,
            )

            choice = resp.choices[0].message
            tool_calls = []
            if choice.tool_calls:
                for tc in choice.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })

            return {
                "content": choice.content or "",
                "tool_calls": tool_calls,
            }
        except Exception as e:
            logger.error("AgentCore _call_llm error (model=%s): %s", model, e)
            return {}
```

同步修改 `run()` 循环里的调用点（原 163-166 行）：

```python
                llm_result = await asyncio.wait_for(
                    self._call_llm(model, messages, tool_schemas),
                    timeout=self.TIMEOUT_SECONDS,
                )
```

注意：`run()` 里取 `model` 的位置在 client 检查之后（3b 步骤已定义局部变量 `model`），循环内直接使用。

- [ ] **Step 4: 同步并运行测试确认通过**

```bash
docker cp backend/app/dialog/agent_core.py ai-reimbursement-agent-backend-1:/app/app/dialog/
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_agent_hot_reload.py -v --no-header
```

预期：6 passed

- [ ] **Step 5: 全量回归**

```bash
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/ -q --no-header
```

预期：与基线一致（138 passed，无新失败）

- [ ] **Step 6: Commit**

```bash
git add backend/app/dialog/agent_core.py backend/tests/test_agent_hot_reload.py
git commit -m "feat(agent): AgentCore 按 model 缓存客户端，支持页面改模型热更新"
```

---

### Task 3: 设置保存后重置 AgentCore + 真实环境端到端验证

**Files:**
- Modify: `backend/app/routers/settings.py:85-90`（`_apply_settings_to_config` 尾部）
- Modify: `frontend/src/pages/Settings.tsx:356-358`（文本模型帮助文案，可选）
- Test: 容器内交互验证（无新测试文件）

**Interfaces:**
- Consumes: `reset_agent_core()`（Task 2 产出，模块级函数）
- Produces: 无（端到端行为：PUT /api/settings/llm 后智能问数立即用新模型）

- [ ] **Step 1: 修改 `_apply_settings_to_config`**

在 `backend/app/routers/settings.py` 的 `_apply_settings_to_config` 尾部（现有 `reset_client()` 块之后）追加：

```python
        # 重置 AgentCore 单例，下次智能问数用新模型
        try:
            from app.dialog.agent_core import reset_agent_core
            reset_agent_core()
        except Exception as e:
            logger.warning("Failed to reset AgentCore: %s", e)
```

- [ ] **Step 2: 更新前端帮助文案（可选）**

`frontend/src/pages/Settings.tsx:387` 附近的文案：

```tsx
            <p className="text-xs text-muted-foreground">
              用于意图识别、Agent 推理、费用分类、批量描述；留空时服务端会从视觉模型名自动推导
            </p>
```

- [ ] **Step 3: 同步代码进容器并重启**

```bash
docker cp backend/app/routers/settings.py ai-reimbursement-agent-backend-1:/app/app/routers/
docker cp backend/app/dialog/agent_core.py ai-reimbursement-agent-backend-1:/app/app/dialog/
docker cp backend/app/config.py ai-reimbursement-agent-backend-1:/app/app/
docker-compose restart backend
```

等待健康检查：

```bash
for i in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/health --max-time 5 2>/dev/null)
  [ "$code" = "200" ] && echo "healthy" && break
  sleep 5
done
```

- [ ] **Step 4: 端到端验证热更新（不重启切模型）**

```bash
# 1. 登录取 token
TOKEN=$(curl -s -X POST http://localhost:18080/api/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"123456"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# 2. 页面路径保存文本模型 = qwen-plus
curl -s -X PUT http://localhost:18080/api/settings/llm \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"llm_text_model":"qwen-plus"}'

# 3. 立即调智能问数（不重启后端）
curl -s -X POST http://localhost:18080/api/dialog/message \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","text":"公司报销总额是多少","role":"admin"}' --max-time 60

# 4. 验证日志显示新模型
docker-compose logs backend --since 1m 2>&1 | grep "AgentCore" | tail -3
```

预期：日志出现 `AgentCore client created for model=qwen-plus`，且智能问数正常返回（非"Agent 未返回有效响应"）

```bash
# 5. 改回 qwen3.7-plus 再验证一次（确认可来回切换）
curl -s -X PUT http://localhost:18080/api/settings/llm \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"llm_text_model":"qwen3.7-plus"}'
curl -s -X POST http://localhost:18080/api/dialog/message \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","text":"公司各部门费用情况","role":"admin"}' --max-time 60
docker-compose logs backend --since 1m 2>&1 | grep "AgentCore client created" | tail -2
```

预期：第二条 `AgentCore client created for model=qwen3.7-plus` 出现

- [ ] **Step 5: 浏览器端设置页验证**

用 Playwright 打开 http://localhost:13000 → admin/123456 登录 → 设置页 → 确认文本模型字段显示当前值、帮助文案更新 → 保存 → 智能问数正常。

验证脚本（保存为 /tmp/verify_settings_page.py 后运行）：

```python
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('http://localhost:13000/', timeout=30000)
    page.wait_for_load_state('networkidle')
    page.fill('input[placeholder*="用户名"], input[type="text"]', 'admin')
    page.fill('input[type="password"]', '123456')
    page.click('button:has-text("登录")')
    page.wait_for_load_state('networkidle')

    page.goto('http://localhost:13000/settings')
    page.wait_for_load_state('networkidle')
    body = page.inner_text('body')
    assert '文本模型' in body, 'Settings page missing text model field'
    assert 'Agent 推理' in body, 'Help text not updated'
    print('Settings page OK')

    # 智能问数回归
    ta = page.locator('textarea[data-testid="chat-input"]')
    ta.click()
    page.keyboard.insert_text('公司报销总额是多少')
    time.sleep(0.3)
    ta.press('Enter')
    for i in range(45):
        time.sleep(2)
        body = page.inner_text('body')
        if '推理中' in body:
            continue
        time.sleep(1)
        assert '暂无报销' in page.inner_text('body') or '报销' in body
        print('Smart Q&A OK')
        break
    browser.close()
```

预期输出：`Settings page OK` + `Smart Q&A OK`

- [ ] **Step 6: 全量回归测试**

```bash
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/ -q --no-header
```

预期：基线 + 新增测试全过（138 + 17 passed 左右，无失败）

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/settings.py frontend/src/pages/Settings.tsx
git commit -m "feat(settings): 保存 LLM 配置后重置 AgentCore，页面改模型即时生效"
```

- [ ] **Step 8: 收尾 — 持久化到镜像（与用户确认后执行）**

当前容器内的代码是 `docker cp` 临时同步的，重建容器会丢失。需重建镜像固化：

```bash
docker-compose build backend && docker-compose up -d backend
```

注意：重建后重跑 Step 4 的端到端验证（模型应为 qwen3.7-plus）。此步骤影响运行中的服务，执行前告知用户。

---

## Self-Review 结论

- **Spec 覆盖**：设计 4 个改动点 → Task 1（优先级）、Task 2（热更新）、Task 3（reset + 文案 + E2E）、错误日志升级含在 Task 2 Step 3c。无遗漏
- **占位符**：无 TBD/TODO，所有步骤含完整代码
- **类型一致性**：`_resolve_model() -> str`、`_clients: dict[str, Any]`、`_call_llm(model, messages, tools)` 在 Task 2/3 间一致；Task 3 消费 Task 2 的 `reset_agent_core()`
- **测试基线**：138 passed / 223 skipped（均 pre-existing）；新测试预期 11 + 6 = 17 个
