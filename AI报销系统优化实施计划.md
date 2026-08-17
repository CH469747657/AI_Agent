# AI 报销智能体 — 项目更改与编码实施计划

> 基于《AI报销系统架构分析》的 5 条优化建议，转化为可执行的工程实施计划。
> 总周期：10 周（W1-W10），分三个阶段递进。
> 原则：**先快赢（降本提速）→ 再补认知（提升质量）→ 后升级架构（解锁能力）**。

---

## 0. 总体路线图

| 阶段 | 周期 | 核心任务 | 对应建议 | 预期收益 |
|------|------|----------|----------|----------|
| 阶段一 快赢 | W1-W2 | 分层模型路由 + 结构化输出 | 建议 3 + 5 | NLU 成本↓60%、延迟↓50% |
| 阶段二 认知 | W3-W5 | RAG 意图清单 + 历史注入 | 建议 1 + 4 | 答非所问率↓70%、Token↓70% |
| 阶段三 架构 | W6-W10 | Function-Calling Agent | 建议 2 | 新增意图零代码、复合任务能力 |
| 横切 基建 | 全程 | 环境/Docker/测试/监控 | — | 工程化保障 |

```
W1  W2  W3  W4  W5  W6  W7  W8  W9  W10
├─阶段一──┤  ├─────阶段二─────┤  ├──────阶段三──────┤
   快赢           认知升级           架构升级
        ↑               ↑                ↑
     里程碑1          里程碑2           里程碑3
```

---

## 1. 阶段一：快赢优化（W1-W2）

### 任务 1.1：分层模型路由

**任务目标**：把单一 `text_model` 拆分为按任务类型路由的多模型配置，NLU/分类用快模型，叙述/推理用强模型。

**涉及模块**：
- `backend/app/config.py` — 增加路由配置
- `backend/app/dialog/llm_nlu.py` — `LlmNlu._ensure_client()` 改造
- `backend/app/services/llm_service.py` — `classify_fee` / `extract_project_name` 改造
- `backend/app/dialog/llm_nlu.py` — `LlmNluCache` key 加入 model 字段
- `.env` / `.env.example` — 新增环境变量

**技术选型**：
| 任务类型 | 推荐模型 | 理由 |
|----------|----------|------|
| `nlu_classify` | qwen-turbo | 高频低复杂度，延迟 300-800ms |
| `fee_classify` | qwen-turbo | 短文本分类 |
| `invoice_ocr` | qwen3-vl-plus | 必须 Vision（已配置） |
| `insight_narrate` | qwen-plus | 长文本生成质量好 |
| `batch_describe` | qwen-plus | 需要推理拆解 |
| `project_extract` | qwen-turbo | 短文本 + 已知列表 |

**实施步骤**：

1. **Step 1.1.1** — 修改 `config.py`：增加 `MODEL_ROUTING` 字典与 `get_model_for_task(task_type)` 辅助函数；保留 `text_model` 作为兜底。
2. **Step 1.1.2** — 改造 `LlmNlu`：构造函数接受 `task_type="nlu_classify"`；`_ensure_client()` 不再缓存单一 client，改为 `dict[str, AsyncOpenAI]` 按 model 复用 client。
3. **Step 1.1.3** — 改造 `LlmNluCache._make_key()`：`f"{role}:{model}:{text}"`，避免跨模型缓存污染。
4. **Step 1.1.4** — 改造 `LLMService`：`classify_fee` / `extract_project_name` 使用 `settings.get_model_for_task("fee_classify")` 等。
5. **Step 1.1.5** — 更新 `.env.example`：新增 `LLM_NLU_MODEL`、`LLM_NARRATE_MODEL` 可选项（覆盖路由表）。
6. **Step 1.1.6** — 灰度验证：通过 `settings` 数据库热更新机制（`SystemSettings` 表）切换模型，对比延迟与准确率。

