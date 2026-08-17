"""Agent Core — Function-Calling Agent 的 ReAct 循环（Step 3.1.4）

替代"LLM 输出意图字符串 → Python 字典路由"的传统模式，
让 LLM 通过 function calling 直接决定调用哪个 tool、传什么参数。

ReAct 循环（最多 N 步）：
1. 把 user message + visible tools + history 传给 LLM
2. LLM 返回 tool_call 或最终回复
3. 若是 tool_call：执行 tool，把结果作为 tool 消息喂回 LLM，回到步骤 1
4. 若是最终回复：返回

设计要点：
- max_steps=5：防止无限循环
- tool 执行前用 RoleGate.check_tool 校验权限（防 LLM 越权）
- tool 参数用 Pydantic 校验（防 LLM 传错参数类型）
- 失败优雅降级：tool 执行失败时把错误信息喂回 LLM，让它自我修正
"""

from __future__ import annotations

import json
import logging
import asyncio
import os
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from .models import DialogContext, UserRole
from .tool_registry import Tool
from .role_gate import RoleGate

logger = logging.getLogger(__name__)


# ============================================================
# AgentResponse
# ============================================================

class AgentResponse:
    """Agent 循环返回结果"""

    def __init__(
        self,
        text: str = "",
        tool_calls: list[dict] = None,
        final_response: str = "",
        steps_taken: int = 0,
        error: Optional[str] = None,
    ):
        self.text = text  # 用户可见回复（来自最终 LLM 输出或 tool 结果）
        self.tool_calls = tool_calls or []  # 执行过的 tool_call 列表
        self.final_response = final_response  # LLM 最终回复文本
        self.steps_taken = steps_taken  # 实际执行的步数
        self.error = error


# ============================================================
# AgentCore
# ============================================================

