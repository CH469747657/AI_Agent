"""对话引擎数据模型

定义意图、槽位、对话上下文、对话响应等核心数据结构。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ============================================================
# 对话上下文增强 — 历史与槽位继承配置
# ============================================================

# 历史记录最大轮数（超出后自动淘汰最早的，防止 Redis 存储膨胀）
MAX_HISTORY = 10

# 可继承槽位白名单 — 跨轮稳定、handler 友好的查询参数
# 当前轮未提供时，可从上一轮历史继承
INHERITABLE_SLOT_NAMES = frozenset({
    "person",                # 人员姓名/工号
    "period",                # 时间段
    "project_name",          # 项目名称
    "department",            # 部门
    "reimbursement_id",      # 报销单编号
    "invoice_id",            # 发票编号
    "filter_type",           # 发票筛选类型
    "anomaly_type",          # 异常类型
    "fee_category_keyword",  # 费用分类关键词
    "fee_category_aliases",  # 费用分类别名
    "limit",                 # 排名数量
    "order",                 # 排序方向
    "data_scope",            # 数据范围
})

# 可覆盖槽位 — 当前轮明确指定时覆盖继承值
# 与 INHERITABLE_SLOT_NAMES 一致：所有可继承槽位也均可被当前轮覆盖
OVERRIDABLE_SLOT_NAMES = frozenset({
    "person", "invoice_id",
    "fee_category_keyword", "fee_category_aliases",
    "filter_type", "anomaly_type",
    "period", "limit", "order", "data_scope",
    "project_name", "department", "reimbursement_id",
})


class UserRole(str, Enum):
    """用户角色 — 三角色权限体系"""
    EMPLOYEE = "employee"
    ADMIN = "admin"
    BOSS = "boss"


class NluLevel(int, Enum):
    """NLU路由层级"""
    L1_KEYWORD = 1   # 正则/关键词精确匹配，<1ms，零成本
    L2_SEMANTIC = 2  # 轻量NLU/BERT语义分类，~50ms
    L3_LLM = 3       # LLM大模型意图理解，1-3s，API费


class DialogState(str, Enum):
    """对话状态机状态"""
    IDLE = "idle"
    # 员工提单状态
    WAITING_FILE = "waiting_file"          # 等待上传发票
    WAITING_AMOUNT = "waiting_amount"      # 等待无票报销金额
    WAITING_DESC = "waiting_desc"          # 等待无票报销描述
    WAITING_FIELD = "waiting_field"        # 等待要修改的字段名
    WAITING_VALUE = "waiting_value"        # 等待字段新值
    WAITING_CATEGORY = "waiting_category"  # 等待分类选择
    WAITING_PROJECT = "waiting_project"    # 等待项目选择
    WAITING_PURPOSE = "waiting_purpose"    # 等待报销用途
    WAITING_CONFIRM = "waiting_confirm"    # 等待提交前确认（场景3：Markdown表格汇总后确认）
    # 管理员状态
    WAITING_REIMB_ID = "waiting_reimb_id"  # 等待报销单编号
    # 洞察查询状态
    WAITING_PERSON = "waiting_person"      # 等待人员姓名
    WAITING_PROJECT_NAME = "waiting_project_name"  # 等待项目名称


@dataclass
class Slot:
    """槽位定义"""
    name: str
    required: bool = True
    value: Any = None
    filled: bool = False

    def fill(self, value: Any) -> None:
        self.value = value
        self.filled = True

    def clear(self) -> None:
        self.value = None
        self.filled = False


@dataclass
class Intent:
    """意图定义"""
    code: str                          # 意图编号，如 "E-01"
    name: str                          # 意图名称，如 "emp_upload_invoice"
    description: str                   # 描述
    role_scope: list[UserRole]         # 允许的角色
    required_slots: list[str]          # 必填槽位名称
    optional_slots: list[str]          # 可选槽位名称
    nlu_level: NluLevel                # 最低NLU层级
    prompt_template: str = ""          # 追问话术模板
    # Step 2.1.1：典型用户表述，3-5 条/意图，用于 RAG embedding 检索
    # 设计：覆盖口语化、省略、同义词等多种表述，提升 Top-K 检索召回率
    typical_utterances: list[str] = field(default_factory=list)


@dataclass
class NluResult:
    """NLU识别结果"""
    intent_name: str
    confidence: float
    level: NluLevel
    raw_text: str
    extracted_slots: dict[str, Any] = field(default_factory=dict)
    # L2/L3 可能返回多个候选
    candidates: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class DialogContext:
    """对话上下文 — 每用户独立维护"""
    user_id: str
    role: UserRole = UserRole.EMPLOYEE
    state: DialogState = DialogState.IDLE
    current_intent: Optional[str] = None
    slots: dict[str, Slot] = field(default_factory=dict)
    # 关联数据
    batch_invoice_ids: list[int] = field(default_factory=list)
    pending_invoice_id: Optional[int] = None
    # 前端传入的费用用途（仅当次请求有效，处理后清除）
    user_description: Optional[str] = None
    # 批量描述映射 — 用户分次说明时累积，key 为 0-based 索引字符串，value 为描述
    # 例: {"0": "餐饮费", "1": "打车费"} 表示第1张=餐饮费，第2张=打车费
    batch_desc_map: dict[str, str] = field(default_factory=dict)
    # 当前轮附件数据（Agent 路径用，仅 _handle_upload_invoice 读取 base64/file_type）
    attachment_data: Optional[dict] = None
    # 当前轮原始文本（供 Insight Engine 解析时间段/实体名）
    current_text: str = ""
    # 对话历史 — 最近 N 轮的查询/操作记录，用于跨轮槽位继承与指代消解
    history: list[dict] = field(default_factory=list)
    # 元信息
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    turn_count: int = 0

    def touch(self) -> None:
        self.updated_at = time.time()
        self.turn_count += 1

    def set_intent(self, intent_name: str, required_slots: list[str], optional_slots: list[str]) -> None:
        """设置当前意图并初始化槽位"""
        self.current_intent = intent_name
        self.slots.clear()
        for s in required_slots:
            self.slots[s] = Slot(name=s, required=True)
        for s in optional_slots:
            self.slots[s] = Slot(name=s, required=False)

    def fill_slot(self, name: str, value: Any) -> None:
        if name in self.slots:
            self.slots[name].fill(value)
        else:
            self.slots[name] = Slot(name=name, required=False, value=value, filled=True)

    def get_missing_required_slots(self) -> list[str]:
        return [s.name for s in self.slots.values() if s.required and not s.filled]

    def all_required_slots_filled(self) -> bool:
        return len(self.get_missing_required_slots()) == 0

    def reset_to_idle(self) -> None:
        """重置到空闲状态"""
        self.state = DialogState.IDLE
        self.current_intent = None
        self.slots.clear()
        self.batch_invoice_ids = []
        self.pending_invoice_id = None

    def soft_reset(self) -> None:
        """软重置 — 仅清除意图和槽位，保留批量发票列表和待处理发票ID

        用于上传新发票时中断 WAITING_PURPOSE 状态：
        上一张发票已保存，仅跳过描述追问，不影响批量流程。
        """
        self.state = DialogState.IDLE
        self.current_intent = None
        self.slots.clear()

    # ============================================================
    # 对话历史管理 — 跨轮上下文继承
    # ============================================================

    def add_history(
        self,
        intent: str,
        slots: dict,
        text: str,
        summary: str = "",
        extra_referents: Optional[dict] = None,
    ) -> None:
        """记录一轮对话到历史

        自动从 slots 提取可继承实体到 referents，供后续跨轮继承使用。

        Args:
            intent: 本轮最终意图
            slots: 本轮填充的槽位（dict[slot_name, value]，可为 Slot 对象或裸值）
            text: 本轮用户输入
            summary: 可选摘要，未提供则自动生成
            extra_referents: 额外需注入 referents 的实体（如 action 结果中的 invoice_id）
        """
        # 从 slots 提取 referents（兼容 Slot 对象和裸值）
        referents: dict[str, Any] = {}
        for k, v in slots.items():
            if k in INHERITABLE_SLOT_NAMES:
                value = v.value if hasattr(v, "value") else v
                if value is not None:
                    referents[k] = value
        if extra_referents:
            for k, v in extra_referents.items():
                if k in INHERITABLE_SLOT_NAMES and v is not None:
                    referents[k] = v

        entry = {
            "turn": self.turn_count,
            "user_text": (text or "")[:200],
            "intent": intent,
            "slots": {k: (v.value if hasattr(v, "value") else v)
                      for k, v in slots.items()} if slots else {},
            "referents": referents,
            "summary": summary or self._auto_summary(intent, text),
            "ts": time.time(),
            "role": self.role.value,
        }
        self.history.append(entry)
        # 限制最近 N 轮
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]

    def last_history(self) -> Optional[dict]:
        """获取最近一轮历史记录"""
        return self.history[-1] if self.history else None

    def clear_history(self) -> None:
        """清空对话历史"""
        self.history.clear()

    def get_history_summary(
        self,
        max_turns: int = 3,
        max_tokens: int = 500,
    ) -> str:
        """Step 2.2.1/2.2.2：生成紧凑对话历史摘要，供 LLM NLU 注入

        模板：
            [对话历史（最近N轮）]
            T-k: intent=xxx, slots={key:val, ...}
            ...
            [当前状态] state=IDLE
            [当前意图] current_intent=xxx（如有）

        设计要点：
        - 只取最近 max_turns 轮，避免 token 爆炸
        - slots 只输出非空键值，过滤 None / 空串
        - 粗略 token 估算：按字符数 / 2（中文约 2 字符/token）
        - 无历史时返回空串，由调用方决定是否注入

        Args:
            max_turns: 最多包含的轮次数
            max_tokens: 摘要最大 token 数（粗略估算）

        Returns:
            历史摘要字符串；无历史时返回空串
        """
        if not self.history:
            return ""

        # 取最近 max_turns 轮
        recent = self.history[-max_turns:]
        total_turns = len(self.history)

        lines: list[str] = [f"[对话历史（最近{len(recent)}轮，共{total_turns}轮）]"]

        # 标注轮次：最早的轮次用 T-(N-1)，最近用 T-1
        n = len(recent)
        for i, entry in enumerate(recent):
            t_label = f"T-{n - i}" if (n - i) > 0 else "T"
            intent = entry.get("intent", "unknown")
            slots = entry.get("slots", {}) or {}
            referents = entry.get("referents", {}) or {}

            # 合并 slots + referents，过滤空值
            merged: dict = {}
            for k, v in {**slots, **referents}.items():
                if v is None or v == "" or v == []:
                    continue
                # 截断长值（避免单槽位占太多 token）
                v_str = str(v)
                if len(v_str) > 30:
                    v_str = v_str[:30] + "..."
                merged[k] = v_str

            slots_str = ", ".join(f"{k}:{v}" for k, v in merged.items()) if merged else "无"
            user_text = (entry.get("user_text", "") or "")[:40]
            lines.append(f"{t_label}: intent={intent}, slots={{{slots_str}}}, text=\"{user_text}\"")

        # 当前状态
        state_str = self.state.value if hasattr(self.state, "value") else str(self.state)
        lines.append(f"[当前状态] state={state_str}")
        if self.current_intent:
            lines.append(f"[当前意图] current_intent={self.current_intent}")

        summary = "\n".join(lines)

        # 粗略 token 估算（中文约 2 字符/token），超长则截断
        # 保留开头与结尾的关键信息
        max_chars = max_tokens * 2
        if len(summary) > max_chars:
            # 截断中间轮次，保留首尾
            header = lines[0]
            footer = lines[-2:]  # state + current_intent
            middle = lines[1:-2]
            # 保留最早的 1 轮 + 最新的 1 轮
            if len(middle) > 2:
                kept_middle = [middle[0], f"...（省略{len(middle) - 2}轮）...", middle[-1]]
            else:
                kept_middle = middle
            summary = "\n".join([header] + kept_middle + footer)
            if len(summary) > max_chars:
                summary = summary[:max_chars] + "..."

        return summary

    @staticmethod
    def _auto_summary(intent: str, text: str) -> str:
        """自动生成历史摘要（避免调用 LLM，简单截断用户输入）"""
        if not text:
            return intent
        return text.strip()[:60]

    def to_dict(self) -> dict:
        """序列化用于持久化"""
        return {
            "user_id": self.user_id,
            "role": self.role.value,
            "state": self.state.value,
            "current_intent": self.current_intent,
            "slots": {k: {"value": v.value, "filled": v.filled, "required": v.required}
                      for k, v in self.slots.items()},
            "batch_invoice_ids": self.batch_invoice_ids,
            "pending_invoice_id": self.pending_invoice_id,
            "user_description": self.user_description,
            "current_text": self.current_text,
            "batch_desc_map": self.batch_desc_map,
            "history": self.history,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DialogContext:
        """反序列化"""
        ctx = cls(user_id=data["user_id"])
        ctx.role = UserRole(data.get("role", "employee"))
        ctx.state = DialogState(data.get("state", "idle"))
        ctx.current_intent = data.get("current_intent")
        ctx.turn_count = data.get("turn_count", 0)
        ctx.updated_at = data.get("updated_at", time.time())
        ctx.batch_invoice_ids = data.get("batch_invoice_ids", [])
        ctx.pending_invoice_id = data.get("pending_invoice_id")
        ctx.user_description = data.get("user_description")
        ctx.current_text = data.get("current_text", "")
        ctx.batch_desc_map = data.get("batch_desc_map", {}) or {}
        ctx.history = data.get("history", [])
        for k, v in data.get("slots", {}).items():
            ctx.slots[k] = Slot(
                name=k, required=v.get("required", False),
                value=v.get("value"), filled=v.get("filled", False),
            )
        return ctx


@dataclass
class DialogResponse:
    """对话引擎响应"""
    text: str                                    # 回复文本
    state: DialogState = DialogState.IDLE        # 响应后对话状态
    intent_name: Optional[str] = None            # 触发的意图
    action_taken: bool = False                   # 是否执行了实际操作
    action_result: Optional[dict] = None         # 操作执行结果
    need_user_input: bool = False                # 是否等待用户输入
    quick_replies: list[str] = field(default_factory=list)  # 快捷回复选项
    error: Optional[str] = None                  # 错误信息