**预期产出**：
- `config.py` 新增 `MODEL_ROUTING` 与 `get_model_for_task()`
- `llm_nlu.py` 多 client 管理 + 缓存 key 升级
- 单元测试：`tests/test_model_routing.py`（验证不同 task_type 命中不同模型）

**验收标准**：

- [ ] NLU P99 延迟从 3s → 0.8s
- [ ] NLU 单次 token 成本下降 ≥ 60%
- [ ] 缓存命中率不下降（相同文本+模型+角色仍命中）
- [ ] `classify_fee` / `extract_project_name` 行为不变（回归测试通过）

---

### 任务 1.2：结构化输出 + 流式响应

**任务目标**：消除 LLM 返回 JSON 解析失败的脆弱性（`split("```json")`），并让用户在 NLU 1-3s 等待期间看到流式反馈。

**涉及模块**：

- `backend/app/dialog/llm_nlu.py` — `_call_llm()` 改用 `response_format`
- `backend/app/services/llm_service.py` — `parse_invoice_from_image` / `classify_fee` 改用 `response_format`
- `backend/app/routers/dialog.py` — 新增 `/message/stream` SSE 端点
- `backend/app/dialog/dialog_engine.py` — `process_message` 增加回调钩子（流式中间结果）
- `frontend/src/components/ChatWidget.tsx` — 接入 SSE
- `backend/app/schemas/` — 新增 `NluResultSchema` Pydantic 模型

**技术选型**：
- 结构化输出：`response_format={"type": "json_schema", "json_schema": {...}}`（qwen-plus/deepseek 支持）；qwen-turbo 降级用 `{"type": "json_object"}`
- Pydantic 校验：`NluResultSchema`（与 `NluResult` dataclass 对齐）
- 流式：FastAPI `StreamingResponse` + SSE 协议
- 兜底：保留现有 `split("```json")` 作为 response_format 不可用时的 fallback

**实施步骤**：

1. **Step 1.2.1** — 定义 Pydantic schema：
   ```python
   # backend/app/schemas/nlu_schema.py
   class NluResultSchema(BaseModel):
       intent_name: str = ""
       confidence: float = 0.0
       slots: dict[str, Any] = {}
       reasoning: str = ""
   ```
2. **Step 1.2.2** — 改造 `LlmNlu._call_llm()`：
   - 构造 `response_format` JSON Schema（从 `NluResultSchema.model_json_schema()` 生成）
   - 用 `pydantic.TypeAdapter` 校验返回，失败自动重试 1 次
3. **Step 1.2.3** — 改造 `LLMService.parse_invoice_from_image`：已有 `response_format={"type": "json_object"}`，升级为完整 json_schema。
4. **Step 1.2.4** — 在 `DialogEngine.process_message()` 注入进度回调：
   ```python
   async def process_message(..., on_progress: Callable[[str], Awaitable] | None = None):
       if on_progress: await on_progress("正在理解您的需求…")
       # LLM NLU 调用前
       if on_progress: await on_progress("正在查询数据…")
       # Action 执行前
   ```
5. **Step 1.2.5** — 新增 SSE 端点 `routers/dialog.py`：
   ```python
   @router.post("/message/stream")
   async def stream_message(req: DialogRequest):
       async def event_gen():
           yield _sse({"phase": "thinking", "text": "正在理解您的需求…"})
           # 调用 process_message(on_progress=...)
           yield _sse({"phase": "done", "response": final_response})
       return StreamingResponse(event_gen(), media_type="text/event-stream")
   ```
6. **Step 1.2.6** — 前端 `ChatWidget.tsx` 接入 `EventSource` 或 `fetch + ReadableStream`，先显示"正在思考…"气泡，再流式替换为最终回复。
7. **Step 1.2.7** — 改造置信度阈值逻辑：`confidence < 0.6` 时返回 `need_user_input=True` + 候选意图列表，触发"您是想问 X 还是 Y？"澄清。

