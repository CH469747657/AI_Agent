---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'a7a6ca72-7bc3-4804-8d16-0b89f75ed928'
  PropagateID: 'a7a6ca72-7bc3-4804-8d16-0b89f75ed928'
  ReservedCode1: '7336d442-56a7-41f4-8c15-e0fcaa54b7bc'
  ReservedCode2: '7336d442-56a7-41f4-8c15-e0fcaa54b7bc'
---

# AI 报销智能体

基于 **LLM Agent** 的对话式报销预审系统。以企业微信和 Web 为交互入口，实现票据自动识别、验真查重、费用分类、项目归属和报表生成全链路智能化。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![React](https://img.shields.io/badge/React-18-61dafb) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL+pgvector-15-336791) ![Docker](https://img.shields.io/badge/Docker-Compose-2496ed)

## 核心能力

| 能力 | 说明 |
|------|------|
| 票据识别 | PaddleOCR + LLM Vision 双源交叉验证，12 字段逐一比对，冲突自动标记 |
| 智能分类 | 三层策略：规则匹配 → LLM 语义分类 → 人工兜底 |
| 查重校验 | 三级查重：发票号精确 → 金额+日期+销售方模糊 → pHash 图像哈希 |
| 对话式交互 | LLM Agent + Function-Calling 架构，RAG 意图检索，企微/Web 双端接入 |
| 管理后台 | 三端分离：员工 Portal / 管理 Admin / 老板 Boss Dashboard |
| 报表生成 | Excel（分 Sheet 含公式）+ PDF（HTML 模板）+ ZIP 票据归档 |

## 系统架构

```
企业微信用户 ──→ 企微回调 ──→ wecom-gateway (FastAPI:8090)
Web 用户 ────→ React SPA ──┐       │  解密消息 / 下载媒体 / 会话管理
                             │       │ HTTP
                             ▼       ▼
                        backend (FastAPI:8080)
                    ┌──────────┴──────────┐
                    │   DialogEngine       │  消息编排入口
                    │   ├─ LLM NLU         │  意图识别 + 槽位提取
                    │   ├─ Agent Core      │  Function-Calling Agent（可选）
                    │   ├─ Tool Registry   │  工具注册表
                    │   ├─ DialogFSM       │  多轮状态机
                    │   ├─ RoleGate        │  三角色权限校验
                    │   └─ InsightEngine   │  管理洞察聚合
                    ├──────────┬──────────┤
                    │  LLM Service   │ Qwen-VL / GPT-4o / DeepSeek
                    │  OCR Service   │ PaddleOCR 2.7
                    │  Diff Engine   │ 双源比对
                    │  Classifier    │ 三层分类
                    │  DupChecker    │ 三级查重
                    │  Report Gen    │ Excel + PDF
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  PostgreSQL + pgvector│
                    │  Redis               │
                    └──────────────────────┘

                    MCP SSE Server (:9000) ──→ 外部 Agent/IDE 接入
```

## 快速开始

### 1. 环境准备

```bash
git clone <repo-url>
cd ai-reimbursement-agent
cp .env.example .env
vi .env   # 填入 API Key 等配置
```

### 2. 关键配置

```ini
# LLM — 在千问控制台获取: https://dashscope.console.aliyun.com/apiKey
LLM_PROVIDER=qwen           # qwen | openai | deepseek | anthropic
LLM_API_KEY=sk-xxx
LLM_MODEL=qwen3-vl-plus     # 视觉模型

# Agent 模式（Function-Calling Agent）
AGENT_MODE_ENABLED=true      # true=Agent 路径, false=传统 NLU+FSM 路径

# JWT（员工端 Portal 鉴权，生产环境务必使用强随机字符串）
JWT_SECRET=<openssl rand -hex 32>

# 企业微信（在企微管理后台获取，未启用可留空）
WECOM_CORP_ID=ww...
WECOM_SECRET=...
WECOM_TOKEN=...
WECOM_ENCODING_AES_KEY=...
```

### 3. 启动服务

```bash
# 一键启动全部服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看后端日志
docker-compose logs -f backend
```

### 4. 服务地址

| 服务 | 地址 |
|------|------|
| 后端 API | http://localhost:18080 |
| API 文档 (Swagger) | http://localhost:18080/docs |
| MCP SSE Server | http://localhost:9000 |
| 企微网关 | http://localhost:18090/wecom/callback |
| PostgreSQL | localhost:15432 |
| Redis | localhost:6379 |
| 前端（本地开发） | http://localhost:5173 |

### 5. 前端本地开发

```bash
cd frontend
npm install
npm run dev          # 启动开发服务器
npm run build        # 构建生产版本
```

### 6. 企业微信回调配置

1. 登录[企业微信管理后台](https://work.weixin.qq.com/)
2. 应用管理 → 自建应用 → 创建应用
3. 接收消息 → 设置 API 接收
   - URL: `https://你的域名:18090/wecom/callback`
   - Token: 与 `.env` 中 `WECOM_TOKEN` 一致
   - EncodingAESKey: 与 `.env` 中 `WECOM_ENCODING_AES_KEY` 一致
4. 配置自定义菜单（可选）：
   - 上传发票 (KEY: `upload_receipt`)
   - 无票报销 (KEY: `no_receipt`)
   - 我的票据 (KEY: `query_status`)
   - 导出报表 (KEY: `generate_report`)

## 项目结构

```
ai-reimbursement-agent/
├── docker-compose.yml          # 容器编排（backend + mcp-sse + wecom-gateway + db + redis）
├── .env.example                # 环境变量模板
│
├── backend/                    # 后端 API 服务
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/                # 数据库迁移（启动时自动 upgrade）
│   └── app/
│       ├── main.py             # FastAPI 入口
│       ├── config.py           # 配置管理（含分层模型路由 MODEL_ROUTING）
│       ├── database.py         # 数据库连接
│       ├── models/             # SQLAlchemy 数据模型
│       │   ├── employee.py     # 员工
│       │   ├── invoice.py      # 发票（含查重/验真/分类状态）
│       │   ├── reimbursement.py # 报销单
│       │   ├── holiday.py      # 节假日
│       │   └── settings.py     # 系统设置
│       ├── dialog/             # 对话系统核心
│       │   ├── dialog_engine.py    # 消息编排主流程（管道 + 状态机）
│       │   ├── agent_core.py       # Function-Calling Agent
│       │   ├── tool_registry.py    # 工具注册表
│       │   ├── tools.py            # 工具实现
│       │   ├── llm_nlu.py          # LLM 意图识别 + 槽位提取
│       │   ├── intent_registry.py  # 意图定义注册
│       │   ├── intent_retriever.py # RAG 意图检索（向量召回候选）
│       │   ├── embedding_service.py # Embedding 服务
│       │   ├── context_resolver.py # 跨轮上下文继承
│       │   ├── context_store.py    # Redis/Memory 会话持久化
│       │   ├── dialog_fsm.py       # 多轮状态机
│       │   ├── role_gate.py        # 三角色权限校验
│       │   ├── insight_engine.py   # 管理洞察聚合（ORM 查询，非 NL2SQL）
│       │   └── nlu_router.py       # 正则快速路由（cancel/help/greeting）
│       ├── services/           # 核心业务逻辑
│       │   ├── llm_service.py      # 多 Provider LLM 调用（Vision OCR / 分类 / 抽取）
│       │   ├── ocr_service.py      # PaddleOCR 服务
│       │   ├── ofd_service.py      # OFD 电子发票解析
│       │   ├── diff_engine.py      # 双源比对引擎
│       │   ├── classifier.py       # 三层费用分类
│       │   ├── duplicate_checker.py # 三级查重
│       │   ├── invoice_service.py  # 票据处理核心编排
│       │   ├── reimbursement_service.py # 报销单管理
│       │   ├── report_generator.py # 报表生成（Excel + PDF）
│       │   ├── cycle_engine.py     # 报销周期引擎
│       │   ├── subsidy_engine.py   # 补贴计算引擎
│       │   ├── expense_date_engine.py # 费用日期解析
│       │   ├── verify_service.py   # 发票验真
│       │   ├── scheduler_service.py # 定时任务调度
│       │   └── aggregation_service.py # 数据聚合统计
│       ├── routers/            # API 路由
│       │   ├── dialog.py       # 对话引擎（/api/dialog）
│       │   ├── invoices.py     # 发票管理（/api/invoices）
│       │   ├── reimbursements.py # 报销单（/api/reimbursements）
│       │   ├── portal.py       # 员工端业务（/api/portal）
│       │   ├── portal_auth.py  # 员工端认证（/api/portal/auth）
│       │   ├── admin_auth.py   # 管理端认证（/api/admin/auth）
│       │   ├── employees.py    # 员工管理（/api/employees）
│       │   ├── reports.py      # 报表生成（/api/reports）
│       │   ├── wecom.py        # 企微交互（/api/wecom）
│       │   ├── settings.py     # 系统设置（/api/settings）
│       │   ├── holidays.py     # 节假日管理（/api/holidays）
│       │   └── travel_days.py  # 出差天数（/api/portal/travel-days）
│       ├── mcp/                # MCP Server
│       │   ├── server.py       # stdio 模式
│       │   └── server_sse.py   # SSE 模式（独立进程）
│       └── prompts/            # LLM 提示词
│
├── frontend/                   # 前端 SPA（React + TypeScript + Vite）
│   ├── package.json
│   └── src/
│       ├── App.tsx             # 路由定义（三端分离）
│       ├── components/         # 共享组件
│       │   ├── ChatWidget.tsx  # 对话聊天组件
│       │   ├── Sidebar.tsx     # 侧边导航
│       │   └── ...
│       └── pages/
│           ├── Dashboard.tsx   # 管理端 - 数据看板
│           ├── Invoices.tsx    # 管理端 - 发票管理
│           ├── Employees.tsx   # 管理端 - 员工管理
│           ├── Settings.tsx    # 管理端 - 系统设置
│           ├── portal/         # 员工端
│           │   ├── Login.tsx
│           │   ├── Home.tsx
│           │   ├── Upload.tsx
│           │   ├── MyInvoices.tsx
│           │   └── MyReimbursements.tsx
│           ├── admin/          # 超级管理员端
│           │   └── Login.tsx
│           └── boss/           # 老板端（移动端布局）
│               ├── Chat.tsx
│               ├── InvoiceList.tsx
│               ├── ReimbursementList.tsx
│               └── Settings.tsx
│
├── wecom-gateway/              # 企业微信回调网关
│   └── gateway/
│       ├── main.py             # FastAPI 回调应用
│       ├── crypto.py           # 企微消息 AES-CBC 加解密
│       ├── session.py          # Redis 会话状态管理
│       └── wecom_client.py     # 企微 API 客户端
│
├── uploads/                    # 票据上传目录
└── reports/                    # 报表输出目录
```

## 技术栈

| 领域 | 选型 | 说明 |
|------|------|------|
| **后端框架** | Python 3.10 + FastAPI | 异步高性能，AI 框架生态兼容 |
| **AI 视觉** | PaddleOCR 2.7 + Qwen-VL / GPT-4o | 中文票据优化 + 多模型兼容 |
| **对话系统** | DialogEngine + LLM Agent + RAG | Function-Calling 架构，向量意图检索 |
| **数据存储** | PostgreSQL 15 + pgvector | 关系型数据 + 向量检索一体化 |
| **缓存** | Redis 7 | 会话管理、缓存、分布式锁 |
| **前端** | React 18 + TypeScript + Vite + TailwindCSS | 三端分离（Portal / Admin / Boss） |
| **报表** | openpyxl + WeasyPrint | Excel + PDF 双格式专业输出 |
| **数据库迁移** | Alembic | 启动时自动 upgrade，零手动迁移 |
| **MCP 协议** | stdio + SSE | 外部 Agent / IDE 接入 |
| **部署** | Docker Compose | 一键启动 5 个服务 |

## API 接口概览

### 对话引擎

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/dialog/message` | 对话消息入口（支持 SSE 流式响应） |

### 发票管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/invoices/upload` | 上传票据文件（multipart） |
| POST | `/api/invoices/wecom-process` | 企微网关转发（base64 图片） |
| POST | `/api/invoices/no-receipt` | 无票报销（文字描述） |
| GET | `/api/invoices` | 发票列表（支持 user_id/status 过滤） |
| GET | `/api/invoices/{id}` | 发票详情 |
| PUT | `/api/invoices/{id}` | 更新发票（修正分类/状态） |
| GET | `/api/invoices/statistics` | 统计数据 |

### 员工端 (Portal)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/portal/auth/login` | 员工登录（JWT） |
| POST | `/api/portal/invoices` | 上传发票 |
| GET | `/api/portal/invoices` | 我的发票列表 |
| GET | `/api/portal/invoices/{id}` | 发票详情 |
| GET | `/api/portal/invoices/{id}/download` | 下载发票文件 |
| DELETE | `/api/portal/invoices/{id}` | 删除发票 |
| GET | `/api/portal/reimbursements` | 我的报销单列表 |
| GET | `/api/portal/reimbursements/{id}` | 报销单详情 |
| PUT | `/api/portal/reimbursements/{id}` | 更新报销单 |
| POST | `/api/portal/reimbursements/link` | 关联发票到报销单 |
| GET | `/api/portal/travel-days` | 出差天数查询 |

### 企微交互

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/wecom/invoices/{user_id}` | 用户发票摘要 |
| POST | `/api/wecom/invoices/{id}/confirm` | 确认发票分类 |

### 管理端

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/auth/login` | 管理员登录 |
| GET | `/api/employees` | 员工列表 |
| POST | `/api/employees` | 创建/同步员工 |
| POST | `/api/reports/generate` | 生成报表 |
| GET | `/api/reports/{id}/download` | 下载报表 |
| GET | `/api/settings` | 系统设置 |
| GET | `/api/holidays` | 节假日列表 |

### 报销单管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/reimbursements` | 报销单列表 |
| GET | `/api/reimbursements/{id}` | 报销单详情 |
| PUT | `/api/reimbursements/{id}` | 更新报销单状态 |

> 完整 API 文档启动后访问 http://localhost:18080/docs

## 核心流程

### 票据处理全链路

```
用户发送图片
    │
    ▼
企微网关接收 → 下载媒体文件 → base64 编码
    │
    ▼
后端 /api/invoices/wecom-process
    │
    ├──→ OCR Service (PaddleOCR)  ──→ 结构化字段 A
    ├──→ LLM Service (Qwen-VL)    ──→ 结构化字段 B
    │                                    │
    │                              Diff Engine (12 字段逐个比对)
    │                                    │
    │                    ┌───────────────┤
    │                    ▼               ▼
    │              匹配→自动确认    冲突→标记人工复核
    │
    ├──→ Classifier (规则→LLM→人工兜底)
    ├──→ DuplicateChecker (发票号→模糊→pHash)
    │
    ▼
保存到数据库 → 推送结果到企微
```

### 对话交互示例

```
用户: [发送发票图片]
智能体: 正在识别票据，请稍候...
智能体:
  ## 票据识别结果 #1
  > 发票号: 12345678
  > 销售方: 中国石化销售有限公司
  > 金额: ¥350.00
  > 日期: 2025-01-15
  > 分类: 交通费-燃油费
  > 验真: ✅ verified
  > 查重: ✅ 正常

用户: 完成
智能体: ✅ 已提交 1 张票据进入报销流程。

用户: 查询上个月的交通费
智能体: 您上个月交通费共 3 笔，合计 ¥1,260.00 ...
```

## 开发指南

### 新增对话意图

系统支持两种模式（通过 `AGENT_MODE_ENABLED` 切换）：

**传统模式（NLU + FSM）**：
1. 在 `intent_registry.py` 中定义意图和槽位
2. 在 `action_executor.py` 中注册 handler
3. 在 `dialog_fsm.py` 中定义多轮追问模板

**Agent 模式（Function-Calling）**：
1. 在 `tool_registry.py` 中注册 Tool Schema
2. 在 `tools.py` 中实现工具函数
3. Agent Core 自动决策调用，无需硬编码路由

### 数据库迁移

```bash
# 生成迁移脚本
cd backend
alembic revision --autogenerate -m "描述变更"

# 手动执行迁移（生产环境；Docker 部署时启动自动 upgrade）
alembic upgrade head

# 查看当前版本
alembic current
```

### 测试

```bash
# 后端测试
cd backend
pytest tests/ -v

# 前端测试
cd frontend
npx playwright test
```

### 本地开发（不依赖 Docker）

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080

# 前端
cd frontend
npm install
npm run dev

# 需要本地安装 PostgreSQL 15 和 Redis 7
```

## 参考项目

- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (86.4k⭐) — 中文票据 OCR 引擎
- [Invoice-Manager](https://github.com/stone16/Invoice-Manager) — 双源验证架构参考
- [wechatpy](https://github.com/wechatpy/wechatpy) (4.3k⭐) — 企微加解密参考

## License

MIT
