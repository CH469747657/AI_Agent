---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '0b208699-4af4-4bbb-be28-7c5d98c6b3c7'
  PropagateID: '0b208699-4af4-4bbb-be28-7c5d98c6b3c7'
  ReservedCode1: '1aa5f5e8-5148-4d19-aac6-8a11406eac0c'
  ReservedCode2: '1aa5f5e8-5148-4d19-aac6-8a11406eac0c'
---

# MCP 插件 — 企微智能机器人 + OpenClaw 对接后端对话引擎

## 依赖

```bash
pip install mcp httpx
```

## 部署方式

### 方式一：stdio 模式（推荐，OpenClaw 本地运行）

```bash
python -m app.mcp.server --mode stdio
```

### 方式二：SSE 模式（独立 HTTP 服务）

```bash
python -m app.mcp.server --mode sse --host 0.0.0.0 --port 9000
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| BACKEND_URL | http://localhost:18080 | 后端 API 地址 |
| MCP_MODE | stdio | 运行模式 (stdio/sse) |
| MCP_HOST | 0.0.0.0 | SSE 模式监听地址 |
| MCP_PORT | 9000 | SSE 模式监听端口 |

## MCP Tools

### 1. send_dialog_message
发送对话消息到AI报销智能体。支持所有对话交互。

**参数：**
- `user_id` (必填): 用户标识
- `text` (可选): 用户输入文本
- `role` (可选): 用户角色 (employee|admin|boss)
- `has_attachment` (可选): 是否包含附件
- `attachment_base64` (可选): 附件 base64 数据
- `attachment_file_type` (可选): 附件文件类型 (jpg|pdf|ofd)
- `receipt_type` (可选): 发票类型
- `user_description` (可选): 费用用途描述
- `no_receipt_amount` (可选): 无凭证报销金额

### 2. query_invoices
查询用户已上传的发票列表。

**参数：**
- `user_id` (必填): 用户标识
- `role` (可选): 用户角色

### 3. query_reimbursements
查询用户报销单列表。

**参数：**
- `user_id` (必填): 用户标识
- `role` (可选): 用户角色

## OpenClaw 配置示例

```json
{
  "mcpServers": {
    "ai-reimbursement": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "env": {
        "BACKEND_URL": "http://localhost:18080"
      }
    }
  }
}
```

> AI生成