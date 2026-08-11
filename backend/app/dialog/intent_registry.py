"""意图注册表 — 53个意图定义

基于 .temp/intent-taxonomy.md 意图体系清单：
- 通用意图 6个 (common_*)
- 员工意图 25个 (emp_* 8 + emp_query 3 + self_insight 9 + batch 2 + delete 1 + fill_desc 1 + query_my_reimb 1)
- 管理员意图 19个 (admin_approve 3 + admin_query 8 + insight 6)
- 老板意图 3个 (boss_insight 3)
- 全局洞察 6个 (admin/boss共享)
- 去重合计 53个独立意图

注意：E-22=emp_batch_describe, E-23=emp_batch_modify, E-24=emp_query_my_reimbursement
"""

from __future__ import annotations

from .models import Intent, NluLevel, UserRole

# ============================================================
# 通用意图（全角色可用）— 6个
# ============================================================
COMMON_INTENTS: list[Intent] = [
    Intent(
        code="C-01", name="common_help",
        description="根据当前角色返回对应的帮助信息",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="C-02", name="common_cancel",
        description="取消当前操作，状态回退到IDLE",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="C-03", name="common_switch_topic",
        description="中断当前对话流，清空槽位，进入IDLE",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="C-04", name="common_human_handoff",
        description="转接人工客服，携带当前对话上下文",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=["issue_desc"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="C-05", name="common_greeting",
        description="问候响应，附带快捷操作提示",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="C-06", name="common_feedback",
        description="收集用户反馈，记录到反馈表",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=["content"], optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
]

# ============================================================
# 员工意图 — 提单类 8个
# ============================================================
EMPLOYEE_INTENTS: list[Intent] = [
    Intent(
        code="E-01", name="emp_upload_invoice",
        description="上传发票图片或文件",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["image_file"],
        optional_slots=["receipt_type"],
        nlu_level=NluLevel.L1_KEYWORD,
        prompt_template="请上传发票图片或文件",
    ),
    Intent(
        code="E-02", name="emp_batch_upload",
        description="批量连续上传发票",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["image_file"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-03", name="emp_no_receipt",
        description="无票报销",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["amount", "description"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        prompt_template="请输入无票报销的金额，例如：120元",
    ),
    Intent(
        code="E-04", name="emp_fill_purpose",
        description="对话中描述报销用途",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["purpose"],
        optional_slots=["project", "cost_center"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-05", name="emp_modify_field",
        description="修改发票字段",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["field_name", "field_value"],
        optional_slots=[],  # invoice_id 为继承槽位
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问您要修改哪个字段？可选：金额、日期、销售方、税号等",
    ),
    Intent(
        code="E-06", name="emp_confirm_category",
        description="确认费用分类",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["category_selection"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-07", name="emp_confirm_project",
        description="确认项目归属",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["project_id"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-08", name="emp_submit_reimbursement",
        description="提交报销单",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],  # invoice_list, purpose 为继承槽位
        optional_slots=["approver"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-20", name="emp_fill_invoice_desc",
        description="为刚上传的发票补充用途描述/备注",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["purpose"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        prompt_template="请简要描述这笔费用的用途，例如：去机场打车",
    ),
    Intent(
        code="E-22", name="emp_batch_describe",
        description="批量用途描述——用户一条说明为多张发票分配用途，如\"前两张是差旅-交通，第三张是差旅-餐饮\"\"1和3是打车，2是餐费\"，LLM自动拆解映射",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["batch_description"],
        optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请描述各发票的用途，例如：\"前两张是差旅-交通，第三张是餐费\"",
    ),
    Intent(
        code="E-23", name="emp_batch_modify",
        description="批量修改发票字段——用户可一次描述多个字段的修改，如\"金额改为100，日期改为2026-08-01\"\"把销售方改成XX公司，税号改成123\"",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["batch_modifications"],
        optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请描述要修改的内容，例如：\"金额改为100，日期改为2026-08-01\"",
    ),
    Intent(
        code="E-21", name="emp_delete_invoice",
        description="删除/撤销已上传但未提交的发票（如\"删除上一张\"\"撤销上传\"\"删除第2张\"\"删除那张机票\"）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["delete_target"],  # 值: "last"/"index:N"/"type:关键词"
        nlu_level=NluLevel.L1_KEYWORD,
    ),
]

# ============================================================
# 员工意图 — 查询类 2个
# ============================================================
EMPLOYEE_QUERY_INTENTS: list[Intent] = [
    Intent(
        code="E-09", name="emp_query_status",
        description="查询报销进度",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["reimbursement_id"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-10", name="emp_query_invoices",
        description="查询已上传发票列表",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["status_filter"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-24", name="emp_query_my_reimbursement",
        description="查询本人的报销单列表（含报销周期、费用/补贴明细、封账状态）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
]

# ============================================================
# 员工意图 — 政策咨询 1个 + 自我洞察 5个
# ============================================================
EMPLOYEE_INSIGHT_INTENTS: list[Intent] = [
    Intent(
        code="E-11", name="emp_explain_policy",
        description="查询差旅标准/报销政策",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["expense_type", "city_level"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="E-12", name="self_insight_total",
        description="查询本人报销总额",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-13", name="self_insight_category",
        description="查询本人费用分类占比",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["fee_category", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-14", name="self_insight_trend",
        description="查询本人费用趋势",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="E-15", name="self_insight_pending",
        description="查询本人未提交票据",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-16", name="self_insight_compare",
        description="本人期间费用对比",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-17", name="self_insight_category_amount",
        description="查询本人某分类费用金额（如\"快递费花了多少\"）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["fee_category_keyword"],
        optional_slots=["fee_category_aliases", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-18", name="self_insight_invoice_total",
        description="查询本人发票统计（张数+金额+按状态分组）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="E-19", name="self_insight_invoice_filter",
        description="按条件筛选本人发票（重复/验真失败/高风险/待审核/收据等）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["filter_type", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
]

# ============================================================
# 管理员意图 — 审批类 3个
# ============================================================
ADMIN_APPROVE_INTENTS: list[Intent] = [
    Intent(
        code="A-01", name="admin_approve",
        description="批准报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["person", "reimbursement_id"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要批准哪张报销单？可以报编号或报申请人姓名",
    ),
    Intent(
        code="A-02", name="admin_reject",
        description="驳回报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=["reimbursement_id"],
        optional_slots=["reason"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要驳回哪张报销单？",
    ),
    Intent(
        code="A-03", name="admin_batch_approve",
        description="批量审批报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=["filter"],
        optional_slots=[],
        nlu_level=NluLevel.L3_LLM,
    ),
]

# ============================================================
# 管理员意图 — 查询类 4个 + 导出 1个
# ============================================================
ADMIN_QUERY_INTENTS: list[Intent] = [
    Intent(
        code="A-04", name="admin_query_team",
        description="按部门维度查询报销",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["department", "period"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="A-05", name="admin_query_pending",
        description="查询待审批报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-06", name="admin_query_person",
        description="查询指定员工报销",
        role_scope=[UserRole.ADMIN],
        required_slots=["person"],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要查询哪位员工的费用情况？",
    ),
    Intent(
        code="A-07", name="admin_query_detail",
        description="查看报销单详情",
        role_scope=[UserRole.ADMIN],
        required_slots=["reimbursement_id"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-08", name="admin_export",
        description="导出报销明细",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["department", "period", "format"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="A-08b", name="admin_query_cycle_summary",
        description="查询某报销周期汇总（报销单数、费用/补贴分拆、封账状态、各申请人明细）",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="A-09b", name="admin_mark_reimbursed",
        description="标记已审核报销单为已打款（REVIEWED → REIMBURSED），如\"打款""已打款""标记报销""确认打款\"",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["person", "reimbursement_id"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要标记哪张报销单为已打款？可以报编号或报申请人姓名",
    ),
    Intent(
        code="A-10", name="admin_aggregate_invoices",
        description='批量归集游离发票到报销单，如"生成报销单""归集发票""生成所有人的报销单""汇总发票到报销单"',
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["user_id"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
]

# ============================================================
# 管理员/老板共享 — 全局洞察 6个
# ============================================================
INSIGHT_INTENTS: list[Intent] = [
    Intent(
        code="A-09/B-01", name="insight_total",
        description="公司报销总额",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period", "department"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-10/B-03", name="insight_by_category",
        description="费用类别分布",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period", "department"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-10b/B-03b", name="insight_category_amount",
        description="查询某分类费用金额（如\"快递费花了多少\"）",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=["fee_category_keyword"],
        optional_slots=["fee_category_aliases", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-11/B-04", name="insight_trend",
        description="费用趋势",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
    ),
    Intent(
        code="A-12/B-05", name="insight_anomaly",
        description="异常/超标/重复报销检测",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period", "anomaly_type"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-13/B-08", name="insight_top",
        description="费用排名",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["limit", "period", "order", "data_scope"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-14/B-09", name="insight_project",
        description="项目费用统计",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=["project_name"],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要查询哪个项目的费用？",
    ),
    Intent(
        code="A-15/B-10", name="insight_invoice_total",
        description="全公司发票统计（张数+金额+按状态分组），支持按员工筛选",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period", "person"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="A-16/B-11", name="insight_invoice_filter",
        description="按条件筛选发票列表（重复/验真失败/高风险/待审核/收据等）",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["filter_type", "period", "person"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
]

# 老板独有洞察
BOSS_INSIGHT_INTENTS: list[Intent] = [
    Intent(
        code="B-02", name="insight_by_dept",
        description="部门费用排名",
        role_scope=[UserRole.BOSS, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
    Intent(
        code="B-06", name="insight_person",
        description="指定员工费用查询",
        role_scope=[UserRole.BOSS, UserRole.ADMIN],
        required_slots=["person"],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要查询哪位员工的费用情况？",
    ),
    Intent(
        code="B-07", name="insight_compare",
        description="期间费用对比",
        role_scope=[UserRole.BOSS, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
    ),
]

# ============================================================
# 全部意图汇总
# ============================================================
ALL_INTENTS: list[Intent] = (
    COMMON_INTENTS
    + EMPLOYEE_INTENTS
    + EMPLOYEE_QUERY_INTENTS
    + EMPLOYEE_INSIGHT_INTENTS
    + ADMIN_APPROVE_INTENTS
    + ADMIN_QUERY_INTENTS
    + INSIGHT_INTENTS
    + BOSS_INSIGHT_INTENTS
)

# 意图名称 → Intent 映射表
INTENT_MAP: dict[str, Intent] = {intent.name: intent for intent in ALL_INTENTS}


def get_intent(name: str) -> Intent | None:
    """按名称获取意图定义"""
    return INTENT_MAP.get(name)


def get_intents_for_role(role: UserRole) -> list[Intent]:
    """获取角色可用的全部意图"""
    return [intent for intent in ALL_INTENTS if role in intent.role_scope]


def get_total_count() -> int:
    """意图去重总数"""
    return len(ALL_INTENTS)
