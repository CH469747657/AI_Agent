"""对话引擎 API 路由

提供对话交互的 REST API 端点，供 Web Chat、企微、钉钉等渠道调用。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.dialog.dialog_engine import get_dialog_engine
from app.dialog.context_store import RedisContextStore
from app.dialog.models import UserRole, DialogState

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# 请求/响应模型
# ============================================================

class DialogRequest(BaseModel):
    """对话请求"""
    user_id: str = Field(..., description="用户标识（企微user_id或工号）")
    text: str = Field("", description="用户输入文本")
    role: str = Field("employee", description="用户角色: employee|admin|boss")
    has_attachment: bool = Field(False, description="是否包含图片/文件附件")
    attachment_base64: Optional[str] = Field(None, description="附件base64数据")
    attachment_file_type: Optional[str] = Field(None, description="附件文件类型: jpg/pdf/ofd")
    receipt_type: Optional[str] = Field(None, description="发票类型: 增值税普通发票/增值税专用发票/火车票/机票/收据/支付截图/交易流水单")
    user_description: Optional[str] = Field(None, description="用户描述的费用用途")
    no_receipt_amount: Optional[str] = Field(None, description="无凭证报销金额（前端\"无凭证\"弹窗传入，如\"120\"）")


class DialogAPIResponse(BaseModel):
    """对话响应"""
    text: str = Field(..., description="回复文本")
    state: str = Field(..., description="对话状态")
    intent: Optional[str] = Field(None, description="触发的意图")
    action_taken: bool = Field(False, description="是否执行了实际操作")
    need_user_input: bool = Field(False, description="是否等待用户输入")
    quick_replies: list[str] = Field(default_factory=list, description="快捷回复选项")
    error: Optional[str] = Field(None, description="错误信息")
    data: Optional[dict] = Field(None, description="操作返回的附加数据（如 invoice_id）")


class DialogStateResponse(BaseModel):
    """对话状态查询响应"""
    user_id: str
    state: str
    role: str
    current_intent: Optional[str]
    turn_count: int
    history: List[Any] = []


# ============================================================
# API 端点
# ============================================================

@router.post("/message", response_model=DialogAPIResponse)
async def send_message(req: DialogRequest):
    """发送消息，获取对话引擎响应

    通用对话入口，所有渠道（Web/企微/钉钉/飞书）统一调用此接口。
    """
    # 解析角色
    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的角色: {req.role}")

    engine = get_dialog_engine()

    # 构造附件数据，包含前端传入的文件类型
    attachment_data = {"base64": req.attachment_base64} if req.attachment_base64 else None
    if attachment_data and req.attachment_file_type:
        attachment_data["file_type"] = req.attachment_file_type

    response = await engine.process_message(
        user_id=req.user_id,
        text=req.text,
        role=role,
        has_attachment=req.has_attachment,
        attachment_data=attachment_data,
        receipt_type=req.receipt_type,
        user_description=req.user_description,
        no_receipt_amount=req.no_receipt_amount,
    )

    # 从 action_result 中提取 data 字段（包含 invoice_id 等前端可用的附加数据）
    action_data: Optional[dict] = None
    if isinstance(response.action_result, dict):
        d = response.action_result.get("data")
        if d:
            action_data = d

    return DialogAPIResponse(
        text=response.text,
        state=response.state.value,
        intent=response.intent_name,
        action_taken=response.action_taken,
        need_user_input=response.need_user_input,
        quick_replies=response.quick_replies,
        error=response.error,
        data=action_data,
    )


@router.get("/state/{user_id}", response_model=DialogStateResponse)
async def get_state(user_id: str):
    """查询用户当前对话状态（调试用）"""
    engine = get_dialog_engine()
    state = await engine.get_user_state(user_id)
    if not state:
        return DialogStateResponse(
            user_id=user_id,
            state="idle",
            role="employee",
            current_intent=None,
            turn_count=0,
            history=[],
        )
    return DialogStateResponse(
        user_id=state.get("user_id", user_id),
        state=state.get("state", "idle"),
        role=state.get("role", "employee"),
        current_intent=state.get("current_intent"),
        turn_count=state.get("turn_count", 0),
        history=state.get("history", []),
    )


@router.post("/reset/{user_id}")
async def reset_context(user_id: str):
    """重置用户对话上下文"""
    engine = get_dialog_engine()
    await engine.reset_user_async(user_id)
    return {"status": "ok", "message": "对话上下文已重置"}


@router.get("/health")
async def store_health():
    """上下文存储健康检查 + 定时任务状态"""
    engine = get_dialog_engine()
    store = engine._store

    # 存储健康
    if isinstance(store, RedisContextStore):
        store_info = await store.health_check()
    else:
        store_info = {"backend": "memory", "active_contexts": len(store._store)}

    # 定时任务状态
    from app.services.scheduler_service import _scheduler
    scheduler_info = {
        "running": _scheduler is not None and _scheduler.running,
        "jobs": [j.id for j in _scheduler.get_jobs()] if _scheduler and _scheduler.running else [],
    }

    return {**store_info, "scheduler": scheduler_info}


@router.get("/intents")
async def list_intents(role: str = "employee"):
    """列出指定角色可用的所有意图"""
    try:
        user_role = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的角色: {role}")

    from app.dialog.intent_registry import get_intents_for_role
    intents = get_intents_for_role(user_role)
    return {
        "role": role,
        "count": len(intents),
        "intents": [
            {
                "code": i.code,
                "name": i.name,
                "description": i.description,
                "nlu_level": f"L{i.nlu_level.value}",
                "required_slots": i.required_slots,
                "optional_slots": i.optional_slots,
            }
            for i in intents
        ],
    }
