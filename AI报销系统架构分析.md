# AI 报销智能体 —— 对话系统架构与大模型价值提升分析

## 1. 架构拆解：自上而下的六层视图

当前项目是一个典型的「对话式业务 Agent」，整体可拆为六层。调用关系如箭头所示。

```
┌─────────────────────────────────────────────────────────────────┐
│ ① 交互层 (Interaction)                                           │
│   企微网关 (wecom-gateway/gateway/main.py)                        │
│   MCP Server (mcp/server.py — stdio/SSE)                          │
│   Web ChatWidget (frontend/src/components/ChatWidget.tsx)         │
│   Portal/管理后台 (frontend/src/pages/*)                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │  HTTP /api/dialog/message
┌──────────────────────────────▼──────────────────────────────────┐
│ ② 调度层 (Orchestration) — DialogEngine                          │
│   dialog_engine.py:79  process_message() 主编排                  │
│   流水线：Step0 注入 → Step1 正则 → Step2 LLM NLU                 │
│          → Step1.7 上下文继承 → Step2 RoleGate                    │
│          → Step3 FSM → Step4 ActionExecutor → Step5 特殊意图       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ ③ 认知层 (Cognitive) — NLU & Context                             │
│   • NluRouter           (正则，仅 cancel/help/greeting)            │
│   • LlmNlu              (单次 LLM 调用：意图+槽位)                 │
│   • SemanticClassifier  (n-gram 余弦相似度，已废弃旁路)            │
│   • LlmIntentClassifier (旧 L3，已废弃旁路)                       │
│   • ContextResolver     (跨轮槽位继承 / 省略句式 / 指代预留)        │
│   • RoleGate            (三角色权限校验 + 员工洞察自动降级)         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ ④ 能力执行层 (Action) — ActionExecutor + InsightEngine           │
│   action_executor.py:116  _get_handler() 意图→handler 静态分发    │
│   insight_engine.py        SQLAlchemy ORM 聚合（明确拒绝 NL2SQL）  │
│   MCP Tools (send_dialog_message / query_invoices / ...)          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ ⑤ 服务层 (Service)                                                │
│   LLMService       (Vision OCR / 费用分类 / 项目提取)              │
│   InvoiceService / ReimbursementService / CycleEngine             │
│   SubsidyEngine / ExpenseDateEngine / VerifyService / OCRService  │
│   NonstandardService / ReportGenerator / SchedulerService         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ ⑥ 数据层 (Data)                                                   │
│   PostgreSQL+asyncpg  Invoice/Reimbursement/Employee/Project      │
│   Redis               dialog:ctx:{user_id}  (TTL 24h，滑动续期)    │
│   Alembic 迁移 / 上传目录 / 报表目录                                │
└─────────────────────────────────────────────────────────────────┘
```

### 调用链关键点

- **入口统一**：所有渠道（企微、MCP、Web）都收敛到 `POST /api/dialog/message`（`routers/dialog.py:66`），由 `DialogEngine.process_message()` 单一入口处理。
- **编排是「管道 + 状态机」混合**：单轮内是线性管道（Step0→Step6），跨轮由 `DialogFSM` 维护 `IDLE / WAITING_*` 状态（`dialog_fsm.py:69` 的 `_STATE_SLOT_MAP`）。
- **上下文持久化**：`RedisContextStore`（`context_store.py:77`）以 `dialog:ctx:{user_id}` 为 Key，JSON 序列化整张 `DialogContext`，TTL 24h 滑动续期；Redis 不可用时优雅降级到 `MemoryContextStore`。

---

## 2. 大模型在架构中的定位：**NLU 工具人，而非 Agent 大脑**

这是当前架构最关键的判断。LLM 在系统里有 **5 处实际调用点**，但全部是「分类 / 抽取」角色，没有任何「决策 / 规划 / 反思」职责。

### 2.1 LLM 的五个调用点

