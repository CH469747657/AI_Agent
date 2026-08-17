# WeKnora 统一入口接入方案

> 文档状态：v1.0（与任务 #4 设计 WeKnora 接入方案同步）
> 更新日期：2026-08-13

## 1. 设计目标

将 WeKnora 作为 AI 报销智能体面向企业员工的**统一对话入口**，替代或并存于现有企微网关（wecom-gateway）。WeKnora 通过 MCP 协议与本地的报销后端对话引擎集成，实现：

- 员工在 WeKnora 聊天窗口完成发票上传、报销查询、无票报销、提交报销等操作。
- 管理员在 WeKnora 中完成审批、统计、周期封账等操作。
- 老板在 WeKnora 中查看只读的经营洞察。
- 复用现有后端 53 个意图、Role Gate、对话状态机，无需重写业务逻辑。

## 2. 集成架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  WeKnora SaaS / 私有化部署                                           │
│  • Skill：AI 报销助手                                                │
│  • MCP Client (SSE)                                                 │
└───────────────┬─────────────────────────────────────────────────────┘
                │ HTTPS / 企业内网
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  入口网关层（可选但建议）                                             │
│  • 反向代理：Nginx / Traefik / Cloudflare Tunnel                     │
│  • 鉴权：Bearer Token + IP 白名单                                    │
└───────────────┬─────────────────────────────────────────────────────┘
                │ HTTP
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  MCP Server SSE  :9000                                               │
│  backend/app/mcp/server.py / server_sse.py                           │
│  暴露 Tools：send_dialog_message, query_invoices,                    │
│             query_reimbursements, list_dialog_tools                  │
└───────────────┬─────────────────────────────────────────────────────┘
                │ HTTP (Docker 网络或本地回环)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Backend FastAPI  :8080 / 18080                                       │
│  POST /api/dialog/message                                            │
│  DialogEngine → NLU → Role Gate → FSM → Action Executor             │
└───────────────┬─────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PostgreSQL + Redis + LLM API + OCR 服务                             │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. 对接方式选择

| 方案 | 描述 | 优点 | 缺点 | 推荐度 |
|------|------|------|------|--------|
| **A. MCP SSE（推荐）** | WeKnora 作为 MCP Client，通过 SSE 连接本地 MCP Server | 协议标准化；WeKnora 自动发现工具；复用现有后端 | 需暴露公网入口；需鉴权 | ★★★ |
| B. 直接调用后端 API | WeKnora 直接 POST `/api/dialog/message` | 链路最短；无需 MCP Server | 需 WeKnora 自己维护意图路由和参数映射 | ★★☆ |
| C. 企微网关转发 | 保留 wecom-gateway，WeKnora 对接企微应用 | 不动现有渠道代码 | 多一层转发；WeKnora 对企微依赖强 | ★★☆ |

本方案采用 **方案 A：MCP SSE**。

## 4. WeKnora 侧配置

### 4.1 MCP Server 注册

| 配置项 | 值 |
|--------|-----|
| 名称 | `ai-reimbursement-agent` |
| 类型 | `SSE` |
| URL | `https://<your-domain>/sse`（生产）或 `https://xxxx.trycloudflare.com/sse`（本地测试） |
| Headers | `Authorization: Bearer <WEKNORA_MCP_TOKEN>` |

### 4.2 Skill 配置

| 配置项 | 建议值 |
|--------|--------|
| Skill 名称 | `AI 报销助手` / `发票上传助手` |
| 编码 | `ai_reimbursement` |
| 触发词 | 上传发票、我要报销、查询发票、查询报销单、无票报销、帮我看看这张票 |
| 默认工具 | `send_dialog_message` |
| 工具发现 | 调用 `list_dialog_tools` 获取完整能力清单 |

### 4.3 参数映射

| WeKnora 字段 | MCP Tool 参数 | 说明 |
|--------------|---------------|------|
| 用户唯一标识 | `user_id` | 建议与企业内部工号/企微 user_id 一致 |
| 用户输入文本 | `text` | 原始消息内容 |
| 用户角色 | `role` | 由 WeKnora 根据企业组织架构解析 |
| 是否有附件 | `has_attachment` | 图片/文件为 true |
| 附件 base64 | `attachment_base64` | WeKnora 下载媒体后编码 |
| 附件类型 | `attachment_file_type` | jpg / png / pdf / ofd |

## 5. 角色与权限映射

现有后端三角色体系：`employee` | `admin` | `boss`。

| WeKnora 企业身份 | 映射角色 | 数据范围 | 说明 |
|------------------|----------|----------|------|
| 普通员工 | `employee` | self | 上传、查询本人发票/报销单、自助洞察 |
| 财务/HR/行政 | `admin` | all | 审批、代提交、统计、周期管理 |
| 老板/高管 | `boss` | read_only_all | 只读的经营洞察 |

**注意**：当前后端 `/api/dialog/message` 不验证 `role` 来源，存在越权风险。生产环境必须由 WeKnora 或后端根据企业身份真实判定角色，不能由客户端声明。

## 6. 关键集成清单

### 6.1 后端已完成项

