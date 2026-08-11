"""NLU Router — 意图路由引擎

架构（重构后）：
1. 快速正则（help/cancel/greeting，<1ms，零成本）— 仅拦截零槽位确定性指令
2. LLM 大模型意图识别 + 槽位提取（1-3s，一步到位）— 所有语义查询统一走 LLM

设计原则：
- fast-path 只保留"取消/帮助/问候"这类零槽位、零歧义的指令
- 所有需要槽位提取的查询（发票统计/筛选/人员/审批/删除等）全部交给 LLM
- 彻底消除正则短路导致的槽位丢失和答非所问问题
"""

from __future__ import annotations

import re
import logging
from typing import Any

from .models import NluResult, NluLevel, UserRole, DialogContext, DialogState

logger = logging.getLogger(__name__)


# ============================================================
# 快速正则 — 仅保留零槽位、零歧义的确定性指令
# ============================================================
_FAST_RULES: list[tuple[str, re.Pattern]] = [
    ("common_cancel", re.compile(r"^(取消|算了|不做了|cancel|不要了|放弃)$")),
    ("common_help", re.compile(r"^(帮助|help|\?|？|怎么用|教我|能做什么|有什么功能)$")),
    ("common_greeting", re.compile(r"^(你好|在吗|hi|hello|嗨|你好啊|您好).*$")),
]

# 状态相关规则 — 仅在特定对话状态下触发（如分类/项目选择的纯数字输入）
_STATE_RULES: list[tuple[str, re.Pattern, DialogState]] = [
    ("emp_confirm_category", re.compile(r"^\d+$"), DialogState.WAITING_CATEGORY),
    ("emp_confirm_project", re.compile(r"^\d+$|^项目\d+"), DialogState.WAITING_PROJECT),
]


class NluRouter:
    """NLU 路由器 — 快速正则 + LLM

    正则只拦截零歧义指令；所有语义查询由 LLM 处理。
    """

    def __init__(self):
        self._compile_rules()

    def _compile_rules(self) -> None:
        """预编译正则规则"""
        self._fast_rules: list[tuple[str, re.Pattern]] = [
            (name, pattern) for name, pattern in _FAST_RULES
        ]
        self._state_rules: list[tuple[str, re.Pattern, DialogState]] = [
            (name, pattern, state) for name, pattern, state in _STATE_RULES
        ]

    def classify(
        self,
        text: str,
        context: DialogContext,
        has_attachment: bool = False,
    ) -> NluResult:
        """意图识别主入口

        流程：
        1. 带附件 → 上传发票意图（硬编码）
        2. 状态相关正则（如分类选择/项目选择状态下的纯数字输入）
        3. 快速正则（cancel/help/greeting，零歧义指令）
        4. 返回空结果 → 由 Dialog Engine 调用 LLM
        """
        text_stripped = text.strip()

        # 特殊处理：带附件的消息 → 上传发票意图
        if has_attachment:
            return NluResult(
                intent_name="emp_upload_invoice",
                confidence=0.99,
                level=NluLevel.L1_KEYWORD,
                raw_text=text,
                extracted_slots={"image_file": True},
            )

        # 状态相关正则优先（如 WAITING_CATEGORY 状态下输入纯数字）
        for name, pattern, required_state in self._state_rules:
            if context.state == required_state and pattern.search(text_stripped):
                return NluResult(
                    intent_name=name,
                    confidence=0.95,
                    level=NluLevel.L1_KEYWORD,
                    raw_text=text,
                )

        # 快速正则（cancel > help > greeting）— 零歧义指令
        for target_name in ["common_cancel", "common_help", "common_greeting"]:
            for name, pattern in self._fast_rules:
                if name == target_name and pattern.search(text_stripped):
                    return NluResult(
                        intent_name=name,
                        confidence=0.98,
                        level=NluLevel.L1_KEYWORD,
                        raw_text=text,
                    )

        # 快速正则未命中 → 返回空，由 Dialog Engine 调用 LLM
        logger.debug("Fast rules no match for text=%r role=%s state=%s", text, context.role, context.state)
        return NluResult(
            intent_name="",
            confidence=0.0,
            level=NluLevel.L1_KEYWORD,
            raw_text=text,
        )

    def try_fast_path(self, text: str, role: str) -> NluResult | None:
        """Fast-path 正则匹配 — 已废弃，保留空实现供 Dialog Engine 调用

        所有语义查询现在统一走 LLM，fast-path 正则规则已全部移除。
        返回 None 表示未命中，继续走 LLM 路径。
        """
        return None

    def is_recognized(self, result: NluResult) -> bool:
        """是否成功识别意图"""
        return bool(result.intent_name) and result.confidence > 0.5

    # ============================================================
    # 槽位提取 — 保留用于 L1 快速正则命中的场景
    # LLM 命中的意图已在 classify 时提取了槽位，不需要再调用
    # ============================================================

    @staticmethod
    def extract_slots(text: str, intent_name: str) -> dict[str, Any]:
        """从用户文本中提取槽位值（仅 L1 快速正则命中时需要）

        LLM 命中的意图已自带 extracted_slots，不需要走此方法。
        """
        slots: dict[str, Any] = {}
        # 目前快速正则命中的意图（help/cancel/greeting/upload/confirm）都不需要槽位
        return slots
