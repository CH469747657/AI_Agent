# 模型路由页面化设计 — get_model_for_task 优先读管理页配置

日期：2026-10-16
状态：已批准（方案 A）

## 背景与问题

自建网关 `aigw.telecomjs.com` 会静默下线模型（2026-10 下线了 `qwen3-max`、`vlt_mm_31_vis`）。模型失效时报误导性的 Key Auth 错误，导致智能问数不可用。

当前模型路由三层链路（`config.py:93 get_model_for_task`）：

```
环境变量 LLM_<SHORT>_MODEL  >  MODEL_ROUTING 硬编码  >  兜底 text_model
```

管理页设置（DB `system_settings` → 运行时覆写 `settings.llm_model/llm_text_model`）**只影响**发票 OCR 主路径（`llm_service.py` 直接读 `settings.llm_model`），管不到走 `get_model_for_task` 的 Agent/NLU/分类/批量路径。用户在页面改模型名对智能问数无效。

另外 `agent_core.py:85` 的单例客户端初始化一次后缓存模型，即使路由改对了，页面改模型后智能问数也要重启后端才生效。

## 目标

网关再换模型时，管理员在设置页改"视觉模型/文本模型"两个字段即可让**全部六类任务**立即生效，无需改代码、改 env、重启容器。

## 设计

### 1. get_model_for_task 优先级调整（config.py）

新优先级：

```
1. 页面配置（settings 上被 DB 覆写的字段）
   - invoice_ocr → settings.llm_model（非空时）
   - 其他任务   → settings.llm_text_model（非空时）
2. 环境变量 LLM_<SHORT>_MODEL（.env / 容器环境）
3. MODEL_ROUTING 硬编码默认值
4. 兜底：invoice_ocr → llm_model，其他 → text_model
```

页面留空（`llm_text_model=""`）时回落到 env/代码默认值，与现状行为兼容。

`llm_model` 默认值 `qwen3-vl-plus` 非空，意味着 OCR 永远命中第 1 层 —— 这正确，因为页面本来就该管 OCR 模型（`.env` 的 `LLM_MODEL` 也会作为 settings.llm_model 初始值，行为不变）。

### 2. AgentCore 热更新（agent_core.py）

仿照 `llm_nlu.py:534` 的模式改造 `_ensure_client`：

- 客户端按 model 缓存：`self._clients: dict[str, OpenAI]`
- 每次调用前 `_resolve_model()` 读 `settings.get_model_for_task("insight_narrate")`
- 返回的 model 不在 `_clients` 中则新建 client；已存在则复用
- `run()` 中移除对 `self._model` 的缓存依赖，`_call_llm` 接受当前 model 参数

### 3. 保存后重置 AgentCore（routers/settings.py）

`_apply_settings_to_config` 在现有 `get_llm_nlu().reset_client()` 之后追加：

```python
from app.dialog.agent_core import reset_agent_core
reset_agent_core()
```

### 4. 前端

无改动。设置页已有"视觉模型（用于发票 OCR 识别）"和"文本模型（用于意图识别、项目提取）"字段。仅更新文本模型的帮助文案，注明它同时作用于 Agent 推理/费用分类/批量描述。

## 错误处理

- 模型名填错（网关 401/403）：AgentCore 现有降级不变（`empty_response` 文本提示 + 日志真实错误）。本次顺手把 `_call_llm` 的 `logger.warning` 提升为 `logger.error` 并附模型名，方便下次排查"页面改错了模型"的场景
- 页面留空：回落 env → MODEL_ROUTING，行为与改造前一致

## 测试计划

1. 单元测试：`get_model_for_task` 优先级矩阵（页面值/env 值/都空 × invoice_ocr/文本任务 共 6 个用例）
2. 单元测试：`_apply_settings_to_config` 后 `reset_agent_core` 被调用、AgentCore 下次 `run()` 用新模型
3. 集成验证（真实环境）：设置页把文本模型改成 `qwen-plus` → 保存 → 智能问数立即用新模型（看日志 `AgentCore initialized: model=qwen-plus`）→ 不重启后端
4. 回归：现有 138 个后端测试全过；智能问数/上传发票/费用分类端到端正常

## 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/app/config.py` | `get_model_for_task` 加页面配置优先层 |
| `backend/app/dialog/agent_core.py` | client 按 model 缓存 + 每次解析模型 |
| `backend/app/routers/settings.py` | 保存后 `reset_agent_core()` |
| `frontend/src/pages/Settings.tsx` | 仅帮助文案（可选） |

## 不做的事（YAGNI）

- 不加每任务独立字段（NLU 与 Agent 共用文本模型）
- 不做模型可用性探测（保存时自动调网关验证）——留待后续
- 不动 `.env` 六个 `LLM_*_MODEL` 变量（降为第二优先级，作为灰度手段保留）
