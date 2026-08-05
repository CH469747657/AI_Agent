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

# 发票报销智能助手

基于 **OCR + LLM 双源验证** 的报销预审系统，以企业微信为交互入口，实现票据自动识别、验真查重、费用分类、项目归属和报表生成全链路智能化。

## 核心能力

| 能力 | 说明 |
|------|------|
| 票据识别 | PaddleOCR 提取结构化字段 + LLM Vision 语义解析，双源交叉验证 |
| 智能分类 | 三层策略：规则匹配 → LLM语义分类 → 人工兜底 |
| 项目归属 | LLM实体抽取 → 供应商关联 → 候选项目询问 |
| 查重三级 | 发票号精确 → 金额+日期+销售方模糊 → pHash图像哈希 |
| 报表生成 | Excel（分Sheet含公式） + PDF（HTML模板） + ZIP票据归档 |
| 企微交互 | 图片发送即识别，文字命令操作，异步推送结果 |

## 系统架构

```
企业微信用户 ──→ 企微回调 ──→ wecom-gateway (FastAPI:8090)
                    │                  │
                    │           ┌──────┴──────┐
                    │           │  1.解密消息  │
                    │           │  2.下载媒体  │
                    │           │  3.会话管理  │
                    │           └──────┬──────┘
                    │                  │ HTTP
                    │                  ▼
                    │         backend (FastAPI:8080)
                    │           ┌──────┴──────┐
                    │           │ OCR Service  │ PaddleOCR
                    │           │ LLM Service  │ Qwen-VL / GPT-4o
                    │           │ Diff Engine  │ 双源比对
                    │           │ Classifier   │ 三层分类
                    │           │ DupChecker   │ 三级查重
                    │           │ Report Gen   │ Excel+PDF
                    │           └──────┬──────┘
                    │                  │
                    │         ┌────────┴────────┐
                    │         │  PostgreSQL+     │
                    │         │  pgvector        │
                    │         │  Redis           │
                    │         └─────────────────┘
                    │
            企微API ◄── 主动推送处理结果（异步）
```

## 技术栈

- **后端**: Python 3.10 + FastAPI + SQLAlchemy + asyncpg
- **OCR**: PaddleOCR 2.7（中文票据优化）
- **LLM**: Qwen-VL-Plus（主） / GPT-4o（辅），兼容多Provider
- **数据库**: PostgreSQL 15 + pgvector（向量检索）
- **缓存**: Redis 7（会话、队列、access_token）
- **企微网关**: FastAPI + pycryptodome（AES-CBC加解密）
- **报表**: openpyxl（Excel）+ WeasyPrint（PDF）
- **部署**: Docker Compose

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
cd ai-reimbursement-agent

# 复制环境变量配置
cp .env.example .env

# 编辑 .env 填入你的配置
vi .env
```

### 2. 环境变量说明

```ini
# LLM 配置
LLM_PROVIDER=qwen           # qwen | openai | deepseek | anthropic
LLM_API_KEY=sk-xxx          # 你的API Key
LLM_MODEL=qwen-vl-plus      # 视觉模型推荐 qwen-vl-plus / gpt-4o

# 企业微信配置（在企微管理后台获取）
WECOM_CORP_ID=ww1234...
WECOM_SECRET=xxx...
WECOM_TOKEN=自定义Token
WECOM_ENCODING_AES_KEY=43位EncodingAESKey
```

### 3. 启动服务

```bash
# 一键启动全部服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看后端日志
docker-compose logs -f backend

# 查看企微网关日志
docker-compose logs -f wecom-gateway
```

### 4. 服务地址

| 服务 | 地址 |
|------|------|
| 后端 API | http://localhost:18080 |
| API 文档 (Swagger) | http://localhost:18080/docs |
| 企微网关 | http://localhost:18090/wecom/callback |
| 网关健康检查 | http://localhost:18090/health |
| PostgreSQL | localhost:15432 |
| Redis | localhost:6379 |

### 5. 企业微信回调配置

1. 登录[企业微信管理后台](https://work.weixin.qq.com/)
2. 应用管理 → 自建应用 → 创建应用
3. 接收消息 → 设置API接收
   - URL: `https://你的域名:18090/wecom/callback`
   - Token: 与 `.env` 中 `WECOM_TOKEN` 一致
   - EncodingAESKey: 与 `.env` 中 `WECOM_ENCODING_AES_KEY` 一致
4. 配置自定义菜单（可选）：
   - 上传发票 (KEY: upload_receipt)
   - 无票报销 (KEY: no_receipt)
   - 我的票据 (KEY: query_status)
   - 导出报表 (KEY: generate_report)

## 项目结构

