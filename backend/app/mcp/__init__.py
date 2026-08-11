"""MCP 插件 — 企微智能机器人 + OpenClaw 对接后端对话引擎

提供 3 个 MCP Tool，供企微智能机器人通过 OpenClaw 调用后端：
1. send_dialog_message — 发送对话消息（支持附件/发票类型/用途/无凭证金额）
2. query_invoices — 查询用户发票列表
3. query_reimbursements — 查询用户报销单列表

设计原则：
- 仅做薄转发层，所有业务逻辑由后端对话引擎处理
- 后端完全零改动（调用 /api/dialog/message 等现有端点）
- MCP Tool 定义符合 OpenAI Function Calling 规范
"""

from .server import create_mcp_server

__all__ = ["create_mcp_server"]