**预期产出**：
- `schemas/nlu_schema.py` Pydantic 模型
- `routers/dialog.py` 新增 `/message/stream` 端点
- `ChatWidget.tsx` SSE 接入
- 单元测试：`tests/test_structured_output.py`

**验收标准**：
- [ ] JSON 解析失败率从 ~2% → < 0.1%
- [ ] 用户首字节反馈时间 < 200ms（"正在思考…"立即出现）
- [ ] 低置信度 case 不再静默返空，触发澄清追问
- [ ] qwen-turbo 不支持 json_schema 时自动降级 json_object，不报错

---

## 2. 阶段二：上下文与 Prompt 优化（W3-W5）

### 任务 2.1：RAG 化意图清单

**任务目标**：把 60+ 意图全塞进 prompt 的做法，改为"向量检索 Top-K 候选 + 精简 prompt"，砍掉 70% token。

**涉及模块**：
- `backend/app/dialog/intent_registry.py` — 增加 `embeddings` 字段
- `backend/app/dialog/llm_nlu.py` — `_SYSTEM_PROMPT` 改为模板 + 动态拼接候选意图
- 新增 `backend/app/dialog/intent_retriever.py` — 向量检索模块
- 新增 `backend/app/dialog/embedding_service.py` — embedding 调用

**技术选型**：
| 选项 | 方案 | 适用场景 |
|------|------|----------|
| A：内存 dict | 60 条意图预计算 embedding 存内存 | ✅ 推荐，启动时一次性计算 |
| B：FAISS | 本地向量索引 | 意图数 > 500 时考虑 |
| C：Chroma/Qdrant | 外部向量库 | 暂不需要 |
| Embedding 模型 | `text-embedding-v2`（qwen）或 `bge-small-zh` | 中文语义，512 维 |

**实施步骤**：

1. **Step 2.1.1** — 在 `intent_registry.py` 给每个 `Intent` 增加 `typical_utterances: list[str]`（典型表述，3-5 条）。
2. **Step 2.1.2** — 新建 `embedding_service.py`：调用 `dashscope.TextEmbedding.embed` 或本地 `sentence-transformers`；带缓存（相同文本不重复调）。
3. **Step 2.1.3** — 启动时（`app/main.py` lifespan）一次性计算所有意图 embedding，存入 `IntentRetriever._index`（dict）。
4. **Step 2.1.4** — 实现 `IntentRetriever.retrieve(text, role, top_k=8)`：
   
   - 用户文本 → embedding
   - 余弦相似度排序
   - 按角色过滤（员工不返回 admin 意图）
   - 返回 Top-8 候选
5. **Step 2.1.5** — 重构 `LlmNlu._SYSTEM_PROMPT` 为模板：
   ```python
   def _build_prompt(candidates: list[Intent]) -> str:
       return f"""你是AI报销智能体的意图识别引擎。
   ## 候选意图（从全库检索出的 Top-{len(candidates)}）
   {format_candidates(candidates)}
   ## 通用规则
   - 输出 JSON: intent_name/confidence/slots/reasoning
   - 都不匹配则 intent_name=""
   """
   ```
6. **Step 2.1.6** — `LlmNlu._call_llm_classify` 先调 retriever，再传候选 prompt 给 LLM；缓存 key 仍按 `(text, role, model)`。
7. **Step 2.1.7** — 监控：记录每次检索的候选列表与最终 LLM 输出，分析 badcase。

**预期产出**：
- `dialog/intent_retriever.py`
- `dialog/embedding_service.py`
- `intent_registry.py` 扩展 typical_utterances
- `llm_nlu.py` prompt 动态化
- 评估脚本：`scripts/eval_nlu_rag.py`（跑 100 条测试集对比准确率）

**验收标准**：

- [ ] 单次 NLU token 从 ~2500 → ~800
- [ ] 测试集准确率不下降（或提升 ≥ 2%）
- [ ] 相似意图混淆率下降（`insight_anomaly` vs `insight_invoice_filter` 误判率↓50%）
- [ ] 启动时间增加 < 3s（一次性 embedding 计算）

