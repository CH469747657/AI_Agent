# WeKnora 本地连接测试方案（无需公网 HTTPS）

> 目标：在本地 Mac + Docker 环境下，让 WeKnora 公网 SaaS 能访问你本地的 AI 报销后端，完成端到端测试。
> 核心工具：cloudflared tunnel（免费、无需公网 IP、自动生成 HTTPS URL）。

---

## 一、前置条件

| 条件 | 要求 |
|------|------|
| 操作系统 | macOS（Intel/Apple Silicon 均可） |
| Docker | 已安装并运行 |
| Docker Compose | 已安装 |
| 本地后端 | 已能正常启动，端口 `18080` |
| 本地 MCP Server | 已能正常启动，端口 `9000` |
| 网络 | 能访问公网（用于 cloudflared tunnel） |

---

## 二、本地服务启动

### 2.1 启动后端服务

```bash
# 进入项目目录
cd /Users/chen/文档2026/skill技能测试/AI报销/ai-reimbursement-agent

# 启动后端、数据库、Redis、企微网关
docker-compose up -d

# 检查状态
docker-compose ps
```

确认后端健康：

```bash
curl http://localhost:18080/health
# 预期输出：{"status":"ok"}
```

### 2.2 启动 MCP Server（SSE 模式）

当前 MCP Server 没有独立的 Docker 服务，需要手动进入 backend 容器启动：

```bash
# 进入 backend 容器
docker exec -it ai-reimbursement-agent-backend-1 /bin/bash

# 在容器内启动 MCP Server SSE
cd /app
BACKEND_URL=http://localhost:8080 MCP_MODE=sse MCP_HOST=0.0.0.0 MCP_PORT=9000 python -m app.mcp.server --mode sse --host 0.0.0.0 --port 9000
```

> 注意：`localhost:8080` 是容器内部访问 backend 的端口（容器内 backend 监听 8080）。

验证 MCP Server：

```bash
# 在宿主机上测试
curl http://localhost:9000/health
# 或
curl http://localhost:9000/sse
```

---

## 三、安装 cloudflared tunnel

### 3.1 安装 cloudflared

```bash
# 使用 Homebrew 安装
brew install cloudflared

# 验证
cloudflared --version
```

### 3.2 暴露本地服务到公网

#### 暴露后端 API（18080）

```bash
cloudflared tunnel --url http://localhost:18080
```

输出示例：

```
2026-08-13T10:00:00Z INF |  Your quick Tunnel has been assigned ...
2026-08-13T10:00:00Z INF |  https://abc123-def456.trycloudflare.com
```

记下这个 URL：`https://abc123-def456.trycloudflare.com`

#### 暴露 MCP Server（9000）

另开一个终端：

```bash
cloudflared tunnel --url http://localhost:9000
```

记下这个 URL：`https://xyz789-abc012.trycloudflare.com`

---

## 四、WeKnora 侧配置

### 4.1 创建 MCP Server 连接

在 WeKnora 平台：

1. 进入「MCP 管理」或「工具管理」
2. 新建 MCP Server：
   - **名称**：`ai-reimbursement-local`
   - **类型**：`SSE`
   - **URL**：`https://xyz789-abc012.trycloudflare.com/sse`
   - **Headers**（可选）：
     ```
     Authorization: Bearer local-test-token
     ```

### 4.2 创建 Skill

1. 进入「Skill 管理」
2. 新建 Skill：
   - **名称**：`发票上传助手`
   - **编码**：`expense_invoice_upload`
   - **触发词**：
     - 上传发票
     - 传一张发票
     - 我要报销
     - 发票上传
   - **关联 MCP Server**：`ai-reimbursement-local`
   - **默认调用 Tool**：`send_dialog_message`
   - **参数映射**：
     - `user_id` → WeKnora 用户 ID
     - `text` → 用户输入文本
     - `role` → 固定值 `employee`
     - `has_attachment` → 是否有图片附件
     - `attachment_base64` → 图片 base64

### 4.3 测试对话

在 WeKnora 对话窗口输入：