| # | 位置 | 任务 | 模型 | Prompt 风格 |
|---|------|------|------|-------------|
| ① | `dialog/llm_nlu.py:417` `_call_llm_classify` | 意图识别 + 槽位提取 | `settings.text_model` | 巨型 system prompt（~200 行意图清单） |
| ② | `services/llm_service.py:66` `parse_invoice_from_image` | 发票图片 OCR + 字段抽取 | `settings.llm_model`（Vision） | 12 字段 JSON Schema + 消歧规则 |
| ③ | `services/llm_service.py:147` `classify_fee` | 费用分类（差旅/办公/投标…） | `settings.text_model` | 分类体系 + 简短示例 |
| ④ | `services/llm_service.py:173` `extract_project_name` | 从描述抽取项目名 | `settings.text_model` | 已知项目列表 + 描述 |
| ⑤ | `dialog/llm_nlu.py:530` `_call_llm_batch_describe` | 批量描述拆解到每张发票 | `settings.text_model` | 简短 few-shot |

### 2.2 「不是 Agent 大脑」的证据

**证据 A — LLM 不决定调用哪个工具**。意图→handler 的映射是硬编码的 Python dict：

```python
# action_executor.py:116
def _get_handler(self, intent_name: str):
    handlers = {
        "emp_upload_invoice": self._handle_upload_invoice,
        "emp_no_receipt": self._handle_no_receipt,
        "admin_approve": self._handle_admin_approve,
        ...
    }
    return handlers.get(intent_name)
```

LLM 输出一个意图字符串，Python 字典做分发。这是「LLM-as-classifier + 规则路由」，不是 function-calling。

**证据 B — LLM 不写 SQL、不直接查数据**。`insight_engine.py:13` 注释明确写：

> 架构特点：直接 SQLAlchemy ORM 查询，不使用 NL2SQL（安全可控）

LLM 只提取 `period/person/fee_category_keyword` 等槽位，真正的聚合查询由 Python ORM 完成。这是合理的安全设计，但也意味着 LLM 无法处理它没见过的查询结构。

**证据 C — LLM 不参与多轮规划**。多轮对话由 `DialogFSM` 的状态机驱动（`dialog_fsm.py:69`），LLM 每轮独立调用、无链式思考、无反思。`_PROMPT_TEMPLATES`（`dialog_fsm.py:30`）是硬编码的追问话术。

**证据 D — LLM 的"上下文"极薄**。`llm_nlu.py:434` 构造的 user message 只有两行：

```python
user_msg = f"用户角色: {context.role.value}\n用户输入: {text}"
```

对话历史、用户偏好、上一轮意图、已填充槽位 —— **一个都没传给 LLM**。跨轮继承是 `ContextResolver` 在 Python 端用正则 + 规则做的（`context_resolver.py:104`），完全绕过 LLM。

### 2.3 结论

> 当前架构是 **"LLM-as-NLU + 规则编排"** 的传统对话机器人范式，不是 Agentic 架构。
> LLM 的核心价值被限制在「自然语言→结构化意图」的单步映射，相当于一个高级正则。
> 真正的"大脑"是 `DialogEngine + DialogFSM + IntentRegistry + RoleGate` 这套规则系统。

这个设计在 v1 阶段是合理的（可控、低成本、易调试），但它的天花板也很明显：意图数膨胀后 prompt 会爆炸、无法处理复合任务、无法自我纠错、无法利用 LLM 的推理能力做复杂洞察。

---

## 3. 五条可落地的优化建议

按 ROI 排序，从最值得做的开始。

### 建议 1：**RAG 化意图清单，砍掉 70% 的 Prompt Token**