---

### 任务 2.2：对话历史注入 LLM

**任务目标**：把 `DialogContext.history` / `slots` / `state` 紧凑摘要传给 LLM，让它自己处理省略句式与跨轮继承，大幅精简 `ContextResolver`。

**涉及模块**：
- `backend/app/dialog/llm_nlu.py` — `_call_llm_classify` 构造带历史的 user message
- `backend/app/dialog/context_resolver.py` — 降级为兜底规则，移除大部分正则
- `backend/app/dialog/dialog_engine.py` — `Step 1.7` 调整为只在 LLM 失败时兜底
- `backend/app/dialog/models.py` — `DialogContext.history` 增加 token 预算

**实施步骤**：

1. **Step 2.2.1** — 设计历史摘要模板（控制 ≤ 500 tokens）：
   ```
   [对话历史（最近3轮）]
   T-2: intent=insight_person, slots={person:"陈辉", period:"last_month"}
   T-1: intent=insight_category_amount, slots={fee_category:"差旅", period:"last_month"}
   [当前状态] state=IDLE
   [用户输入] 交通费呢？
   ```
2. **Step 2.2.2** — `DialogContext.get_history_summary(max_turns=3, max_tokens=500)`：返回紧凑字符串。
3. **Step 2.2.3** — 改造 `LlmNlu._call_llm_classify` 的 user message：
   ```python
   user_msg = f"用户角色: {context.role.value}\n{context.get_history_summary()}\n用户输入: {text}"
   ```
4. **Step 2.2.4** — 调整 `LlmNluCache`：
   - key 改为 `(text, role, history_hash)`
   - `history_hash = md5(context.get_history_summary())`
   - TTL 缩短到 120s（历史变化快，缓存价值下降）
5. **Step 2.2.5** — 改造 `ContextResolver.resolve()`：
   - 仅保留"LLM 未识别意图时的强兜底"（场景 A）
   - 删除场景 B（同意图槽位补全），交给 LLM 自己处理
   - 保留 `is_query_intent()` 用于 `dialog_engine.py:247` 的历史写入
6. **Step 2.2.6** — 评估：在 `tests/test_context_resolver.py` 中跑原测试集，确认兜底逻辑仍正确。

**预期产出**：
- `DialogContext.get_history_summary()` 方法
- `llm_nlu.py` 带历史的 prompt 构造
- `context_resolver.py` 精简至 ≤ 100 行
- 单元测试：`tests/test_history_injection.py`

**验收标准**：
- [ ] 跨轮继承 case（"查张三上月差旅费 → 交通费呢？"）准确率 ≥ 95%
- [ ] 指代消解 case（"这张发票" → 注入 invoice_id）准确率 ≥ 90%
- [ ] `context_resolver.py` 代码量下降 ≥ 50%
- [ ] 缓存命中率下降在可接受范围（< 30%，因 key 多了 history_hash）

---

## 3. 阶段三：Agent 架构升级（W6-W10）

### 任务 3.1：Function-Calling Agent 改造

**任务目标**：把"LLM 输出意图字符串 → Python 字典路由"升级为"LLM 输出 tool_call → 通用执行循环"，让 LLM 真正成为 Agent 大脑。

**涉及模块（大改）**：

- `backend/app/dialog/intent_registry.py` — `Intent` → `Tool` schema
- `backend/app/dialog/dialog_engine.py` — 主循环改为 Agent loop
- `backend/app/dialog/action_executor.py` — 删除 `_get_handler` 硬编码 dict，改为通用分发
- `backend/app/dialog/dialog_fsm.py` — 多轮追问改由 LLM 生成（保留状态机做权限/超时控制）
- `backend/app/dialog/role_gate.py` — 改为 tool 可见性过滤
- `backend/app/dialog/llm_nlu.py` — 升级为 `AgentCore`，支持 tool_calling

