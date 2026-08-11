"""Dialog Engine — 对话引擎主编排器

编排流程:
    用户消息 → 快速正则（help/cancel/greeting）
             → LLM NLU（意图识别 + 槽位提取）
             → Role Gate（权限校验）
             → Dialog FSM（状态机 + 槽位填充）
             → Action Executor（调用后端服务）
             → Response（回复用户）

架构:
    - 快速正则: help/cancel/greeting（<1ms，零成本）
    - LLM NLU: 单层大模型意图理解 + 槽位提取（1-3s）
    - 三角色权限校验 + 员工洞察自动降级
    - 多轮对话槽位填充
    - Action Executor + Insight Engine
    - Redis 上下文持久化（不可用时优雅降级到内存存储）
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import (
    DialogContext, DialogResponse, DialogState,
    NluLevel, NluResult, UserRole,
)
from .nlu_router import NluRouter
from .role_gate import RoleGate
from .dialog_fsm import DialogFSM
from .intent_registry import get_intent, get_intents_for_role
from .context_store import BaseContextStore, MemoryContextStore, RedisContextStore, KEY_PREFIX
from .context_resolver import resolve as resolve_context, is_query_intent

import json

logger = logging.getLogger(__name__)


class DialogEngine:
    """对话引擎 — 对话式AI报销智能体核心"""

    def __init__(self, store: Optional[BaseContextStore] = None):
        self.nlu_router = NluRouter()
        self.role_gate = RoleGate()
        self.fsm = DialogFSM()
        # 上下文存储 — 优先使用 Redis，否则回退到内存
        self._store: BaseContextStore = store or MemoryContextStore()
        # Action executor — 延迟初始化（避免循环导入）
        self._action_executor = None

    def _ensure_action_executor(self):
        """延迟初始化 Action Executor（避免启动时循环导入）"""
        if self._action_executor is None:
            try:
                from .action_executor import get_action_executor
                self._action_executor = get_action_executor()
                logger.info("Action executor initialized")
            except Exception as e:
                logger.warning("Failed to init action executor: %s", e)
        return self._action_executor

    async def get_context(self, user_id: str, role: UserRole = UserRole.EMPLOYEE) -> DialogContext:
        """获取或创建用户对话上下文（从持久化存储读取）"""
        ctx = await self._store.get(user_id)
        if ctx is None:
            ctx = DialogContext(user_id=user_id, role=role)
            await self._store.set(ctx)
            logger.info("Created new dialog context for user=%s role=%s", user_id, role)
        else:
            # 如果角色发生变化，更新角色
            if ctx.role != role:
                ctx.role = role
                await self._store.set(ctx)
                logger.info("Updated role for user=%s to %s", user_id, role)
        return ctx

    async def process_message(
        self,
        user_id: str,
        text: str,
        role: UserRole = UserRole.EMPLOYEE,
        has_attachment: bool = False,
        attachment_data: Optional[dict] = None,
        receipt_type: Optional[str] = None,
        user_description: Optional[str] = None,
        no_receipt_amount: Optional[str] = None,
    ) -> DialogResponse:
        """处理用户消息 — 对话引擎主入口

        Args:
            user_id: 用户标识（企微 user_id 或工号）
            text: 用户输入文本
            role: 用户角色
            has_attachment: 是否包含图片/文件附件
            attachment_data: 附件数据（base64、文件路径等）
            receipt_type: 前端传入的发票类型（弹窗选择）
            user_description: 前端传入的费用用途（弹窗输入）
            no_receipt_amount: 无凭证报销金额（前端"无凭证"弹窗传入）

        Returns:
            DialogResponse 对话响应
        """
        context = await self.get_context(user_id, role)
        context.current_text = text  # 供 Insight Engine 解析时间段/实体名

        # ===== Step 0: 注入前端传入的槽位/参数 =====
        # 弹窗收集的发票类型和用途，供 Action Executor 使用
        if receipt_type:
            context.fill_slot("receipt_type", receipt_type)
        if user_description:
            context.user_description = user_description

        # ===== Step 0.5: 无凭证报销 — 绕过 NLU，直接走 emp_no_receipt =====
        # 前端"无凭证"弹窗传入金额+原因，一步到位，不需要多轮追问
        if no_receipt_amount and not has_attachment:
            no_receipt_intent = get_intent("emp_no_receipt")
            if no_receipt_intent:
                context.set_intent(
                    no_receipt_intent.name,
                    no_receipt_intent.required_slots,
                    no_receipt_intent.optional_slots,
                )
                context.fill_slot("amount", no_receipt_amount)
                context.fill_slot("description", user_description or "")
                logger.info(
                    "No-receipt shortcut: user=%s amount=%s desc=%s",
                    user_id, no_receipt_amount, (user_description or "")[:30],
                )
                # 构造一个完整的 NluResult，跳过后续 NLU 流程
                nlu_result = NluResult(
                    intent_name="emp_no_receipt",
                    confidence=1.0,
                    level=NluLevel.L1_KEYWORD,
                    raw_text=text or "无凭证报销",
                    extracted_slots={
                        "amount": no_receipt_amount,
                        "description": user_description or "",
                    },
                )
                # 跳到 Step 3（FSM 状态机处理）
                response = self.fsm.process(nlu_result, context, text or "无凭证报销", False)
                # 槽位已完整，直接执行
                if response.intent_name and not response.need_user_input:
                    response = await self._try_execute(response, context, attachment_data)
                # 持久化上下文
                await self._store.set(context)
                logger.info(
                    "Dialog processed (no-receipt): user=%s intent=%s state=%s",
                    user_id, response.intent_name, response.state,
                )
                return response

        # ===== Step 1: 快速正则意图识别（help/cancel/greeting + 附件）=====
        nlu_result = self.nlu_router.classify(text, context, has_attachment)

        # ===== Step 1.5: Fast-path 正则（高频易混淆意图快速匹配）=====
        if not nlu_result.intent_name and not has_attachment:
            fast_path_result = self.nlu_router.try_fast_path(text, context.role.value)
            if fast_path_result and fast_path_result.intent_name:
                nlu_result = fast_path_result

        # ===== Step 2: LLM NLU 意图理解（快速正则 + fast-path 未命中时调用）=====
        if not nlu_result.intent_name and not has_attachment:
            llm_result = await self._try_llm_nlu(text, context)
            if llm_result and llm_result.intent_name:
                # LLM 角色过滤兜底：LLM 可能返回该角色不可用的意图
                perm = self.role_gate.check(llm_result.intent_name, role)
                if not perm.allowed:
                    logger.warning(
                        "LLM NLU returned blocked intent: intent=%s role=%s, discarding",
                        llm_result.intent_name, role,
                    )
                else:
                    nlu_result = llm_result
            elif llm_result and llm_result.extracted_slots:
                # LLM 未识别意图但提取了槽位 → 保留槽位供状态机使用
                nlu_result.extracted_slots = llm_result.extracted_slots

        # ===== Step 1.5: 槽位补充（仅 L1 快速正则命中时需要，LLM 已自带槽位）=====
        if nlu_result.intent_name and nlu_result.level == NluLevel.L1_KEYWORD and not has_attachment:
            nlu_result.extracted_slots.update(
                self.nlu_router.extract_slots(text, nlu_result.intent_name)
            )

        # ===== Step 1.7: 上下文继承（仅 IDLE 状态、无附件时）=====
        # 从对话历史补全或继承槽位，解决多轮对话「答非所问」
        if not has_attachment and context.state == DialogState.IDLE:
            nlu_result = resolve_context(nlu_result, context, text)

        # ===== Step 2: Role Gate 权限校验 =====
        if nlu_result.intent_name:
            perm = self.role_gate.check(nlu_result.intent_name, role)
            if not perm.allowed:
                # 员工被全局洞察拦截 → 智能降级为自我洞察
                if role == UserRole.EMPLOYEE and nlu_result.intent_name.startswith("insight_"):
                    degraded = self._degrade_insight_for_employee(nlu_result.intent_name)
                    if degraded:
                        logger.info(
                            "Insight degraded for employee: user=%s %s→%s",
                            user_id, nlu_result.intent_name, degraded,
                        )
                        nlu_result.intent_name = degraded
                        nlu_result.confidence *= 0.85  # 降级后略降置信度
                    else:
                        logger.warning(
                            "Permission denied: user=%s role=%s intent=%s reason=%s",
                            user_id, role, nlu_result.intent_name, perm.reason,
                        )
                        return DialogResponse(
                            text=f"您没有权限执行此操作：{perm.reason}",
                            state=context.state,
                            error="permission_denied",
                        )
                else:
                    logger.warning(
                        "Permission denied: user=%s role=%s intent=%s reason=%s",
                        user_id, role, nlu_result.intent_name, perm.reason,
                    )
                    return DialogResponse(
                        text=f"您没有权限执行此操作：{perm.reason}",
                        state=context.state,
                        error="permission_denied",
                    )

        # ===== Step 3: Dialog FSM 状态机处理 =====
        response = self.fsm.process(nlu_result, context, text, has_attachment)

        # ===== Step 3.5: 重新注入前端传入的发票类型 =====
        # FSM 的 set_intent 会清空所有槽位，Step 0 填入的 receipt_type 被清除
        # 此处需要在 Action Executor 之前补回，否则会回退到默认值"增值税普通发票"
        if receipt_type and response.intent_name == "emp_upload_invoice":
            context.fill_slot("receipt_type", receipt_type)

        # ===== Step 4: 执行实际操作（Action Executor）=====
        # common_cancel / common_help / common_greeting 由 FSM 或 SpecialIntents 处理，不需要 Action Executor
        _skip_exec = {"common_cancel", "common_help", "common_greeting"}
        if response.intent_name and not response.need_user_input and response.intent_name not in _skip_exec:
            response = await self._try_execute(response, context, attachment_data)

        # ===== Step 5: 特殊意图处理 =====
        response = self._handle_special_intents(response, context, nlu_result)

        # ===== Step 5.5: 记录对话历史（仅查询类、已完成的轮次）=====
        # 用于后续跨轮槽位继承与指代消解；提单/审批操作不入历史
        if (
            response.intent_name
            and is_query_intent(response.intent_name)
            and not response.need_user_input
        ):
            final_slots = {
                k: s.value for k, s in context.slots.items() if s.filled
            }
            extra_referents: dict = {}
            if isinstance(response.action_result, dict):
                result_data = response.action_result.get("data") or {}
                for k in ("invoice_id", "reimbursement_id"):
                    if result_data.get(k) is not None:
                        extra_referents[k] = result_data[k]
            context.add_history(
                intent=response.intent_name,
                slots=final_slots,
                text=text,
                extra_referents=extra_referents,
            )

        # ===== Step 6: 持久化上下文 =====
        await self._store.set(context)

        logger.info(
            "Dialog processed: user=%s intent=%s state=%s action_taken=%s",
            user_id, response.intent_name, response.state, response.action_taken,
        )

        return response

    async def _try_execute(
        self,
        response: DialogResponse,
        context: DialogContext,
        attachment_data: Optional[dict],
    ) -> DialogResponse:
        """执行实际操作 — 由 Action Executor 调用后端服务层

        支持 follow_up 机制：action 执行后可返回 follow_up 指令，
        要求 dialog_engine 将上下文切换到 WAITING 状态等待用户补充信息。
        典型场景：上传发票后自动追问费用用途 → 用户输入描述 → 更新发票。
        """
        executor = self._ensure_action_executor()
        if executor:
            try:
                result = await executor.execute(
                    intent_name=response.intent_name,
                    context=context,
                    attachment_data=attachment_data,
                )
                response.action_taken = True
                response.action_result = result
                if result and "text" in result:
                    response.text = result["text"]

                # 处理 follow_up 指令 — action 执行后需要追问用户
                if result and "data" in result and result["data"].get("follow_up"):
                    fu = result["data"]["follow_up"]
                    fu_intent_name = fu.get("intent")
                    fu_state_str = fu.get("state")

                    # 获取意图定义并初始化槽位
                    fu_intent = get_intent(fu_intent_name)
                    if fu_intent:
                        context.set_intent(
                            fu_intent.name,
                            fu_intent.required_slots,
                            fu_intent.optional_slots,
                        )
                        logger.info(
                            "Follow-up triggered: intent=%s state=%s",
                            fu_intent_name, fu_state_str,
                        )

                    # 设置对话状态
                    if fu_state_str == "waiting_purpose":
                        context.state = DialogState.WAITING_PURPOSE
                        response.state = DialogState.WAITING_PURPOSE
                        response.quick_replies = ["跳过", "去机场打车", "出差餐费", "办公用品采购"]
                    elif fu_state_str == "waiting_confirm":
                        context.state = DialogState.WAITING_CONFIRM
                        response.state = DialogState.WAITING_CONFIRM
                        response.quick_replies = ["确认", "取消"]

                    # 设置待处理发票ID
                    if "pending_invoice_id" in fu:
                        context.pending_invoice_id = fu["pending_invoice_id"]

                    response.need_user_input = True

            except Exception as e:
                logger.exception("Action execution failed: %s", e)
                response.text = f"操作执行失败：{e}"
                response.error = "action_failed"

        return response

    # 全局洞察 → 员工自我洞察的降级映射
    # 原则：有语义一致的自我洞察→降级；无对应意图→礼貌拒绝（None）
    _INSIGHT_DEGRADE_MAP = {
        "insight_total": "self_insight_total",               # ✅ 公司报销总额→本人报销总额
        "insight_by_category": "self_insight_category",     # ✅ 公司分类分布→本人分类分布
        "insight_category_amount": "self_insight_category_amount",  # ✅
        "insight_trend": "self_insight_trend",               # ✅
        "insight_compare": "self_insight_compare",           # ✅
        "insight_invoice_total": "self_insight_invoice_total",  # ✅ 公司发票统计→本人发票统计
        # 无对应自我洞察的意图→礼貌拒绝而非乱降级
        "insight_anomaly": None,          # 员工无权查全公司异常
        "insight_top": None,             # 员工无权查排行榜
        "insight_person": None,          # 员工无权查他人费用
        "insight_project": None,         # 员工无权查项目费用
        "insight_by_dept": None,         # 员工无权查部门统计
        "insight_invoice_filter": "self_insight_invoice_filter",  # ✅ 全公司发票筛选→本人发票筛选
    }

    def _degrade_insight_for_employee(self, intent_name: str) -> str | None:
        """员工被全局洞察拦截后，降级为对应的自我洞察

        例如：员工问"项目投标的报销"被匹配为 insight_project → 降级为 self_insight_total
        这样员工看到的是自己的报销总额，而不是"权限不足"
        """
        return self._INSIGHT_DEGRADE_MAP.get(intent_name)

    async def _try_llm_nlu(
        self,
        text: str,
        context: DialogContext,
    ) -> Optional[NluResult]:
        """尝试 LLM NLU 意图理解（异步，1-3s，有超时保护）"""
        try:
            from .llm_nlu import get_llm_nlu
            nlu = get_llm_nlu()
            result = await nlu.classify(text, context)
            return result
        except Exception as e:
            logger.warning("LLM NLU error: %s", e)
            return None

    def _handle_special_intents(
        self,
        response: DialogResponse,
        context: DialogContext,
        nlu_result: NluResult,
    ) -> DialogResponse:
        """处理不需要后端调用的特殊意图"""

        # 帮助 — 按角色返回差异化帮助
        if response.intent_name == "common_help":
            help_text = self._get_help_text(context.role)
            # 在 WAITING 状态下，保留当前对话流
            if context.state != DialogState.IDLE:
                response.text = help_text + "\n\n💡 您当前正在进行操作，回复「取消」可退出，或继续输入。"
                response.state = context.state
                response.need_user_input = True
            else:
                response.text = help_text
                response.state = DialogState.IDLE

        # 问候
        elif response.intent_name == "common_greeting":
            role_name = {UserRole.EMPLOYEE: "", UserRole.ADMIN: "管理员", UserRole.BOSS: ""}.get(context.role, "")
            response.text = f"你好{role_name}！我是AI报销助手，有什么可以帮您的？"
            response.quick_replies = self._get_quick_replies_for_role(context.role)
            response.state = DialogState.IDLE

        return response

    def _get_help_text(self, role: UserRole) -> str:
        """按角色返回帮助文本"""
        if role == UserRole.EMPLOYEE:
            return (
                "📋 **员工使用帮助**\n\n"
                "**上传凭证：**\n"
                "• 发送发票图片 → 自动识别上传\n"
                "• 输入「无票」→ 无凭证报销\n"
                "• 报销单按周期自动归集，无需手动提交\n\n"
                "**查询操作：**\n"
                "• 输入「查询报销」→ 查看报销进度\n"
                "• 输入「我的发票」→ 查看已上传发票\n\n"
                "**自我洞察：**\n"
                "• 输入「我花了多少」→ 本期报销总额\n"
                "• 输入「我哪类费用最多」→ 费用分类占比\n"
                "• 输入「我还有多少没报的」→ 未提交票据\n\n"
                "**其他：**\n"
                "• 输入「取消」→ 取消当前操作\n"
                "• 输入「转人工」→ 联系客服"
            )
        elif role == UserRole.ADMIN:
            return (
                "📋 **管理员使用帮助**\n\n"
                "**审批管理：**\n"
                "• 输入「待审批」→ 查看待审批列表\n"
                "• 输入「批准报销单XXX」→ 审批通过\n"
                "• 输入「驳回报销单XXX」→ 驳回\n\n"
                "**查询导出：**\n"
                "• 输入「查张三的报销」→ 查询个人\n"
                "• 输入「导出报销明细」→ 导出报表\n\n"
                "**数据洞察：**\n"
                "• 输入「公司花了多少」→ 总额统计\n"
                "• 输入「有没有异常」→ 异常检测\n"
                "• 输入「费用最高的前10人」→ 排名\n\n"
                "也可使用后台Web管理系统进行操作。"
            )
        else:  # BOSS
            return (
                "📋 **使用帮助**\n\n"
                "**数据洞察：**\n"
                "• 输入「本月公司报销总额」→ 总额统计\n"
                "• 输入「哪个部门花得多」→ 部门排名\n"
                "• 输入「费用最高的前10人」→ 人员排名\n"
                "• 输入「最近半年费用趋势」→ 趋势分析\n"
                "• 输入「有没有异常」→ 异常检测\n"
                "• 输入「智慧城市项目花了多少」→ 项目统计\n\n"
                "**其他：**\n"
                "• 输入「取消」→ 取消当前操作"
            )

    def _get_quick_replies_for_role(self, role: UserRole) -> list[str]:
        """按角色返回快捷回复"""
        if role == UserRole.EMPLOYEE:
            return ["上传发票", "查询报销", "我花了多少", "帮助"]
        elif role == UserRole.ADMIN:
            return ["待审批", "公司花了多少", "有没有异常", "帮助"]
        else:
            return ["本月报销总额", "哪个部门花得多", "趋势", "帮助"]

    def reset_user(self, user_id: str) -> None:
        """重置用户对话上下文"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._store.delete(user_id))
        except RuntimeError:
            asyncio.run(self._store.delete(user_id))

    async def reset_user_async(self, user_id: str) -> None:
        """异步重置用户对话上下文"""
        await self._store.delete(user_id)

    async def get_user_state(self, user_id: str) -> Optional[dict]:
        """获取用户当前状态（用于调试）"""
        ctx = await self._store.get(user_id)
        return ctx.to_dict() if ctx else None

    async def get_waiting_users(self, state: DialogState, timeout_seconds: int = 300) -> list[dict]:
        """获取处于指定 WAITING 状态且超过 timeout 的用户列表（场景2：超时主动提醒）

        Args:
            state: 目标状态（如 WAITING_PURPOSE）
            timeout_seconds: 超过多少秒视为超时

        Returns:
            [{"user_id": str, "state": str, "updated_at": float}, ...]
        """
        import time as _time
        now = _time.time()
        result = []

        # Redis 存储模式：SCAN dialog:ctx:* 逐个检查
        if hasattr(self._store, '_redis') and self._store._redis and not self._store._use_fallback:
            try:
                keys = []
                async for key in self._store._redis.scan_iter(match=f"{KEY_PREFIX}*", count=100):
                    keys.append(key)
                for key in keys:
                    try:
                        raw = await self._store._redis.get(key)
                        if not raw:
                            continue
                        data = json.loads(raw)
                        if data.get("state") == state.value:
                            updated_at = data.get("updated_at", 0)
                            if now - updated_at >= timeout_seconds:
                                result.append({
                                    "user_id": data.get("user_id", ""),
                                    "state": data.get("state", ""),
                                    "updated_at": updated_at,
                                })
                    except Exception as e:
                        logger.debug("Error scanning key %s: %s", key, e)
                        continue
            except Exception as e:
                logger.warning("Error scanning waiting users: %s", e)
        else:
            # 内存存储模式
            if hasattr(self._store, '_store'):
                for user_id, data in self._store._store.items():
                    if data.get("state") == state.value:
                        updated_at = data.get("updated_at", 0)
                        if now - updated_at >= timeout_seconds:
                            result.append({
                                "user_id": data.get("user_id", user_id),
                                "state": data.get("state", ""),
                                "updated_at": updated_at,
                            })

        return result


# ============================================================
# 全局单例
# ============================================================
_engine: Optional[DialogEngine] = None


def get_dialog_engine() -> DialogEngine:
    """获取对话引擎单例（使用 Redis 持久化，不可用时优雅降级到内存）"""
    global _engine
    if _engine is None:
        from app.config import settings
        store = RedisContextStore(redis_url=settings.redis_url)
        _engine = DialogEngine(store=store)
        logger.info("Dialog engine initialized with %d intents (store=RedisContextStore)", _count_intents())
    return _engine


def get_dialog_engine_with_store(store: BaseContextStore) -> DialogEngine:
    """获取使用指定存储后端的对话引擎（测试用）"""
    engine = DialogEngine(store=store)
    return engine


def _count_intents() -> int:
    from .intent_registry import get_total_count
    return get_total_count()