```
上传发票
```

预期：WeKnora 调用 MCP Tool → 本地后端返回 → WeKnora 显示：

```
请上传发票图片或文件
```

---

## 五、测试用例

### 5.1 文本对话测试

| 测试项 | 输入 | 预期结果 |
|--------|------|----------|
| 问候 | 你好 | 返回问候语 + 快捷操作提示 |
| 查询发票 | 我的发票 | 返回最近 20 条发票列表 |
| 查询报销单 | 我的报销单 | 返回报销单列表 |
| 取消 | 取消 | 当前操作取消，回到 IDLE |
| 帮助 | 帮助 | 返回功能说明 |

### 5.2 图片上传测试

| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| 上传发票图片 | 发送一张发票图片 | 返回识别结果：发票号、金额、日期、销售方、分类 |
| 继续上传 | 再发一张图片 | 返回第二张识别结果 |
| 无票报销 | 输入「无票报销 120 元打车费」 | 生成无票报销记录 |
| 提交报销 | 输入「提交报销」 | 生成报销单草稿 |

### 5.3 异常测试

| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| 后端不可用 | 停止 backend 容器 | WeKnora 显示「服务暂时不可用，请稍后重试」 |
| MCP 超时 | 上传超大图片 | 超时后显示友好提示 |
| 无效角色 | 传入 role=xxx | 返回 400 错误，WeKnora 提示参数错误 |

---

## 六、本地测试架构图

```
┌─────────────────────────────────────────────────────────────────┐
│  WeKnora 公网 SaaS                                              │
│  • Skill：发票上传助手                                           │
│  • MCP Client → SSE                                             │
└───────────────┬─────────────────────────────────────────────────┘
                │ HTTPS
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  cloudflared tunnel                                             │
│  https://xyz789-abc012.trycloudflare.com/sse                    │
└───────────────┬─────────────────────────────────────────────────┘
                │ HTTP (本地)
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  MCP Server SSE  :9000                                          │
│  backend/app/mcp/server.py                                      │
└───────────────┬─────────────────────────────────────────────────┘
                │ HTTP (Docker 网络)
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Backend FastAPI :18080                                           │
│  POST /api/dialog/message                                         │
└───────────────┬─────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL :15432  +  Redis :6379                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 七、常见问题排查

### 7.1 cloudflared 连接不上

- 检查本地服务是否启动：`curl http://localhost:18080/health`
- 检查 cloudflared 是否正常运行
- 尝试更换 tunnel URL（重新运行 cloudflared）

### 7.2 WeKnora 调用 MCP 失败

- 检查 MCP Server URL 是否以 `/sse` 结尾
- 检查 WeKnora 是否能访问公网 URL（用浏览器打开）
- 查看 MCP Server 日志：
  ```bash
  docker logs ai-reimbursement-agent-backend-1 -f
  ```

### 7.3 后端返回 500

- 查看后端日志：
  ```bash
  docker-compose logs -f backend
  ```
- 检查数据库是否健康：
  ```bash
  docker exec ai-reimbursement-agent-db-1 pg_isready -U reimburse
  ```

### 7.4 图片上传失败

- 检查图片大小（建议不超过 5MB）
- 检查 `attachment_base64` 是否完整
- 检查 `attachment_file_type` 是否正确（jpg/png/pdf/ofd）

---

## 八、清理环境

测试完成后：

```bash
# 停止 cloudflared tunnel
# 按 Ctrl+C 即可

# 停止后端服务
docker-compose down

# 如需清理数据（谨慎）
docker-compose down -v
```

---

## 九、下一步

本地测试跑通后，下一步：

1. **申请正式域名 + HTTPS 证书**
2. **部署正式 MCP Server SSE 到云服务器**
3. **配置 WeKnora 生产环境 MCP Server**
4. **添加鉴权（Bearer Token + IP 白名单）**
5. **接入审计日志和监控**

---

> 本方案无需公网 HTTPS 入口，利用 cloudflared tunnel 即可在本地完成 WeKnora 与现有后端的端到端联调。