**技术选型**：
- Function Calling：OpenAI 兼容接口的 `tools=[...]` + `tool_choice="auto"`
- Tool Schema：Pydantic `BaseModel` 自动生成 JSON Schema
- 执行循环：ReAct 风格（最多 N=5 步）
- 安全：`RoleGate` + SQL guard + tool 参数白名单校验

**实施步骤**：

1. **Step 3.1.1** — 定义 Tool 基类（`dialog/tool_registry.py`）：
   ```python
   class Tool(BaseModel):
       name: str
       description: str
       parameters: Type[BaseModel]  # Pydantic schema
       handler: Callable
       required_roles: list[UserRole]
       
       def to_openai_schema(self) -> dict: ...
   ```
2. **Step 3.1.2** — 把现有 `_get_handler` 中的 20+ handler 改写为 Tool 实例：
   ```python
   class UploadInvoiceTool(Tool):
       name = "emp_upload_invoice"
       description = "上传发票图片/PDF/OFD"
       parameters = UploadInvoiceParams  # Pydantic
       required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
       
       async def run(self, ctx, db, params) -> dict: ...
   ```
3. **Step 3.1.3** — 改造 `RoleGate`：从"意图校验"改为"tool 可见性过滤"，根据角色返回该角色可见的 tool 列表。
4. **Step 3.1.4** — 新建 `AgentCore`（替代 `LlmNlu`）：
   ```python
   class AgentCore:
       async def run(self, user_msg, history, visible_tools) -> AgentResponse:
           # ReAct 循环（最多 5 步）
           for step in range(5):
               resp = await self._call_llm_with_tools(user_msg, visible_tools, ...)
               if resp.tool_calls:
                   for tc in resp.tool_calls:
                       result = await self._execute_tool(tc, visible_tools)
                       # 把 result 喂回 LLM 做下一步推理
                       user_msg = ...
               else:
                   return resp  # LLM 给出最终回复
   ```
5. **Step 3.1.5** — 改造 `DialogEngine.process_message()`：
   - 取消 `Step 2 LLM NLU` 与 `Step 4 ActionExecutor` 的分离
   - 改为：`get_visible_tools(role)` → `agent.run(text, history, tools)` → 收到 tool_calls 直接执行
   - `DialogFSM` 仅用于 WAITING 状态超时管理与多轮中断（cancel）
6. **Step 3.1.6** — 保留双轨运行机制（feature flag `AGENT_MODE_ENABLED`）：
   - `False`：走旧 NLU + FSM + ActionExecutor 路径（兜底）
   - `True`：走新 Agent loop
   - 通过 `SystemSettings` 表热切换
7. **Step 3.1.7** — MCP Server 升级：把 3 个现有 tool 扩展为完整 tool 库，与 DialogEngine 共享同一套 Tool 注册表。
8. **Step 3.1.8** — 灰度发布：先 10% 用户启用 `AGENT_MODE_ENABLED=True`，监控准确率与延迟，逐步放量。

**预期产出**：
- `dialog/tool_registry.py` Tool 基类 + 20+ Tool 实例
- `dialog/agent_core.py` ReAct 循环
- `dialog_engine.py` 双轨机制
- `mcp/server.py` 工具库扩展
- 集成测试：`tests/test_agent_mode.py`

**验收标准**：
- [ ] 新增意图零代码（只加 Tool 实例 + 注册）
- [ ] 复合任务（"查陈辉上月差旅费，再对比上月公司总额"）可一次完成
- [ ] Agent mode 准确率 ≥ 旧模式 -3%（允许小退步以换取灵活性）
- [ ] Agent mode P99 延迟 ≤ 旧模式 + 1.5x（多步推理可接受）
- [ ] `AGENT_MODE_ENABLED=False` 时旧路径完全不受影响

---

## 4. 横切关注点：环境与基础设施

### 任务 0.1：环境准备

**关键配置项**：