```
ai-reimbursement-agent/
├── docker-compose.yml          # 容器编排
├── .env.example                # 环境变量模板
├── README.md                   # 本文件
│
├── backend/                    # 后端 API 服务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # FastAPI 入口
│       ├── config.py           # 配置管理
│       ├── database.py         # 数据库连接
│       ├── models/             # SQLAlchemy 数据模型
│       │   ├── base.py
│       │   ├── project.py      # 项目
│       │   ├── invoice.py      # 发票（含查重/验真/分类状态）
│       │   └── reimbursement.py # 报销单
│       ├── prompts/            # LLM 提示词
│       │   └── invoice_prompts.py
│       ├── services/           # 核心业务逻辑
│       │   ├── ocr_service.py       # PaddleOCR 服务
│       │   ├── llm_service.py       # 多Provider LLM 服务
│       │   ├── diff_engine.py       # 双源比对引擎
│       │   ├── classifier.py        # 三层费用分类
│       │   ├── project_matcher.py   # 项目归属匹配
│       │   ├── duplicate_checker.py # 三级查重
│       │   ├── report_generator.py  # 报表生成
│       │   └── invoice_service.py   # 核心编排服务
│       ├── routers/            # API 路由
│       │   ├── invoices.py     # 发票上传/列表/统计/更新
│       │   ├── projects.py     # 项目 CRUD
│       │   ├── reports.py      # 报表生成/下载
│       │   └── wecom.py        # 企微交互专用接口
│       └── schemas/            # Pydantic 数据验证
│           └── __init__.py
│
├── wecom-gateway/              # 企业微信回调网关
│   ├── Dockerfile
│   ├── requirements.txt
│   └── gateway/
│       ├── main.py             # FastAPI 回调应用
│       ├── crypto.py           # 企微消息 AES-CBC 加解密
│       ├── session.py          # Redis 会话状态管理
│       └── wecom_client.py     # 企微 API 客户端
│
├── uploads/                    # 票据上传目录
└── reports/                    # 报表输出目录
```

## 核心流程

### 票据处理全链路

```
用户发送图片
    │
    ▼
企微网关接收 → 下载媒体文件 → base64编码
    │
    ▼
后端 /api/invoices/wecom-process
    │
    ├──→ OCR Service (PaddleOCR)  ──→ 结构化字段A
    ├──→ LLM Service (Qwen-VL)    ──→ 结构化字段B
    │                                    │
    │                              Diff Engine (12字段逐个比对)
    │                                    │
    │                    ┌───────────────┤
    │                    ▼               ▼
    │              匹配→自动确认    冲突→标记人工复核
    │
    ├──→ Classifier (规则→LLM→人工兜底)
    ├──→ ProjectMatcher (LLM抽取→供应商关联→候选询问)
    ├──→ DuplicateChecker (发票号→模糊→pHash)
    │
    ▼
保存到数据库 → 推送结果到企微
```

### 用户交互示例

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

用户: [发送第二张图片]
智能体: ...（同上）

用户: 完成
智能体: ✅ 已提交 2 张票据进入报销流程。

用户: 查询
智能体:
  ## 您的票据汇总
  > 共 3 张，总计 ¥1,560.00
  1. 中国石化 ¥350 [交通费-燃油费]
  2. 全季酒店 ¥890 [住宿费]
  3. 滴滴出行 ¥320 [交通费-网约车]
```

## API 接口

### 发票管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/invoices/upload` | 上传票据文件（multipart） |
| POST | `/api/invoices/wecom-process` | 企微网关转发（base64图片） |
| POST | `/api/invoices/no-receipt` | 无票报销（文字描述） |
| GET | `/api/invoices` | 发票列表（支持user_id/status过滤） |
| GET | `/api/invoices/{id}` | 发票详情 |
| PUT | `/api/invoices/{id}` | 更新发票（修正分类/项目/状态） |
| GET | `/api/invoices/statistics` | 统计数据 |

### 企微交互

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/wecom/invoices/{user_id}` | 用户发票摘要 |
| POST | `/api/wecom/invoices/{id}/confirm` | 确认发票分类 |
| GET | `/api/wecom/invoices/{id}/detail` | 发票详情（卡片展示用） |

### 项目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{id}` | 项目详情 |

### 报表生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/reports/generate` | 生成报表 |
| GET | `/api/reports/{id}/download` | 下载报表 |

## 开发计划

| 阶段 | 时间 | 目标 |
|------|------|------|
| Phase 1 | 2周 | 核心Demo：OCR+LLM双源验证+企微图片上传 |
| Phase 2 | 2周 | 业务完善：费用分类+项目归属+查重+报表 |
| Phase 3 | 2周 | 验真接入+生产部署+性能优化 |

## 参考项目

- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (86.4k⭐) — 中文票据OCR引擎
- [Invoice-Manager](https://github.com/stone16/Invoice-Manager) — 双源验证架构参考
- [wechatpy](https://github.com/wechatpy/wechatpy) (4.3k⭐) — 企微加解密参考

## License

MIT

> AI生成