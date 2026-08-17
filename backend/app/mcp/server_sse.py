"""MCP Server — SSE 模式独立入口

复用 server.py 中的 FastMCP 实例，包装成 ASGI app 供 uvicorn 启动。
"""

from __future__ import annotations

import logging
import os

from app.mcp.server import create_mcp_server

logging.basicConfig(level=logging.INFO)

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080")
os.environ.setdefault("BACKEND_URL", BACKEND_URL)

mcp = create_mcp_server()

# FastMCP 暴露 ASGI app（SSE 模式）
app = mcp.sse_app()