| 类别 | 配置 | 说明 |
|------|------|------|
| LLM API | qwen dashscope base_url | 已在 `config.py` 配置 |
| Embedding API | `text-embedding-v2` | 用于 RAG 检索 |
| 流式 API | `stream=True` | OpenAI 兼容 |
| Function Calling | `tools=[...]` | qwen-plus/deepseek 支持 |
| 向量库 | 内存 dict（W3-5）→ FAISS（W6+，如需） | 启动加载 |
| Pydantic | v2（已用） | JSON Schema 生成 |

**新增环境变量**（`.env.example`）：

```bash
# 模型路由
LLM_NLU_MODEL=qwen-turbo
LLM_NARRATE_MODEL=qwen-plus
LLM_BATCH_MODEL=qwen-plus

# Embedding
LLM_EMBEDDING_MODEL=text-embedding-v2
LLM_EMBEDDING_DIM=1536

# Agent 模式
AGENT_MODE_ENABLED=false
AGENT_MAX_STEPS=5

# 流式
DIALOG_STREAM_ENABLED=true
```

---

### 任务 0.2：Docker 调整

**当前 `docker-compose.yml` 服务**：backend / frontend / postgres / redis / wecom-gateway

**调整项**：

1. **Backend 环境变量**：增加上述新增变量。
2. **健康检查**：`dialog/health` 端点扩展返回 model_routing / embedding_index 状态。
3. **资源限制**：embedding 索引常驻内存，backend 容器内存建议从 512m → 1024m。
4. **可选：embedding 服务**：若用本地 `sentence-transformers`，考虑独立 sidecar 容器。
5. **日志卷**：增加 `./logs:/app/logs` 挂载，便于 LLM 调用日志分析。

---

### 任务 0.3：测试验证策略

| 测试类型 | 工具 | 覆盖目标 |
|----------|------|----------|
| 单元测试 | pytest | 模型路由、结构化输出、RAG 检索 |
| 集成测试 | pytest + httpx | SSE 流式、Agent loop |
| 回归测试 | 录制真实对话样本 | 100 条 badcase 集 |
| 评估集 | 自建 100 条标注 query | NLU 准确率、跨轮继承准确率 |
| 性能测试 | locust | NLU P99 延迟、并发吞吐 |
| A/B 测试 | feature flag | Agent mode vs 旧模式对比 |

**评估集建设**：
- 从生产日志（`dialog.py` 的 `logger.info`）抽样 200 条真实 query
- 人工标注正确 intent + slots
- 加入 CI：每次 PR 跑评估集，准确率不得下降超过 1%

---

## 5. 风险控制矩阵

| 风险 | 等级 | 触发条件 | 应对策略 |
|------|------|----------|----------|
| **R1：qwen-turbo 不支持 json_schema** | 中 | W1 切换 NLU 模型时 | 降级 `response_format={"type":"json_object"}`；用 Pydantic 校验 + 1 次重试 |
| **R2：embedding 模型限流** | 低 | W3 启动时批量计算 60 条 embedding | 启动时延迟初始化 + 失败重试 3 次 + 内存兜底 |
| **R3：缓存命中率大幅下降** | 中 | W3 引入 history_hash 后 key 变复杂 | 监控 cache hit rate；如 < 30% 则缩短 TTL 至 60s |
| **R4：Agent mode 准确率不达标** | 高 | W8 灰度时 | 双轨机制兜底；保留旧路径至少 2 个版本周期；评估集做对比 |
| **R5：Function Calling 不被 qwen 支持** | 中 | W6 切换 Agent 架构时 | 先用 `deepseek-chat` 验证；或退回"LLM 输出 JSON tool_call + Pydantic 校验"伪 function calling |
| **R6：SSE 在企微网关不可用** | 中 | W2 接入企微时 | 企微走非流式端点；Web/MCP 走流式；channel capability negotiation |
| **R7：历史注入导致 token 爆炸** | 低 | W3 长对话场景 | `get_history_summary` 严格限 3 轮 + 500 tokens；超长用 LLM 摘要压缩 |
| **R8：Tool schema 漂移导致 LLM 误调** | 中 | W6 Tool 改造时 | Tool 注册时强校验 Pydantic schema；CI 跑 schema 兼容性检查 |
| **R9：模型热更新中断 Agent loop** | 低 | W6+ Agent 多步推理中 | 单次 Agent run 内固定 model；热更新只在新 run 生效 |
| **R10：测试集过拟合** | 中 | 评估集与训练意图重叠 | 评估集独立维护；定期新增 badcase；引入 holdout 集 |