**痛点**：`llm_nlu.py:36-194` 的 `_SYSTEM_PROMPT` 是个 ~200 行的巨型字符串，把 60+ 意图、全部槽位定义、十几条语义判别规则全塞进每次调用。每次 NLU 调用消耗 2000+ tokens，且相似意图（`insight_anomaly` vs `insight_invoice_filter` vs `insight_top`）在长 prompt 里容易被 LLM 混淆 —— 代码里专门写了大段「### insight_anomaly vs insight_top」「### insight_by_dept vs insight_top」的判别规则，正是这种混淆的补救。

**方案**：

1. 离线把每个意图的 `name + description + 典型表述` 编码为 embedding，存入向量库（甚至内存 dict 即可，60 条向量很轻）。
2. 用户输入来了，先用 embedding 检索 Top-8 相关意图。
3. LLM 的 system prompt 只放：通用规则 + 这 8 个候选意图的精简定义 + 槽位 schema。
4. 同时让 LLM 输出 `reasoning`（已经在输出），用于后续 prompt 优化和 badcase 分析。

**收益**：单次 token 从 ~2500 降到 ~800，延迟下降 40%+，相似意图混淆率显著降低。`LlmNluCache` 的命中率不变（仍按 text+role 做 key）。

### 建议 2：**升级为 Function-Calling Agent，让 LLM 真正成为大脑**

**痛点**：当前 `ActionExecutor._get_handler()` 是静态 dict，新增意图必须改 Python 代码、重启服务。LLM 提取的槽位要先经过 `DialogFSM` 多轮追问、再传给 handler —— 中间任何一步槽位缺失就卡住，LLM 没有自我修正机会。

**方案**：把每个意图改写为 OpenAI Function Calling 风格的 tool schema（项目已有 MCP 基础，`mcp/server.py` 已经定义了 3 个 tool，扩展到 20+ 个即可）。LLM 直接决定调用哪个 tool、传什么参数；缺参数时由 LLM 自己生成追问，而不是查 `_PROMPT_TEMPLATES`。`RoleGate` 的权限校验改写成 tool 层面的可见性过滤（员工看不到 `admin_approve` tool）。

**关键代码改动点**：

- `intent_registry.py` 的 `Intent` 改写为 Pydantic `Tool` schema。
- `dialog_engine.py:164` 的 LLM NLU 调用改为 `tools=[...]` 的 function-calling。
- `action_executor.py` 改为「LLM 输出 tool_call → 校验 schema → 执行 handler」的通用循环，删掉 `_get_handler` 的硬编码 dict。
- 保留 `RoleGate` 作为执行前权限校验（不是 LLM 提示词层面的，因为 LLM 可能漏看）。

**收益**：新增意图零代码（只加 tool schema）、LLM 可自主澄清模糊参数、复合任务可一次调用多 tool。这是把架构从「规则 Agent」推向「LLM Agent」的关键一步。

### 建议 3：**分层模型路由，Haiku 干 NLU、Sonnet 干洞察叙述**

**痛点**：`config.py:64` 的 `text_model` 是单一文本模型，所有任务（NLU 分类、费用分类、项目提取、批量描述拆解）都用同一个。NLU 是高频低复杂度任务，用 Sonnet/Opus 级模型既慢又贵；而洞察类回复的自然语言叙述用 Haiku 又不够好。

**方案**：在 `config.py` 增加 `model_routing` 配置：

```python
MODEL_ROUTING = {
    "nlu_classify":    "qwen-turbo",      # 高频、低复杂度
    "fee_classify":    "qwen-turbo",      # 短文本分类
    "invoice_ocr":     "qwen3-vl-plus",   # 必须 Vision
    "insight_narrate": "qwen-plus",       # 长文本生成
    "batch_describe":  "qwen-plus",       # 需要推理
}
```

`LlmNlu._ensure_client()` 根据 `task_type` 选择模型。`LlmNluCache` 的 key 加入 `model` 字段避免跨模型缓存污染。

**收益**：NLU 单次成本降 60%+，延迟从 1-3s 降到 0.3-0.8s；复杂叙述质量提升。这是最省力的性价比优化。

