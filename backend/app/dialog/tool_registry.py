"""Tool Registry — Function-Calling Agent 的 Tool 基类与注册表（Step 3.1.1）

把"LLM 输出意图字符串 → Python 字典路由"升级为"LLM 输出 tool_call → 通用执行循环"。

设计：
- Tool 基类：name / description / parameters (Pydantic) / handler / required_roles
- to_openai_schema()：生成 OpenAI Function Calling 兼容的 tool schema
- ToolRegistry：管理所有 Tool 实例，按角色过滤可见 tool

与现有 Intent 的关系：
- Tool 是 Intent 的"执行化"形态：Intent 描述"识别"，Tool 描述"执行"
- 一个 Intent 可对应一个 Tool（多数情况），也可不对应（如 common_help）
- Tool 的 parameters 用 Pydantic schema，比 Intent 的 required_slots 更严格
"""

from __future__ import annotations

import logging
from typing import Any, Callable, ClassVar, Optional, Type

from pydantic import BaseModel

from .models import UserRole

logger = logging.getLogger(__name__)


# ============================================================
# Tool 基类
# ============================================================

class Tool:
    """Function-Calling Tool 基类

    子类需覆盖：
    - name: 工具名（与 Intent.name 对齐，如 "emp_upload_invoice"）
    - description: 工具描述（供 LLM 决策时参考）
    - Parameters: Pydantic BaseModel 子类，定义工具参数 schema
    - required_roles: 允许调用此工具的角色列表
    - run(): 实际执行逻辑

    用法：
        class UploadInvoiceTool(Tool):
            name = "emp_upload_invoice"
            description = "上传发票图片/PDF/OFD"
            Parameters = UploadInvoiceParams
            required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]

            async def run(self, ctx, db, params) -> dict: ...
    """

    # 类属性（子类覆盖）
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    Parameters: ClassVar[Optional[Type[BaseModel]]] = None
    required_roles: ClassVar[list[UserRole]] = []

    def to_openai_schema(self) -> dict:
        """生成 OpenAI Function Calling 兼容的 tool schema

        Returns:
            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": {<json_schema>},
                }
            }
        """
        if self.Parameters is None:
            # 无参数工具
            params_schema: dict = {"type": "object", "properties": {}}
        else:
            params_schema = self.Parameters.model_json_schema()

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params_schema,
            },
        }

    async def run(
        self,
        ctx: Any,  # DialogContext
        db: Any,    # AsyncSession
        params: BaseModel,
    ) -> dict:
        """执行工具逻辑（子类必须覆盖）

        Args:
            ctx: 对话上下文（含 user_id / role / slots / history）
            db: 数据库 session
            params: Pydantic 校验后的参数

        Returns:
            {"text": "用户可见回复", "data": {...}}
        """
        raise NotImplementedError(f"Tool {self.name} did not implement run()")

    @classmethod
    def is_visible_to_role(cls, role: UserRole) -> bool:
        """检查工具是否对指定角色可见"""
        return role in cls.required_roles


# ============================================================
# _BridgeTool — 桥接现有 ActionExecutor handler 的 Tool 基类
# ============================================================
# Step 3.1.2：为避免重写 20+ handler，采用桥接模式：
# 每个 Tool 子类只声明元数据（name/description/Parameters/required_roles），
# run() 委托给 ActionExecutor 对应的 handler 方法。
# 后续若需脱离 ActionExecutor，子类覆盖 run() 即可。

class _BridgeTool(Tool):
    """桥接 ActionExecutor handler 的 Tool 基类

    子类需覆盖：
    - handler_method: str  ActionExecutor 中对应的方法名（如 "_handle_upload_invoice"）
    """

    handler_method: ClassVar[str] = ""

    async def run(self, ctx, db, params: BaseModel) -> dict:
        """委托给 ActionExecutor 的 handler 方法

        把 Pydantic params 字段回写到 ctx.slots（handler 统一从 ctx.slots 读参数），
        attachment 从 ctx.attachment_data 取（仅 _handle_upload_invoice 用，不进 LLM schema）。

        Args:
            ctx: DialogContext
            db: AsyncSession
            params: Pydantic 校验后的参数

        Returns:
            handler 返回的 dict
        """
        from .action_executor import get_action_executor
        executor = get_action_executor()
        handler = getattr(executor, self.handler_method, None)
        if not handler:
            return {
                "text": f"工具 {self.name} 的 handler {self.handler_method} 未实现",
                "data": {"not_implemented": True},
            }
        # 回写 params 到 ctx.slots（exclude_none 防止 None 覆盖已填槽位）
        if params is not None:
            for k, v in params.model_dump(exclude_none=True).items():
                ctx.fill_slot(k, v)
        # attachment 仅 _handle_upload_invoice 用，从 ctx 取（不进 LLM schema）
        attachment = getattr(ctx, "attachment_data", None)
        return await handler(ctx, db, attachment)


class _InsightBridgeTool(Tool):
    """桥接 InsightEngine handler 的 Tool 基类

    与 _BridgeTool 的区别：
    - _BridgeTool 委托给 ActionExecutor 的 _handle_* 方法（提单/查询/管理操作）
    - _InsightBridgeTool 委托给 InsightEngine.execute(intent_name, ctx, db)（洞察分析）

    子类需覆盖：
    - intent_name: str  对应 InsightEngine 的意图名（如 "self_insight_total"）
    """

    intent_name: ClassVar[str] = ""

    async def run(self, ctx, db, params: BaseModel) -> dict:
        """委托给 InsightEngine.execute"""
        from .insight_engine import get_insight_engine
        if not self.intent_name:
            return {
                "text": f"工具 {self.name} 未配置 intent_name",
                "data": {"not_implemented": True},
            }
        # 回写 params 到 ctx.slots（InsightEngine handler 统一从 ctx.slots 读参数）
        if params is not None:
            for k, v in params.model_dump(exclude_none=True).items():
                ctx.fill_slot(k, v)
        engine = get_insight_engine()
        return await engine.execute(self.intent_name, ctx, db)


# ============================================================
# ToolRegistry — 工具注册表
# ============================================================

class ToolRegistry:
    """工具注册表 — 管理所有 Tool 实例，按角色过滤"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具实例"""
        if not tool.name:
            raise ValueError("Tool.name must be set")
        if tool.name in self._tools:
            logger.warning("Tool %s already registered, overwriting", tool.name)
        self._tools[tool.name] = tool
        logger.debug("Tool registered: %s", tool.name)

    def get(self, name: str) -> Optional[Tool]:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_visible_tools(self, role: UserRole) -> list[Tool]:
        """获取角色可见的所有工具"""
        return [t for t in self._tools.values() if t.is_visible_to_role(role)]

    def get_openai_schemas(self, role: UserRole) -> list[dict]:
        """获取角色可见工具的 OpenAI schema 列表（供 LLM function calling）"""
        return [t.to_openai_schema() for t in self.get_visible_tools(role)]

    @property
    def size(self) -> int:
        return len(self._tools)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


# ============================================================
# 全局单例
# ============================================================

_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取 ToolRegistry 单例"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_tool_registry() -> None:
    """重置单例（测试用）"""
    global _registry
    _registry = None