---

## 6. 里程碑与发布节奏

| 里程碑 | 时间 | 交付物 | 可上线条件 |
|--------|------|--------|------------|
| **M1：快赢** | W2 周末 | 模型路由 + 结构化输出 + SSE | NLU P99<1s、JSON 解析失败率<0.1% |
| **M2：认知升级** | W5 周末 | RAG 意图 + 历史注入 | 跨轮继承准确率≥95%、Token↓60% |
| **M3：Agent 上线** | W10 周末 | Function-Calling Agent | 灰度 50% 用户、准确率达标 |
| **M3+：全量** | W10+ 1 周 | 旧路径下线 | 100% 用户稳定运行 7 天 |

---

## 7. 团队分工建议（参考）

| 角色 | 人数 | 主要负责 |
|------|------|----------|
| 后端 Lead | 1 | 架构设计、Agent Core、Tool 改造 |
| 后端 | 1-2 | RAG、模型路由、SSE、单元测试 |
| 前端 | 1 | ChatWidget SSE 接入、流式 UI |
| 算法/Prompt | 1 | 评估集、Prompt 优化、badcase 分析 |
| QA | 1 | 评估集标注、回归测试、A/B 监控 |

---

## 8. 关键代码改动清单（一图速查）

```
backend/app/
├── config.py                          [改] +MODEL_ROUTING, +get_model_for_task()
├── schemas/
│   └── nlu_schema.py                  [新] Pydantic schema
├── dialog/
│   ├── dialog_engine.py               [改] +on_progress回调, 双轨机制
│   ├── llm_nlu.py                     [改→重构] 多client, 历史注入, 响应式prompt
│   ├── action_executor.py             [改] 删_get_handler, 通用分发
│   ├── context_resolver.py            [改] 精简, 仅兜底
│   ├── intent_registry.py             [改] +typical_utterances, Tool化
│   ├── tool_registry.py               [新] Tool 基类
│   ├── agent_core.py                  [新] ReAct 循环
│   ├── intent_retriever.py            [新] 向量检索
│   ├── embedding_service.py           [新] embedding 调用
│   ├── context_store.py               [无改动]
│   └── role_gate.py                   [改] tool 可见性过滤
├── routers/
│   └── dialog.py                      [改] +/message/stream SSE
├── services/
│   └── llm_service.py                 [改] 多模型路由
├── prompts/
│   ├── invoice_prompts.py             [改] 拆分巨型prompt
│   └── nonstandard_prompts.py         [改] 同上
└── tests/
    ├── test_model_routing.py          [新]
    ├── test_structured_output.py      [新]
    ├── test_nlu_rag.py                [新]
    ├── test_history_injection.py      [新]
    ├── test_agent_mode.py             [新]
    └── test_context_resolver.py       [改] 适配精简后逻辑
```

---

## 9. 一句话总结

> 这份计划把"5 条优化建议"拆为"3 阶段 + 10 周期 + 30+ 步骤"，每一步都标注了**改哪个文件、用什么技术、怎么验收**。
>
> 关键路径：**W2 快赢上线（降本提速）→ W5 认知升级（提质）→ W10 Agent 架构（解锁能力）**，全程通过 feature flag 双轨运行，确保任何阶段失败都不影响线上。
>
> 风险控制的核心是 R4（Agent 准确率）与 R1（模型兼容性），分别用"双轨兜底"和"分级降级"覆盖。