class AgentCore:
    """Function-Calling Agent 核心

    用法：
        core = get_agent_core()
        response = await core.run(
            user_msg="查陈辉上月差旅费",
            context=ctx,
            visible_tools=gate.get_visible_tools(role),
        )
    """

    MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "5"))
    TIMEOUT_SECONDS = 30.0

    def __init__(self):
        self._client = None
        self._model = None
        self._initialized = False
        self._role_gate = RoleGate()

    def _ensure_client(self):
        """延迟初始化 LLM 客户端"""
        if self._initialized:
            return
        try:
            from app.config import settings, LLM_PROVIDERS
            from openai import OpenAI

            base_url = settings.llm_base_url
            if not base_url:
                provider = settings.llm_provider.lower()
                provider_info = LLM_PROVIDERS.get(provider, {})
                base_url = provider_info.get("base_url", "")

            # Agent mode 用 narrate 模型（推理能力强）
            model = settings.get_model_for_task("insight_narrate")

            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=base_url,
            )
            self._model = model
            self._initialized = True
            logger.info("AgentCore initialized: model=%s", model)
        except Exception as e:
            logger.warning("Failed to init AgentCore client: %s", e)
            self._initialized = True

    async def run(
        self,
        user_msg: str,
        context: DialogContext,
        visible_tools: list[Tool],
        on_progress=None,
    ) -> AgentResponse:
        """运行 ReAct 循环

        Args:
            user_msg: 用户输入（含历史摘要）
            context: 对话上下文
            visible_tools: 角色可见的 Tool 列表
            on_progress: 进度回调

        Returns:
            AgentResponse
        """
        self._ensure_client()
        if not self._client:
            return AgentResponse(
                text="Agent 模式不可用：LLM 客户端未初始化",
                error="client_unavailable",
            )

        # 构造 OpenAI tool schemas
        tool_schemas = [t.to_openai_schema() for t in visible_tools]
        if not tool_schemas:
            return AgentResponse(
                text="当前角色无可用工具",
                error="no_tools",
            )

        # tool name → Tool 实例映射
        tool_map: dict[str, Tool] = {t.name: t for t in visible_tools}

        # 消息历史（含 system + user + 后续 tool_call/tool_result）
        messages: list[dict] = [
            {"role": "system", "content": self._build_system_prompt(context)},
            {"role": "user", "content": user_msg},
        ]

        response = AgentResponse()

        for step in range(self.MAX_STEPS):
            response.steps_taken = step + 1
            if on_progress:
                await on_progress(f"Agent 推理中（第 {step + 1} 步）…")

            try:
                llm_result = await asyncio.wait_for(
                    self._call_llm(messages, tool_schemas),
                    timeout=self.TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return AgentResponse(text="Agent 推理超时", error="timeout")
            except Exception as e:
                logger.warning("AgentCore LLM call failed at step %d: %s", step + 1, e)
                return AgentResponse(text=f"Agent 推理失败：{e}", error="llm_call_failed")

            if not llm_result:
                return AgentResponse(text="Agent 未返回有效响应", error="empty_response")

            # 解析 LLM 输出
            tool_calls = llm_result.get("tool_calls", [])
            content = llm_result.get("content", "")

            if not tool_calls:
                # LLM 给出最终回复
                response.final_response = content
                response.text = content
                # 折中方案：检测 tool 结果含表格但 LLM 未原样展示时，强制附加
                appended = self._append_missing_table(response, content)
                if appended:
                    response.text = content + appended
                    logger.info(
                        "AgentCore appended missing table to final response (tool=%s)",
                        response._last_table_tool,
                    )
                logger.info(
                    "AgentCore completed at step %d: text=%r",
                    step + 1, content[:80],
                )
                return response

            # 执行 tool_calls
            for tc in tool_calls:
                tool_name = tc.get("function", {}).get("name", "")
                args_str = tc.get("function", {}).get("arguments", "{}")
                tc_id = tc.get("id", "")

                logger.info(
                    "AgentCore step %d tool_call: %s args=%s",
                    step + 1, tool_name, args_str[:100],
                )

                tool = tool_map.get(tool_name)
                if not tool:
                    # LLM 调用了不可见的 tool（越权或幻觉）
                    perm = self._role_gate.check_tool(tool_name, context.role)
                    if not perm.allowed:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"错误：{perm.reason}",
                        })
                    else:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"错误：工具 {tool_name} 不在可见列表中",
                        })
                    response.tool_calls.append({
                        "name": tool_name, "args": args_str, "result": "permission_denied",
                    })
                    continue

                # 权限校验（防 LLM 越权）
                perm = self._role_gate.check_tool(tool_name, context.role)
                if not perm.allowed:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"权限不足：{perm.reason}",
                    })
                    response.tool_calls.append({
                        "name": tool_name, "args": args_str, "result": "permission_denied",
                    })
                    continue

                # Pydantic 参数校验
                try:
                    args_dict = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError as e:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"参数 JSON 解析失败：{e}",
                    })
                    response.tool_calls.append({
                        "name": tool_name, "args": args_str, "result": "invalid_json",
                    })
                    continue

                if tool.Parameters is not None:
                    try:
                        params = tool.Parameters.model_validate(args_dict)
                    except ValidationError as ve:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"参数校验失败：{ve}",
                        })
                        response.tool_calls.append({
                            "name": tool_name, "args": args_str, "result": "validation_failed",
                        })
                        continue
                else:
                    params = None

                # 执行 tool
                try:
                    from app.database import get_async_sessionmaker
                    sm = get_async_sessionmaker()
                    async with sm() as db:
                        result = await tool.run(context, db, params)

                    result_text = result.get("text", "") if isinstance(result, dict) else str(result)
                    result_data = result.get("data") if isinstance(result, dict) else None
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_text[:2000],  # 截断长结果（batch 表格不丢失）
                    })
                    response.tool_calls.append({
                        "name": tool_name, "args": args_str,
                        "result": "success", "data": result_data,
                        "result_text": result_text,  # 保留完整文本（含表格），供最终回复时附加
                    })
                    # 把 tool 结果文本作为候选最终回复
                    response.text = result_text

                    # legacy_fallback 降级：LLM 主动调用 legacy_fallback meta-tool
                    # 返回特殊 error，由 dialog_engine 切换到 legacy 路径处理
                    if isinstance(result_data, dict) and result_data.get("legacy_fallback"):
                        logger.info(
                            "AgentCore legacy_fallback: tool=%s, delegating to legacy path",
                            tool_name,
                        )
                        response.text = ""
                        response.error = "legacy_fallback"
                        return response

                    # follow_up 短路：tool 返回 follow_up（如上传发票后追问用途）
                    # 直接把 follow_up.prompt + batch 表格作为最终回复，跳出 ReAct 循环
                    if isinstance(result_data, dict) and result_data.get("follow_up"):
                        follow_up = result_data["follow_up"]
                        if follow_up.get("pending_invoice_id"):
                            context.pending_invoice_id = follow_up["pending_invoice_id"]
                        logger.info(
                            "AgentCore follow_up shortcut: tool=%s pending_invoice_id=%s",
                            tool_name, follow_up.get("pending_invoice_id"),
                        )
                        return response

                except Exception as e:
                    logger.exception("AgentCore tool %s execution failed: %s", tool_name, e)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"工具执行失败：{e}",
                    })
                    response.tool_calls.append({
                        "name": tool_name, "args": args_str, "result": f"error: {e}",
                    })

        # 达到 max_steps 仍未结束
        logger.warning("AgentCore reached max_steps=%d without final response", self.MAX_STEPS)
        if not response.text:
            response.text = "Agent 推理步数已达上限，请简化问题或稍后重试"
        response.error = "max_steps_reached"
        return response

    # 折中方案白名单：这些 tool 返回的表格需要保证呈现给用户
    TABLE_FORCING_TOOLS = {
        # 员工查询
        "emp_query_invoices", "emp_query_status", "emp_query_my_reimbursement",
        "self_insight_invoice_total", "self_insight_invoice_filter",
        "self_insight_category_amount", "self_insight_by_month",
        "self_insight_trend", "self_insight_top",
        # 员工上传/修改（操作后展示当前发票）
        "emp_upload_invoice", "emp_no_receipt", "emp_fill_invoice_desc",
        "emp_batch_upload", "emp_batch_describe", "emp_batch_modify",
        "emp_delete_invoice",
        # 管理员查询
        "admin_query_team", "admin_query_pending", "admin_query_person",
        "admin_query_detail", "admin_query_cycle_summary",
        "insight_invoice_total", "insight_invoice_filter",
        "insight_category_amount", "insight_by_dept", "insight_top",
        "admin_aggregate_invoices",
    }

    # Markdown 表格识别：表头 + 分隔行 + 至少 1 数据行
    _TABLE_RE = __import__("re").compile(
        r"\|[^\n]*\|\s*\n\|\s*[-:| ]+\s*\|\s*\n(?:\|[^\n]*\|\s*\n?)+",
        __import__("re").MULTILINE,
    )

    def _append_missing_table(self, response: AgentResponse, content: str) -> str:
        """检测 tool 结果含表格但 LLM 最终回复未展示时，返回需要附加的表格片段

        Returns: 附加的字符串（含分隔符 + 表格）；无需附加时返回空串
        """
        if not response.tool_calls:
            return ""

        # 从最后一次匹配白名单的 tool_call 倒序找
        for tc in reversed(response.tool_calls):
            tool_name = tc.get("name", "")
            if tool_name not in self.TABLE_FORCING_TOOLS:
                continue
            result_text = tc.get("result_text", "")
            if not result_text:
                continue

            # 提取该 tool 结果中的第一个 markdown 表格
            match = self._TABLE_RE.search(result_text)
            if not match:
                continue

            table = match.group(0).strip()
            if not table:
                continue

            response._last_table_tool = tool_name

            # 去重：如果 LLM 最终回复已含该表格的前两行（表头+分隔），认为已展示
            first_two_lines = "\n".join(table.split("\n")[:2]).strip()
            if first_two_lines and first_two_lines in content:
                return ""

            # 附加表格到回复末尾
            return f"\n\n{table}"

        return ""

    def _build_system_prompt(self, context: DialogContext) -> str:
        """构造 system prompt"""
        prompt = f"""你是AI报销智能体的 Agent 大脑。当前用户角色：{context.role.value}。

你可以调用工具完成用户请求。若信息不足，可调用工具查询；若工具返回错误，根据错误信息修正参数后重试。

规则：
1. 一次只调用必要的工具，避免冗余调用
2. 工具返回结果后，用自然语言向用户解释结果
3. 若用户请求不清晰，直接询问用户补充信息（不调用工具）
4. 不要编造数据，所有数据必须来自工具返回
5. **分类查询优先调 Tool**：用户问"我有哪些X费的发票""X费报了多少""X费明细"等分类查询时，
   即使"X费"看起来不是标准分类名（如"配合费""办公费""出行费"），也应优先调用
   self_insight_category_amount（员工）或 insight_category_amount（管理员）工具，
   fee_category_keyword 参数填入"X费"。系统会用 LLM 语义匹配发票的 subcategory/
   description 字段，能识别口语词与标准子类的等价关系（如"打车费"="差旅-交通 子类下用途
   为打车费的发票"）。若 Tool 返回空结果，再向用户说明无相关数据并提示可用分类。
6. **无关问题兜底**：用户问与报销无关的问题（天气/笑话/数学/翻译/股票/出行路线等），
   不调用任何工具，直接友好拒绝并说明本系统专注报销事务。
7. **表格强制展示**（核心规则，违反将导致用户体验严重退化）：
   - 工具返回结果中**只要含 markdown 表格**，最终回复**必须**原样输出该表格，禁止改写为散文或仅描述表格内容
   - 不要把表格内容拆解成"X 张发票，金额 Y，分别是 A、B、C..."这种叙述；表格本身就是展示形式
   - 仅在表格**前后**补充简要说明（如"共 X 张，合计 ¥Y"），不要在表格行间插入散文
   - 调用 `emp_query_invoices`、`admin_query_*`、`insight_invoice_*`、`insight_category_amount` 等
     返回列表的查询工具后，**100% 必须输出表格**给用户，即使你已用文字总结了结果
8. **缺失字段提醒**：上传发票后，若工具返回的发票信息中"用途"或"出差日期"为"待补充"或为空，
   必须在回复中明确提醒用户补充这两项字段（它们是自动生成报销单的核心依据）。
9. **用途+日期同时填**：用户回复补充用途时，若同一句话中**同时包含日期信息**（如
   "出差时间8月1日，项目投标费"/"7月15号出差，打车费"/"费用日期2026-08-01，住宿费"），
   必须调用 emp_fill_invoice_desc 工具时**同时**传入 purpose 和 expense_date 两个参数，
   不要把日期塞进 purpose、也不要丢弃日期。日期参数格式 YYYY-MM-DD（如 2026-08-01），
   用户只说"8月1日""7月15号"未带年份时，用当前年份 2026 补全。
10. **空结果也要出表格**：若查询类工具返回"暂无数据"或空列表，**仍需输出仅含表头的空表格**
    （表头 + 分隔行，无数据行），让用户知道字段结构 + 明确看到"没有数据"这一事实，而非仅一句话"暂无发票"。
    例如调用 emp_query_invoices 返回空时，回复应包含：
    ```
    | 序号 | 类型 | 销售方 | 金额 | 用途 | 出差日期 | 状态 | 上传时间 |
    |------|------|--------|------|------|----------|------|----------|
    ```
    然后说明"暂无符合条件的发票记录"。
11. **修改/删除失败时附加查询**：用户执行修改/删除类操作（emp_modify_field、admin_approve、
    admin_reject 等）但工具返回失败（如发票不存在、状态不符）时，应**主动调用查询工具**
    （emp_query_invoices 或 admin_query_*）展示当前用户的发票/报销单列表表格，让用户对照
    确认正确 ID 或状态后再操作。不要仅回一句"操作失败"就结束对话。
12. **引导用户上传时也附表格**：用户说"上传发票""再上传一张"但未附文件时，先按规则 8 引导
    用户上传，**同时**调用 emp_query_invoices 工具展示当前已有的发票列表表格，让用户对照
    上下文决定补充哪张发票的字段或继续上传。这避免用户问"再上传一张"时只收到一句空泛引导。
"""
        # follow_up 上下文：上一轮上传了发票，等待用户补充用途
        if context.pending_invoice_id:
            prompt += f"""
【当前上下文】上一轮上传了发票 #{context.pending_invoice_id}，正在等待用户补充用途描述。
若用户回复用途（如"打车费""差旅""办公用品"），请调用 emp_fill_invoice_desc 工具，purpose 参数填用户输入。
若用户回复中同时包含日期（如"出差时间8月1日，项目投标费"），请拆分为 purpose="项目投标费" + expense_date="2026-08-01" 两个参数同时传入，参见规则 9。
若用户说"跳过"或上传新发票，按用户意图处理，不要强制调 emp_fill_invoice_desc。
"""
        return prompt

    async def _call_llm(self, messages: list[dict], tools: list[dict]) -> dict:
        """调用 LLM（带 tools）"""
        try:
            resp = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1000,
                timeout=self.TIMEOUT_SECONDS,
            )

            choice = resp.choices[0].message
            tool_calls = []
            if choice.tool_calls:
                for tc in choice.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })

            return {
                "content": choice.content or "",
                "tool_calls": tool_calls,
            }
        except Exception as e:
            logger.warning("AgentCore _call_llm error: %s", e)
            return {}


# ============================================================
# 全局单例
# ============================================================

_core: Optional[AgentCore] = None


def get_agent_core() -> AgentCore:
    """获取 AgentCore 单例"""
    global _core
    if _core is None:
        _core = AgentCore()
    return _core


def reset_agent_core() -> None:
    """重置单例（测试用）"""
    global _core
    _core = None
