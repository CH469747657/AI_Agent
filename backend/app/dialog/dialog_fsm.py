"""Dialog FSM — 对话状态机 + 多轮槽位填充

负责：
1. 根据 NLU 结果和当前对话状态确定下一步动作
2. 管理槽位填充流程（缺失必填槽位 → 追问）
3. 状态流转（IDLE → WAITING_* → IDLE）
4. 追问超时管理
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import (
    DialogContext, DialogState, DialogResponse,
    NluResult, Intent, Slot, UserRole,
)
from .intent_registry import get_intent

logger = logging.getLogger(__name__)

# 追问超时时间（秒）
SLOT_TIMEOUT = 300  # 5分钟无回复自动取消追问


# ============================================================
# 槽位追问话术
# ============================================================
_PROMPT_TEMPLATES: dict[str, dict[str, str]] = {
    "emp_upload_invoice": {
        "image_file": "请上传发票图片或文件",
    },
    "emp_no_receipt": {
        "amount": "请输入无票报销的金额，例如：120元",
        "description": "请描述这笔费用的用途，例如：去机场打车",
    },
    "emp_modify_field": {
        "field_name": "请问您要修改哪个字段？可选：金额、日期、销售方、税号等",
        "field_value": "{field_name}改为多少？",
    },
    "admin_approve": {
        "reimbursement_id": "请问要批准哪张报销单？可以报编号或报申请人姓名",
    },
    "admin_reject": {
        "reimbursement_id": "请问要驳回哪张报销单？",
    },
    "insight_person": {
        "person": "请问要查询哪位员工的费用情况？",
    },
    "insight_project": {
        "project_name": "请问要查询哪个项目的费用？",
    },
    "emp_fill_invoice_desc": {
        "purpose": "请简要描述这笔费用的用途，例如：去机场打车",
    },
    "emp_batch_describe": {
        "batch_description": "请描述各发票的用途，例如：\"前两张是差旅-交通，第三张是餐费\"",
    },
    "emp_batch_modify": {
        "batch_modifications": "请描述要修改的内容，例如：\"金额改为100，日期改为2026-08-01\"",
    },
}


# ============================================================
# 状态 → 槽位映射（用于在 WAITING 状态下接收用户输入填充槽位）
# ============================================================
_STATE_SLOT_MAP: dict[DialogState, str] = {
    DialogState.WAITING_FILE: "image_file",
    DialogState.WAITING_AMOUNT: "amount",
    DialogState.WAITING_DESC: "description",
    DialogState.WAITING_FIELD: "field_name",
    DialogState.WAITING_VALUE: "field_value",
    DialogState.WAITING_PURPOSE: "purpose",
    DialogState.WAITING_REIMB_ID: "reimbursement_id",
    DialogState.WAITING_PERSON: "person",
    DialogState.WAITING_PROJECT_NAME: "project_name",
    DialogState.WAITING_CATEGORY: "category_selection",
    DialogState.WAITING_PROJECT: "project_id",
    DialogState.WAITING_CONFIRM: "confirm_action",
}


class DialogFSM:
    """对话状态机"""

    def process(
        self,
        nlu_result: NluResult,
        context: DialogContext,
        text: str,
        has_attachment: bool = False,
    ) -> DialogResponse:
        """处理一轮对话

        Args:
            nlu_result: NLU 识别结果
            context: 对话上下文
            text: 原始用户输入
            has_attachment: 是否包含附件

        Returns:
            DialogResponse 对话响应
        """
        context.touch()

        # 1. 取消操作 — 任意状态都可取消（最高优先级）
        if nlu_result.intent_name == "common_cancel":
            context.reset_to_idle()
            return DialogResponse(
                text="已取消当前操作。",
                state=DialogState.IDLE,
                intent_name="common_cancel",
            )

        # 2. 当前处于 WAITING 状态 → 接收用户输入填充槽位
        #    仅 cancel 和 help 可中断 WAITING 状态，其余输入一律视为对追问的回复
        if context.state != DialogState.IDLE:
            if nlu_result.intent_name == "common_help":
                # help 在 WAITING 状态下仅展示帮助提示，不破坏当前对话流
                # 保持上下文状态不变，让 engine 填充帮助文本
                return DialogResponse(
                    text="",
                    state=context.state,
                    intent_name="common_help",
                    need_user_input=True,
                )

            # WAITING_PURPOSE 特殊处理：用户可跳过描述，或发送新附件中断
            if context.state == DialogState.WAITING_PURPOSE:
                skip_keywords = ("跳过", "skip", "不用了", "不用描述", "略过", "不需要")
                if text.strip() in skip_keywords:
                    # 用户选择跳过描述 → 回到 IDLE，保留批量列表
                    context.soft_reset()
                    if context.role == UserRole.EMPLOYEE:
                        msg = "已跳过描述。继续上传可发送更多发票。报销单将按周期自动生成与归集。"
                    else:
                        msg = "已跳过描述。继续上传可发送更多发票，输入「完成」提交报销。"
                    return DialogResponse(
                        text=msg,
                        state=DialogState.IDLE,
                    )
                if has_attachment:
                    # 用户发送新发票 → 中断描述追问，保留批量列表，处理新上传
                    # soft_reset 清除意图和槽位但保留 batch_invoice_ids
                    context.soft_reset()
                    # 不 return，继续往下走到步骤 3+ 处理新意图
                else:
                    return self._handle_waiting_state(context, text)
            else:
                return self._handle_waiting_state(context, text)

        # 3. 未识别意图
        if not nlu_result.intent_name:
            return self._handle_unrecognized(context, text)

        # 4. 获取意图定义
        intent = get_intent(nlu_result.intent_name)
        if not intent:
            return DialogResponse(
                text=f"系统内部错误：意图 {nlu_result.intent_name} 未定义。",
                state=context.state,
                error="intent_not_found",
            )

        # 5. 设置当前意图并填充已提取的槽位
        context.set_intent(intent.name, intent.required_slots, intent.optional_slots)
        for slot_name, slot_value in nlu_result.extracted_slots.items():
            context.fill_slot(slot_name, slot_value)

        # 6. 检查必填槽位是否完整
        missing = context.get_missing_required_slots()
        if missing:
            return self._prompt_for_slots(context, missing, intent)

        # 7. 所有槽位已填充 → 准备执行（实际执行由 dialog_engine 调用后端服务）
        return DialogResponse(
            text=self._build_confirmation(context, intent),
            state=DialogState.IDLE,
            intent_name=intent.name,
            action_taken=False,  # 由 engine 标记
            need_user_input=False,
        )

    def _handle_waiting_state(
        self, context: DialogContext, text: str
    ) -> DialogResponse:
        """处理 WAITING 状态下的用户输入"""
        # WAITING_CONFIRM 特殊处理：用户确认/取消提交
        if context.state == DialogState.WAITING_CONFIRM:
            confirm_keywords = ("确认", "确定", "提交", "是", "好的", "确认提交", "yes", "ok")
            cancel_keywords = ("取消", "不", "否", "返回", "cancel", "no")
            if text.strip() in confirm_keywords:
                # 用户确认提交 → 清除 confirm 状态，由 engine 执行实际提交
                context.state = DialogState.IDLE
                return DialogResponse(
                    text=self._build_confirmation(context, get_intent(context.current_intent or "")),
                    state=DialogState.IDLE,
                    intent_name=context.current_intent,
                )
            elif text.strip() in cancel_keywords:
                context.soft_reset()
                return DialogResponse(
                    text="已取消提交。您可以继续修改，或输入「帮助」查看可用操作。",
                    state=DialogState.IDLE,
                )
            else:
                return DialogResponse(
                    text="请回复「确认」提交报销，或「取消」返回修改。",
                    state=DialogState.WAITING_CONFIRM,
                    intent_name=context.current_intent,
                    need_user_input=True,
                    quick_replies=["确认", "取消"],
                )

        slot_name = _STATE_SLOT_MAP.get(context.state)

        # 意图特化：batch_description/batch_modifications 与 WAITING_PURPOSE/WAITING_FIELD 共享状态，
        # 但需要填充不同的槽位名，否则会填入 purpose/field_name 导致 FSM 陷入追问循环
        if context.current_intent == "emp_batch_describe" and context.state == DialogState.WAITING_PURPOSE:
            slot_name = "batch_description"
        elif context.current_intent == "emp_batch_modify" and context.state == DialogState.WAITING_FIELD:
            slot_name = "batch_modifications"

        if not slot_name:
            # 未知状态，重置
            context.reset_to_idle()
            return DialogResponse(
                text="操作已超时，请重新开始。",
                state=DialogState.IDLE,
            )

        context.fill_slot(slot_name, text)

        # 检查是否还有其他缺失的必填槽位
        missing = context.get_missing_required_slots()
        if missing:
            intent = get_intent(context.current_intent or "")
            return self._prompt_for_slots(context, missing, intent)

        # 全部填完
        intent = get_intent(context.current_intent or "")
        context.state = DialogState.IDLE  # 所有槽位已填充，状态回到 IDLE
        return DialogResponse(
            text=self._build_confirmation(context, intent),
            state=DialogState.IDLE,
            intent_name=context.current_intent,
        )

    def _prompt_for_slots(
        self, context: DialogContext, missing: list[str], intent: Optional[Intent]
    ) -> DialogResponse:
        """生成槽位追问"""
        if not missing:
            return DialogResponse(text="", state=context.state)

        slot_name = missing[0]
        prompt = self._get_prompt(context.current_intent or "", slot_name, context)

        # 根据槽位确定下一个状态
        next_state = self._get_waiting_state(slot_name)
        context.state = next_state

        quick_replies = self._get_quick_replies(context.current_intent or "", slot_name)

        return DialogResponse(
            text=prompt,
            state=next_state,
            intent_name=context.current_intent,
            need_user_input=True,
            quick_replies=quick_replies,
        )

    def _get_prompt(self, intent_name: str, slot_name: str, context: DialogContext) -> str:
        """获取追问话术"""
        templates = _PROMPT_TEMPLATES.get(intent_name, {})
        template = templates.get(slot_name, f"请提供{slot_name}：")

        # 模板替换
        if "{field_name}" in template:
            field_name = context.slots.get("field_name")
            field_value = field_name.value if field_name else "该字段"
            template = template.replace("{field_name}", str(field_value))

        return template

    def _get_waiting_state(self, slot_name: str) -> DialogState:
        """根据槽位名称获取对应的等待状态"""
        state_map = {
            "image_file": DialogState.WAITING_FILE,
            "amount": DialogState.WAITING_AMOUNT,
            "description": DialogState.WAITING_DESC,
            "field_name": DialogState.WAITING_FIELD,
            "field_value": DialogState.WAITING_VALUE,
            "purpose": DialogState.WAITING_PURPOSE,
            "reimbursement_id": DialogState.WAITING_REIMB_ID,
            "person": DialogState.WAITING_PERSON,
            "project_name": DialogState.WAITING_PROJECT_NAME,
            "category_selection": DialogState.WAITING_CATEGORY,
            "project_id": DialogState.WAITING_PROJECT,
            "batch_description": DialogState.WAITING_PURPOSE,
            "batch_modifications": DialogState.WAITING_FIELD,
            "confirm_action": DialogState.WAITING_CONFIRM,
        }
        return state_map.get(slot_name, DialogState.IDLE)

    def _get_quick_replies(self, intent_name: str, slot_name: str) -> list[str]:
        """获取快捷回复选项"""
        if intent_name == "emp_modify_field" and slot_name == "field_name":
            return ["金额", "日期", "销售方", "税号"]
        if intent_name == "emp_fill_invoice_desc" and slot_name == "purpose":
            return ["跳过", "去机场打车", "出差餐费", "办公用品采购"]
        if intent_name == "emp_batch_describe" and slot_name == "batch_description":
            return ["前两张是差旅-交通，第三张是餐费", "全部是办公用品"]
        if intent_name == "emp_batch_modify" and slot_name == "batch_modifications":
            return ["金额改为100", "日期改为今天"]
        if slot_name == "confirm_action":
            return ["确认", "取消"]
        return []

    def _build_confirmation(self, context: DialogContext, intent: Optional[Intent]) -> str:
        """构建操作确认提示"""
        if not intent:
            return "操作已就绪。"

        slot_summary = "，".join(
            f"{name}={slot.value}" for name, slot in context.slots.items() if slot.filled
        )
        return f"已识别意图：{intent.description}" + (f"（{slot_summary}）" if slot_summary else "")

    def _handle_unrecognized(self, context: DialogContext, text: str) -> DialogResponse:
        """处理未识别的意图 — 根据用户文本猜测可能意图做友好引导"""
        # 简单关键词猜测，提供更精准的引导
        guesses = []
        text_lower = text.lower()
        if any(kw in text_lower for kw in ("发票", "票", "上传", "传")):
            guesses.append("• 发送发票图片即可上传报销")
        if any(kw in text_lower for kw in ("查", "进度", "状态", "到哪", "批了")):
            guesses.append("• 输入「查询报销」查看进度")
        if any(kw in text_lower for kw in ("花了", "费用", "多少", "钱")):
            guesses.append("• 输入「我花了多少」查看费用")
        if any(kw in text_lower for kw in ("你好", "在吗", "嗨")):
            guesses.append("• 输入「你好」跟我打招呼")
        if not guesses:
            guesses = [
                "• 发送发票图片上传报销",
                "• 输入「查询报销」查看进度",
                "• 输入「我花了多少」查看费用",
            ]

        quick_replies = ["帮助", "上传发票", "查询报销", "我花了多少"]

        if context.state != DialogState.IDLE:
            return DialogResponse(
                text=f"抱歉，我没有理解您的意思。当前正在处理「{context.current_intent}」，"
                     f"请继续输入或回复「取消」退出。",
                state=context.state,
                need_user_input=True,
                quick_replies=quick_replies,
            )

        return DialogResponse(
            text=f"抱歉，我没有理解「{text}」的意思。您可以尝试：\n" + "\n".join(guesses),
            state=DialogState.IDLE,
            need_user_input=True,
            quick_replies=quick_replies,
        )
