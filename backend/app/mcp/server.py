"""MCP Server — 企微智能机器人 + OpenClaw 对接后端对话引擎

使用 FastMCP 框架注册 3 个 MCP Tool，通过 HTTP 调用后端 API。
支持两种部署模式：
1. stdio 模式：OpenClaw 本地运行，通过 stdin/stdout 通信
2. SSE 模式：独立 HTTP 服务，OpenClaw 通过 Server-Sent Events 通信

环境变量：
- BACKEND_URL: 后端 API 地址（默认 http://localhost:18080）
- MCP_HOST: SSE 模式监听地址（默认 0.0.0.0）
- MCP_PORT: SSE 模式监听端口（默认 9000）
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# 后端 API 基地址
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:18080")


# ============================================================
# 后端 API 调用封装
# ============================================================

async def _post(path: str, payload: dict) -> dict:
    """异步 POST 请求到后端 API"""
    url = f"{BACKEND_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


async def _get(path: str, params: Optional[dict] = None) -> dict:
    """异步 GET 请求到后端 API"""
    url = f"{BACKEND_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


# ============================================================
# MCP Tool 实现
# ============================================================

async def send_dialog_message(
    user_id: str,
    text: str = "",
    role: str = "employee",
    has_attachment: bool = False,
    attachment_base64: Optional[str] = None,
    attachment_file_type: Optional[str] = None,
    receipt_type: Optional[str] = None,
    user_description: Optional[str] = None,
    no_receipt_amount: Optional[str] = None,
) -> str:
    """发送对话消息到后端对话引擎

    所有对话交互（上传发票、查询、审批等）都通过此接口完成。
    后端对话引擎自动识别意图、填充槽位、执行操作。

    Args:
        user_id: 用户标识（企微 user_id 或工号）
        text: 用户输入文本
        role: 用户角色 (employee|admin|boss)
        has_attachment: 是否包含图片/文件附件
        attachment_base64: 附件 base64 数据（图片/PDF/OFD）
        attachment_file_type: 附件文件类型 (jpg|pdf|ofd)
        receipt_type: 发票类型 (增值税普通发票|增值税专用发票|火车票|机票|收据|支付截图|交易流水单)
        user_description: 费用用途描述
        no_receipt_amount: 无凭证报销金额（如"120"）

    Returns:
        对话引擎的回复文本（含操作结果、追问、Markdown表格等）
    """
    payload = {
        "user_id": user_id,
        "text": text,
        "role": role,
        "has_attachment": has_attachment,
    }
    if attachment_base64:
        payload["attachment_base64"] = attachment_base64
    if attachment_file_type:
        payload["attachment_file_type"] = attachment_file_type
    if receipt_type:
        payload["receipt_type"] = receipt_type
    if user_description:
        payload["user_description"] = user_description
    if no_receipt_amount:
        payload["no_receipt_amount"] = no_receipt_amount

    try:
        result = await _post("/api/dialog/message", payload)
        # 返回结构化 JSON（对话引擎完整响应）
        return json.dumps(result, ensure_ascii=False, indent=2)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"后端返回 {e.response.status_code}", "detail": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "请求失败", "detail": str(e)}, ensure_ascii=False)


async def query_invoices(
    user_id: str,
    role: str = "employee",
) -> str:
    """查询用户发票列表

    通过对话引擎查询当前用户的发票列表（最近20条）。
    返回发票编号、销售方、金额、状态等结构化信息。

    Args:
        user_id: 用户标识
        role: 用户角色 (employee|admin|boss)

    Returns:
        发票列表的回复文本
    """
    try:
        result = await _post("/api/dialog/message", {
            "user_id": user_id,
            "text": "查询我的发票",
            "role": role,
        })
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": "查询失败", "detail": str(e)}, ensure_ascii=False)


async def query_reimbursements(
    user_id: str,
    role: str = "employee",
) -> str:
    """查询用户报销单列表

    通过对话引擎查询当前用户的报销单（含周期、费用/补贴明细、封账状态）。

    Args:
        user_id: 用户标识
        role: 用户角色 (employee|admin|boss)

    Returns:
        报销单列表的回复文本
    """
    try:
        result = await _post("/api/dialog/message", {
            "user_id": user_id,
            "text": "查询我的报销单",
            "role": role,
        })
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": "查询失败", "detail": str(e)}, ensure_ascii=False)


# ============================================================
# MCP Server 创建
# ============================================================

def create_mcp_server():
    """创建 MCP Server 实例并注册 Tools

    支持 stdio 和 SSE 两种模式部署。
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.error("mcp package not installed. Run: pip install mcp")
        raise

    mcp = FastMCP(
        name="ai-reimbursement",
        version="1.0.0",
        description="AI报销智能体 MCP 插件 — 企微智能机器人对话入口",
    )

    # 注册 Tool: send_dialog_message
    @mcp.tool(
        name="send_dialog_message",
        description=(
            "发送对话消息到AI报销智能体。"
            "支持所有对话交互：上传发票图片、查询报销进度、补充用途描述、修改字段、提交报销等。"
            "上传发票时需提供 attachment_base64 和 receipt_type。"
            "无凭证报销需提供 no_receipt_amount。"
        ),
    )
    async def _send_dialog_message(
        user_id: str,
        text: str = "",
        role: str = "employee",
        has_attachment: bool = False,
        attachment_base64: str | None = None,
        attachment_file_type: str | None = None,
        receipt_type: str | None = None,
        user_description: str | None = None,
        no_receipt_amount: str | None = None,
    ) -> str:
        return await send_dialog_message(
            user_id=user_id,
            text=text,
            role=role,
            has_attachment=has_attachment,
            attachment_base64=attachment_base64,
            attachment_file_type=attachment_file_type,
            receipt_type=receipt_type,
            user_description=user_description,
            no_receipt_amount=no_receipt_amount,
        )

    # 注册 Tool: query_invoices
    @mcp.tool(
        name="query_invoices",
        description="查询用户已上传的发票列表（最近20条），含编号、销售方、金额、状态。",
    )
    async def _query_invoices(user_id: str, role: str = "employee") -> str:
        return await query_invoices(user_id=user_id, role=role)

    # 注册 Tool: query_reimbursements
    @mcp.tool(
        name="query_reimbursements",
        description="查询用户的报销单列表，含报销周期、费用/补贴明细、封账状态。",
    )
    async def _query_reimbursements(user_id: str, role: str = "employee") -> str:
        return await query_reimbursements(user_id=user_id, role=role)

    return mcp


# ============================================================
# 入口 — 支持 stdio / SSE 两种模式
# ============================================================

def main():
    """MCP Server 入口

    默认 stdio 模式（OpenClaw 本地运行）。
    设置 MCP_MODE=sse 启用 SSE 模式（独立 HTTP 服务）。
    """
    import argparse

    parser = argparse.ArgumentParser(description="AI报销 MCP Server")
    parser.add_argument("--mode", choices=["stdio", "sse"], default=os.getenv("MCP_MODE", "stdio"), help="运行模式")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"), help="SSE 模式监听地址")
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "9000")), help="SSE 模式监听端口")
    args = parser.parse_args()

    mcp = create_mcp_server()

    if args.mode == "sse":
        logger.info("Starting MCP Server in SSE mode on %s:%s", args.host, args.port)
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        logger.info("Starting MCP Server in stdio mode")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