### 建议 4：**注入对话历史与用户画像，解决「答非所问」根因**

**痛点**：`llm_nlu.py:434` 只传 `role + text` 给 LLM，丢失了 `DialogContext` 里的丰富信息 —— `history`（最近查询轮次）、`slots`（已填充槽位）、`state`（当前 WAITING 状态）、`last_intent`。所以 `ContextResolver` 不得不用纯正则在 Python 端做省略句式检测和槽位继承（`context_resolver.py:64` 的 `_ELLIPSIS_PATTERNS`），这套正则维护成本高、覆盖窄。

**方案**：构造一个紧凑的上下文摘要传给 LLM（控制在 500 tokens 内）：

```
[对话历史]
T-2: intent=insight_person, slots={person:"陈辉", period:"last_month"}
T-1: intent=insight_category_amount, slots={fee_category:"差旅", period:"last_month"}
[当前状态] state=IDLE
[用户输入] 交通费呢？
```

LLM 直接输出 `intent=insight_category_amount, slots={fee_category:"交通", person:"陈辉", period:"last_month"}`，无需 `ContextResolver` 介入。`ContextResolver` 降级为兜底规则。

**注意**：传 history 会破坏现有 `LlmNluCache` 的 `(text, role)` key —— 需要把 key 改为 `(text, role, history_hash)`。可接受，因为相同文本在不同历史下应得到不同结果。

**收益**：省略句式、指代消解、跨轮槽位继承这三类痛点一次性解决；`ContextResolver` 的 200+ 行正则可大幅精简。

### 建议 5：**结构化输出 + 流式响应，提升健壮性与体感**

**痛点 A（健壮性）**：`llm_nlu.py:514-521` 解析 LLM 返回的 JSON 靠 `split("```json")` + `json.loads`，LLM 偶尔返回带注释、尾随逗号、markdown 包裹的 JSON 就会 `JSONDecodeError`。`llm_service.py:140` 也有同样的脆弱解析。

**痛点 B（体感）**：NLU 调用是阻塞的（`asyncio.wait_for` 15s 超时，`llm_nlu.py:296`），用户发完消息要等 1-3s 才看到任何反馈。

**方案**：

- **结构化输出**：用 OpenAI 的 `response_format={"type": "json_schema", "json_schema": {...}}`（qwen-plus/deepseek 均支持），或引入 `instructor` 库做 Pydantic 校验 + 自动重试。把 `_SYSTEM_PROMPT` 里的「输出格式」一节迁移为正式 JSON Schema。
- **流式响应**：`/api/dialog/message` 增加 SSE 流式版本，先返回「正在思考…」→ 再返回意图识别中间结果 → 最后返回 action 结果。`ChatWidget.tsx` 已经是 React 前端，接入 SSE 成本低。
- **置信度路由**：`confidence < 0.6` 时不静默返回空意图，而是触发一次澄清追问（"您是想问 X 还是 Y？"），把 `CONFIDENCE_THRESHOLD`（`llm_nlu.py:297`）变成动态门限。

**收益**：JSON 解析失败率从 ~2% 降到 ~0；用户体感延迟降 50%+；低置信度 case 从「答非所问」变为「主动澄清」。

---

## 4. 一句话总结

> 当前系统是「规则编排 + LLM 当 NLU」的 v1 架构，工程上严谨可控（ORM 拒绝 NL2SQL、Redis 持久化、角色降级、缓存幂等都很扎实），但 LLM 的价值被锁死在分类抽取层。
>
> 优先级建议：**建议 3（分层模型）→ 建议 5（结构化输出+流式）→ 建议 1（RAG 意图）→ 建议 4（历史注入）→ 建议 2（Function-Calling Agent）**。
>
> 前两项是 1 周内可上线的快赢，后三项是 1-2 个月的架构升级，最终目标是把 LLM 从「高级正则」推向「真正的 Agent 大脑」。
