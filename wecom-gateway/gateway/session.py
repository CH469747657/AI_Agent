"""Redis 会话状态管理

管理企微用户的交互会话，支持：
- 多轮对话上下文
- 批量提交模式（用户连续发送多张票据）
- 待确认状态（LLM 需要用户补充信息时）
"""

import json
import time
from typing import Optional

import redis.asyncio as redis


# ===== 会话状态常量 =====
STATE_IDLE = "idle"                    # 空闲
STATE_BATCH = "batch"                  # 批量提交中
STATE_WAIT_CATEGORY = "wait_category"  # 等待用户确认费用分类
STATE_WAIT_PROJECT = "wait_project"    # 等待用户选择项目
STATE_WAIT_AMOUNT = "wait_amount"      # 等待用户补充金额（无票报销）
STATE_WAIT_REASON = "wait_reason"      # 等待用户输入报销事由

# 会话TTL（2小时不活跃自动清除）
SESSION_TTL = 7200

# 命令关键词
CMD_HELP = {"帮助", "help", "?"}
CMD_DONE = {"完成", "提交", "done", "end"}
CMD_CANCEL = {"取消", "cancel"}
CMD_QUERY = {"查询", "我的", "统计", "summary"}
CMD_REPORT = {"报表", "报告", "report", "导出"}
CMD_NORECEIPT = {"无票", "无发票", "no-receipt"}


class SessionManager:
    """企微用户会话管理器"""

    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)

    def _key(self, user_id: str) -> str:
        return f"wecom:session:{user_id}"

    async def get_state(self, user_id: str) -> dict:
        """获取用户会话状态，不存在则返回默认"""
        raw = await self.redis.get(self._key(user_id))
        if raw:
            return json.loads(raw)

        # 默认会话
        return {
            "state": STATE_IDLE,
            "user_id": user_id,
            "batch_count": 0,
            "batch_invoice_ids": [],
            "pending_invoice_id": None,
            "pending_type": None,     # "category" 或 "project"
            "pending_options": [],
            "updated_at": time.time(),
        }

    async def save_state(self, user_id: str, state: dict):
        """保存会话状态"""
        state["updated_at"] = time.time()
        await self.redis.setex(
            self._key(user_id),
            SESSION_TTL,
            json.dumps(state, ensure_ascii=False),
        )

    async def reset_to_idle(self, user_id: str):
        """重置为空闲状态（保留 user_id）"""
        state = await self.get_state(user_id)
        state["state"] = STATE_IDLE
        state["batch_count"] = 0
        state["batch_invoice_ids"] = []
        state["pending_invoice_id"] = None
        state["pending_type"] = None
        state["pending_options"] = []
        # 清理报表事由收集阶段的临时数据
        state.pop("report_invoice_ids", None)
        await self.save_state(user_id, state)

    async def start_batch(self, user_id: str):
        """开始批量提交模式"""
        state = await self.get_state(user_id)
        state["state"] = STATE_BATCH
        state["batch_count"] = 0
        state["batch_invoice_ids"] = []
        await self.save_state(user_id, state)

    async def add_to_batch(self, user_id: str, invoice_id: int):
        """添加发票到批量提交"""
        state = await self.get_state(user_id)
        state["batch_invoice_ids"].append(invoice_id)
        state["batch_count"] = len(state["batch_invoice_ids"])
        await self.save_state(user_id, state)

    async def set_pending(self, user_id: str, invoice_id: int,
                          pending_type: str, options: list = None):
        """设置待确认状态"""
        state = await self.get_state(user_id)
        state["state"] = (
            STATE_WAIT_CATEGORY if pending_type == "category"
            else STATE_WAIT_PROJECT
        )
        state["pending_invoice_id"] = invoice_id
        state["pending_type"] = pending_type
        state["pending_options"] = options or []
        await self.save_state(user_id, state)

    async def clear_pending(self, user_id: str):
        """清除待确认状态，回到批量模式或空闲"""
        state = await self.get_state(user_id)
        state["pending_invoice_id"] = None
        state["pending_type"] = None
        state["pending_options"] = []
        # 如果有批量中发票则回到批量模式，否则空闲
        state["state"] = (
            STATE_BATCH if state["batch_invoice_ids"] else STATE_IDLE
        )
        await self.save_state(user_id, state)