- [x] MCP Server 框架（FastMCP 2.0）
- [x] SSE 模式入口 `server_sse.py`
- [x] 4 个 MCP Tools 注册
- [x] `list_dialog_tools` 工具自描述
- [x] 53 个意图 + Role Gate + 对话状态机
- [x] 本地连接测试方案（cloudflared tunnel）

### 6.2 后端待完善项

- [ ] **MCP SSE 鉴权**：为 SSE 连接和 Tool 调用增加 Bearer Token 校验。
- [ ] **角色来源可信化**：WeKnora 传入的 role 需由企业组织架构决定，后端增加角色白名单校验。
- [ ] **IP 白名单 / 来源校验**：生产环境限制 WeKnora 出口 IP。
- [ ] **健康检查端点**：MCP Server 增加 `/health`。
- [ ] **超时与重试策略**：MCP Tool 调用后端超时配置（当前 30s）。
- [ ] **审计日志**：记录 WeKnora 渠道的对话和文件上传。
- [ ] **图片大小限制**：建议单张不超过 5MB，base64 后注意内存。

### 6.3 WeKnora 侧待确认项

- [ ] 是否支持 SSE 模式 MCP Server？
- [ ] 是否支持图片/文件 base64 编码上传？
- [ ] 是否支持 Tool 结果中的 Markdown 表格渲染？
- [ ] 是否支持 `quick_replies` 快捷回复按钮？
- [ ] 用户 ID、角色信息如何透传？
- [ ] 是否有固定的出口 IP 段用于白名单？

### 6.4 部署与运维项

- [ ] 生产域名 + HTTPS 证书
- [ ] 反向代理与负载均衡
- [ ] MCP Server 多实例部署（当前单进程 uvicorn）
- [ ] 监控：MCP 连接数、后端响应时间、错误率
- [ ] 容灾：后端不可用时的降级提示

## 7. 数据流示例

### 7.1 员工上传发票图片

```text
WeKnora 用户发送图片
  → WeKnora 下载图片 → base64
  → MCP Client 调用 send_dialog_message(
       user_id="E001",
       role="employee",
       has_attachment=true,
       attachment_base64="...",
       attachment_file_type="jpg"
     )
  → MCP Server → POST /api/dialog/message
  → DialogEngine → NLU 识别意图 emp_upload_invoice
  → Role Gate 校验通过
  → Action Executor 调用 OCR + LLM 识别
  → 返回 JSON：
     {
       "text": "已识别发票：\n- 发票号码：12345678\n- 金额：120.00 元\n- 销售方：XX 公司",
       "state": "idle",
       "intent": "emp_upload_invoice",
       "quick_replies": ["继续上传", "提交报销", "取消"]
     }
  → WeKnora 渲染文本 + 快捷按钮
```

### 7.2 管理员审批报销单

```text
WeKnora 用户输入：审批报销单 RB-2026-0001
  → send_dialog_message(user_id="A001", role="admin", text="...")
  → DialogEngine 识别 admin_approve_reimbursement
  → 校验 admin 权限
  → 执行审批
  → 返回审批结果
```

## 8. 风险与合规评估

| 风险 | 等级 | 说明 | 缓解措施 |
|------|------|------|----------|
| 未鉴权的外部 MCP 入口 | 高 | 当前 SSE 无认证，公网暴露后任何人可调 | 立即增加 Bearer Token + IP 白名单 |
| 角色越权 | 高 | role 由调用方声明 | 后端根据企业身份库校验；WeKnora 签名验证 |
| 数据泄露 | 中 | 发票图片、金额、报销人信息通过公网传输 | HTTPS 强制；Token 定期轮换；最小权限 |
| 单点故障 | 中 | MCP Server 单进程、后端单容器 | 多实例 + 反向代理 + 健康检查 |
| 图片大导致超时 | 低 | 大图 base64 后体积大 | 限制 5MB；压缩；异步处理 |
| LLM/OCR 服务不可用 | 中 | 识别失败 | 降级为“请稍后重试”或转人工 |
| 审计缺失 | 中 | 无法追溯 WeKnora 渠道操作 | 增加审计日志表和查询接口 |

## 9. 本地开发联调路径

沿用已有的本地测试方案：

1. 启动后端：`docker compose up -d`
2. 确认 MCP Server 运行：`curl http://localhost:9000/sse`
3. 启动 cloudflared：`cloudflared tunnel --url http://127.0.0.1:9000 --metrics 127.0.0.1:20241`
4. 在 WeKnora 注册 MCP Server（URL 为 tunnel 地址 + `/sse`）。
5. 测试触发词和工具调用。

详细步骤见：《WeKnora本地连接测试方案.md》

## 10. 下一步建议

1. **补齐鉴权**：在 `backend/app/mcp/server_sse.py` 中增加 `Authorization` Header 校验。
2. **角色可信化**：改造 `DialogRequest` 的角色解析逻辑，优先从 JWT/签名中解析。
3. **WeKnora 联调**：与 WeKnora 团队确认 SSE 支持、参数透传、附件编码格式。
4. **生产部署**：申请域名、部署反向代理、配置监控和日志。
5. **文档同步**：将本方案同步到项目 README 或 V2_DEVELOPMENT_PLAN。
