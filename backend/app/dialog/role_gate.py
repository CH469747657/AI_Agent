"""Role Gate — 三角色权限网关

基于意图体系清单第七节权限矩阵，实现：
1. 意图级权限校验（是否允许角色触发该意图）
2. 数据范围隔离（员工仅本人/管理员全员/老板只读全员）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .models import UserRole, DialogContext
from .intent_registry import get_intent

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# 员工端受限对话 — 意图黑名单
# 报销单的生成与汇总由系统后台按报销周期自动完成，员工不可手动触发；
# 发票核心字段修改不在员工操作白名单（上传/补充说明/查询）内。
# 管理员不受此限制（可代为提交/修改）。
# ------------------------------------------------------------
EMPLOYEE_BLOCKED_INTENTS: dict[str, str] = {
    "emp_submit_reimbursement": "报销单由系统按报销周期自动生成与归集，您无需手动提交。",
    "emp_modify_field": "员工端暂不支持修改发票字段，如需修正请联系管理员。",
}


@dataclass
class PermissionResult:
    """权限校验结果"""
    allowed: bool
    reason: str = ""
    data_scope: str = ""  # "self" | "all" | "department" | "read_only_all"


class RoleGate:
    """角色权限网关"""

    # 意图前缀 → 角色权限映射
    _PERMISSION_MATRIX: dict[str, dict[UserRole, bool]] = {
        "common_":        {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: True},
        "emp_upload_":    {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: False},
        "emp_no_receipt": {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: False},
        "emp_fill_":      {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: False},
        "emp_modify_":    {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: False},
        "emp_confirm_":   {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: False},
        "emp_submit_":    {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: False},
        "emp_query_":     {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: True},
        "emp_explain_":   {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: True},
        "self_insight_":  {UserRole.EMPLOYEE: True,  UserRole.ADMIN: True,  UserRole.BOSS: False},
        "admin_":         {UserRole.EMPLOYEE: False, UserRole.ADMIN: True,  UserRole.BOSS: False},
        "insight_":       {UserRole.EMPLOYEE: False, UserRole.ADMIN: True,  UserRole.BOSS: True},
    }

    # 数据范围映射
    _DATA_SCOPE: dict[str, dict[UserRole, str]] = {
        "emp_upload_":    {UserRole.EMPLOYEE: "self",   UserRole.ADMIN: "all",    UserRole.BOSS: ""},
        "emp_no_receipt": {UserRole.EMPLOYEE: "self",   UserRole.ADMIN: "all",    UserRole.BOSS: ""},
        "emp_modify_":    {UserRole.EMPLOYEE: "self",   UserRole.ADMIN: "all",    UserRole.BOSS: ""},
        "emp_submit_":    {UserRole.EMPLOYEE: "self",   UserRole.ADMIN: "all",    UserRole.BOSS: ""},
        "emp_query_":     {UserRole.EMPLOYEE: "self",   UserRole.ADMIN: "all",    UserRole.BOSS: "read_only_all"},
        "self_insight_":  {UserRole.EMPLOYEE: "self",   UserRole.ADMIN: "self",   UserRole.BOSS: ""},
        "admin_":         {UserRole.EMPLOYEE: "",       UserRole.ADMIN: "all",    UserRole.BOSS: ""},
        "insight_":       {UserRole.EMPLOYEE: "",       UserRole.ADMIN: "all",    UserRole.BOSS: "read_only_all"},
    }

    def check(self, intent_name: str, role: UserRole) -> PermissionResult:
        """检查角色是否有权触发该意图

        Args:
            intent_name: 意图名称
            role: 用户角色

        Returns:
            PermissionResult 含 allowed/reason/data_scope
        """
        # 员工端受限对话：意图黑名单（禁止手动提交报销单、修改发票字段等）
        if role == UserRole.EMPLOYEE and intent_name in EMPLOYEE_BLOCKED_INTENTS:
            return PermissionResult(
                allowed=False,
                reason=EMPLOYEE_BLOCKED_INTENTS[intent_name],
            )

        intent = get_intent(intent_name)
        if not intent:
            return PermissionResult(
                allowed=False,
                reason=f"未知意图: {intent_name}",
            )

        # 精确匹配角色范围
        if role in intent.role_scope:
            data_scope = self._get_data_scope(intent_name, role)
            return PermissionResult(
                allowed=True,
                data_scope=data_scope,
            )

        # 前缀匹配权限矩阵
        for prefix, role_perms in self._PERMISSION_MATRIX.items():
            if intent_name.startswith(prefix):
                if role in role_perms and role_perms[role]:
                    data_scope = self._get_data_scope(intent_name, role)
                    return PermissionResult(allowed=True, data_scope=data_scope)
                else:
                    role_name = {UserRole.EMPLOYEE: "员工", UserRole.ADMIN: "管理员",
                                 UserRole.BOSS: "老板"}.get(role, str(role))
                    return PermissionResult(
                        allowed=False,
                        reason=f"{role_name}无权执行此操作",
                    )

        return PermissionResult(
            allowed=False,
            reason=f"权限未定义: 意图={intent_name}, 角色={role}",
        )

    def _get_data_scope(self, intent_name: str, role: UserRole) -> str:
        """获取该意图的数据范围"""
        for prefix, scope_map in self._DATA_SCOPE.items():
            if intent_name.startswith(prefix):
                return scope_map.get(role, "")

        # 通用意图无数据范围限制
        if intent_name.startswith("common_"):
            return ""

        return ""

    def get_self_insight_guard(self, context: DialogContext) -> dict:
        """SelfInsightGuard — 为 self_insight_* 意图自动注入本人数据过滤

        确保员工只能看到自己的数据。
        """
        if context.current_intent and context.current_intent.startswith("self_insight_"):
            return {"applicant_id": context.user_id, "enforced": True}
        return {"enforced": False}

    def is_readonly(self, intent_name: str, role: UserRole) -> bool:
        """是否只读操作（老板的洞察查询为只读）"""
        if role == UserRole.BOSS and intent_name.startswith("insight_"):
            return True
        if role == UserRole.BOSS and intent_name.startswith("emp_query_"):
            return True
        return False
