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
        typical_utterances=[
            "帮助", "怎么用", "能做什么", "有什么功能", "使用说明",
        ],
    ),
    Intent(
        code="C-02", name="common_cancel",
        description="取消当前操作，状态回退到IDLE",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "取消", "算了", "不做了", "不要了", "放弃",
        ],
    ),
    Intent(
        code="C-03", name="common_switch_topic",
        description="中断当前对话流，清空槽位，进入IDLE",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "换个话题", "不聊这个了", "说点别的", "我想问其他的",
        ],
    ),
    Intent(
        code="C-04", name="common_human_handoff",
        description="转接人工客服，携带当前对话上下文",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=["issue_desc"],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "转人工", "找客服", "人工服务", "联系人工", "转接客服",
        ],
    ),
    Intent(
        code="C-05", name="common_greeting",
        description="问候响应，附带快捷操作提示",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "你好", "在吗", "hi", "hello", "嗨",
        ],
    ),
    Intent(
        code="C-06", name="common_feedback",
        description="收集用户反馈，记录到反馈表",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=["content"], optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "我要反馈", "有个建议", "反馈问题", "提个意见",
        ],
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
        typical_utterances=[
            "上传发票", "上传", "传一张发票", "上传这张票", "传个发票图片",
        ],
    ),
    Intent(
        code="E-02", name="emp_batch_upload",
        description="批量连续上传发票",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["image_file"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "还有一张", "继续上传", "再加一张", "还有发票要传", "再传一张",
        ],
    ),
    Intent(
        code="E-03", name="emp_no_receipt",
        description="无票报销",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["amount", "description"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        prompt_template="请输入无票报销的金额，例如：120元",
        typical_utterances=[
            "无票报销", "没有发票", "无凭证报销", "发票丢了", "没带发票",
        ],
    ),
    Intent(
        code="E-04", name="emp_fill_purpose",
        description="对话中描述报销用途",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["purpose"],
        optional_slots=["project", "cost_center"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "用途是出差", "用于项目", "这笔是差旅", "报销事由是", "费用用途",
        ],
    ),
    Intent(
        code="E-05", name="emp_modify_field",
        description="修改发票字段",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["field_name", "field_value"],
        optional_slots=["invoice_index"],  # "第N张"定位，未指定则用 pending_invoice_id
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问您要修改哪个字段？可选：金额、日期、销售方、税号、用途等",
        typical_utterances=[
            "修改金额", "改一下日期", "销售方改一下", "把金额改成", "修改发票字段",
            "用途改成投标费", "把这张的用途改成", "第一张发票的金额改成", "修改第二张的税号",
        ],
    ),
    Intent(
        code="E-06", name="emp_confirm_category",
        description="确认费用分类",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["category_selection"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "选差旅", "类别是办公", "分类选交通", "费用类别确认", "选第一个",
        ],
    ),
    Intent(
        code="E-07", name="emp_confirm_project",
        description="确认项目归属",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["project_id"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "项目选智慧城市", "归属项目A", "项目编号1", "确认项目", "选这个项目",
        ],
    ),
    Intent(
        code="E-08", name="emp_submit_reimbursement",
        description="提交报销单",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],  # invoice_list, purpose 为继承槽位
        optional_slots=["approver"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "提交报销", "提交", "报完了", "提交报销单", "确认提交",
        ],
    ),
    Intent(
        code="E-20", name="emp_fill_invoice_desc",
        description="为刚上传的发票补充用途描述/备注",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["purpose"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        prompt_template="请简要描述这笔费用的用途，例如：去机场打车",
        typical_utterances=[
            "用途是打车", "这笔是出差打车", "费用说明是", "备注一下用途", "描述一下",
        ],
    ),
    Intent(
        code="E-22", name="emp_batch_describe",
        description="批量用途描述——用户一条说明为多张发票分配用途，如\"前两张是差旅-交通，第三张是差旅-餐饮\"\"1和3是打车，2是餐费\"，LLM自动拆解映射",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["batch_description"],
        optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请描述各发票的用途，例如：\"前两张是差旅-交通，第三张是餐费\"",
        typical_utterances=[
            "前两张是差旅，第三张是餐费", "1和3是打车，2是餐费",
            "批量描述用途", "这几张都是办公用品", "分别是交通和住宿",
        ],
    ),
    Intent(
        code="E-23", name="emp_batch_modify",
        description="批量修改发票字段——用户可一次描述多个字段的修改，如\"金额改为100，日期改为2026-08-01\"\"把销售方改成XX公司，税号改成123\"",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["batch_modifications"],
        optional_slots=[],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请描述要修改的内容，例如：\"金额改为100，日期改为2026-08-01\"",
        typical_utterances=[
            "金额改为100，日期改为2026-08-01", "把销售方改成XX公司，税号改成123",
            "批量修改", "同时改金额和日期", "改一下这两张的金额",
        ],
    ),
    Intent(
        code="E-21", name="emp_delete_invoice",
        description="删除/撤销已上传但未提交的发票（如\"删除上一张\"\"撤销上传\"\"删除第2张\"\"删除那张机票\"）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["delete_target"],  # 值: "last"/"index:N"/"type:关键词"
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "删除上一张", "撤销上传", "删掉第2张", "删除那张机票", "撤销刚才的发票",
        ],
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
        typical_utterances=[
            "查询报销", "报销到哪了", "报销进度", "批了没", "查报销状态",
        ],
    ),
    Intent(
        code="E-10", name="emp_query_invoices",
        description="查询已上传发票列表",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["status_filter"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我的发票", "查看发票", "已上传的发票", "我传了哪些票", "发票列表",
        ],
    ),
    Intent(
        code="E-24", name="emp_query_my_reimbursement",
        description="查询本人的报销单列表（含报销周期、费用/补贴明细、封账状态）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我的报销单", "报销单列表", "我有哪些报销单", "看看我的报销单", "报销周期",
        ],
    ),
    Intent(
        code="E-25", name="emp_permission_denied",
        description="员工越权查询拦截：员工询问非本人数据（具体人名/公司全员/他人工号）时返回此意图，由 FSM 统一回复「没有权限，只能看本人的信息。」",
        role_scope=[UserRole.EMPLOYEE],
        required_slots=[],
        optional_slots=[],
        nlu_level=NluLevel.L3_LLM,
        typical_utterances=[
            "陈辉的发票", "张三报销了多少", "查看公司所有的发票",
            "所有员工的发票", "全公司的发票", "EMP002的发票",
            "陈辉的重复发票", "陈辉的收据", "陈辉验真失败的发票",
        ],
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
        typical_utterances=[
            "差旅标准是多少", "住宿标准", "报销政策", "补贴标准", "出差补贴多少",
        ],
    ),
    Intent(
        code="E-12", name="self_insight_total",
        description="查询本人报销总额",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我花了多少", "我报了多少", "我的报销总额", "我这个月花了多少", "我报销了多少钱",
        ],
    ),
    Intent(
        code="E-13", name="self_insight_category",
        description="查询本人费用分类占比",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["fee_category", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我哪类费用多", "我的费用分布", "我的费用占比", "我各类花了多少", "费用分类占比",
        ],
    ),
    Intent(
        code="E-14", name="self_insight_trend",
        description="查询本人费用趋势",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "我的费用趋势", "我最近开支走势", "我的费用变化", "我的报销趋势", "费用走势",
        ],
    ),
    Intent(
        code="E-15", name="self_insight_pending",
        description="查询本人未提交票据",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我还有多少没报的", "有没有没报的", "未提交票据", "还有发票没提交", "没报的票",
        ],
    ),
    Intent(
        code="E-16", name="self_insight_compare",
        description="本人期间费用对比",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我这个月比上个月花得多吗", "我的费用环比", "上月对比本月", "期间对比", "环比",
        ],
    ),
    Intent(
        code="E-17", name="self_insight_category_amount",
        description="查询本人某分类费用金额（如\"快递费花了多少\"）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=["fee_category_keyword"],
        optional_slots=["fee_category_aliases", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我的快递费花了多少", "差旅费报了多少", "我哪类费用最多", "我的餐费", "我的交通费",
        ],
    ),
    Intent(
        code="E-18", name="self_insight_invoice_total",
        description="查询本人发票统计（张数+金额+按状态分组）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我有多少张发票", "我的发票总金额", "我上传了多少发票", "发票统计", "我的发票数量",
        ],
    ),
    Intent(
        code="E-19", name="self_insight_invoice_filter",
        description="按条件筛选本人发票（重复/验真失败/高风险/待审核/收据等）",
        role_scope=[UserRole.EMPLOYEE, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["filter_type", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "我的重复发票", "我的验真失败的发票", "我的高风险发票", "我的收据", "我的待审核发票",
        ],
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
        typical_utterances=[
            "批准", "通过", "approve", "批准陈辉的报销", "通过这张报销单",
        ],
    ),
    Intent(
        code="A-02", name="admin_reject",
        description="驳回报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=["reimbursement_id"],
        optional_slots=["reason"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要驳回哪张报销单？",
        typical_utterances=[
            "驳回", "不通过", "拒绝", "驳回报销单", "reject",
        ],
    ),
    Intent(
        code="A-03", name="admin_batch_approve",
        description="批量审批报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=["filter"],
        optional_slots=[],
        nlu_level=NluLevel.L3_LLM,
        typical_utterances=[
            "批量批准", "全部通过", "批量审批", "一次通过所有", "批量approve",
        ],
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
        typical_utterances=[
            "部门报销", "按部门查", "销售部报销了多少", "技术部费用", "部门维度",
        ],
    ),
    Intent(
        code="A-05", name="admin_query_pending",
        description="查询待审批报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=[], optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "待审批", "还没处理的", "待审核列表", "待审批报销单", "待处理",
        ],
    ),
    Intent(
        code="A-06", name="admin_query_person",
        description="查询指定员工的报销单/费用（非发票），如报销了多少、有哪些报销单",
        role_scope=[UserRole.ADMIN],
        required_slots=["person"],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要查询哪位员工的费用情况？",
        typical_utterances=[
            "查张三的报销", "陈辉报销了多少", "查这个人的费用", "admin的报销", "查询员工报销费用",
        ],
    ),
    Intent(
        code="A-07", name="admin_query_detail",
        description="查看报销单详情",
        role_scope=[UserRole.ADMIN],
        required_slots=["reimbursement_id"],
        optional_slots=[],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "报销单详情", "查看30号报销单", "报销单明细", "看一下这张报销单", "详情",
        ],
    ),
    Intent(
        code="A-08", name="admin_export",
        description="导出报销明细",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["department", "period", "format"],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "导出报销明细", "导出Excel", "导出报表", "导出本月报销", "下载报表",
        ],
    ),
    Intent(
        code="A-08b", name="admin_query_cycle_summary",
        description="查询某报销周期汇总（报销单数、费用/补贴分拆、封账状态、各申请人明细）",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "周期汇总", "周期统计", "这个周期报销了多少", "封账了吗", "本月周期情况",
        ],
    ),
    Intent(
        code="A-09b", name="admin_mark_reimbursed",
        description="标记已审核报销单为已打款（REVIEWED → REIMBURSED），如\"打款""已打款""标记报销""确认打款\"",
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["person", "reimbursement_id"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要标记哪张报销单为已打款？可以报编号或报申请人姓名",
        typical_utterances=[
            "给30号打款", "30号已打款", "标记报销", "确认打款", "给陈辉打款",
        ],
    ),
    Intent(
        code="A-10", name="admin_aggregate_invoices",
        description='批量归集游离发票到报销单，如"生成报销单""归集发票""生成所有人的报销单""汇总发票到报销单"',
        role_scope=[UserRole.ADMIN],
        required_slots=[],
        optional_slots=["user_id"],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "生成报销单", "归集发票", "生成所有人的报销单", "汇总发票到报销单", "把发票生成报销单",
        ],
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
        typical_utterances=[
            "公司花了多少", "报销总额", "公司报销了多少", "本月公司费用", "总报销",
        ],
    ),
    Intent(
        code="A-10/B-03", name="insight_by_category",
        description="费用类别分布",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period", "department"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "差旅费占多少", "各类占比", "费用分布", "各类费用占比", "费用类别分布",
        ],
    ),
    Intent(
        code="A-10b/B-03b", name="insight_category_amount",
        description="查询某分类费用金额（如\"快递费花了多少\"）",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=["fee_category_keyword"],
        optional_slots=["fee_category_aliases", "period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "快递费花了多少", "差旅费报了多少", "哪些是差旅费", "办公费明细", "餐费金额",
        ],
    ),
    Intent(
        code="A-11/B-04", name="insight_trend",
        description="费用趋势",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        typical_utterances=[
            "趋势", "费用变化", "增长", "最近半年费用怎么变化", "走势",
        ],
    ),
    Intent(
        code="A-12/B-05", name="insight_anomaly",
        description="异常/超标/重复报销检测",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period", "anomaly_type"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "有没有异常", "超标", "重复报销", "违规", "有没有问题",
        ],
    ),
    Intent(
        code="A-13/B-08", name="insight_top",
        description="费用排名",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["limit", "period", "order", "data_scope"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "前5名", "排行榜", "谁报销最多", "费用最高的前10人", "排名",
        ],
    ),
    Intent(
        code="A-14/B-09", name="insight_project",
        description="项目费用统计",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=["project_name"],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要查询哪个项目的费用？",
        typical_utterances=[
            "智慧城市项目花了多少", "项目费用", "XX项目报销", "项目统计", "项目成本",
        ],
    ),
    Intent(
        code="A-15/B-10", name="insight_invoice_total",
        description="全公司发票统计+发票列表（张数/金额/按状态分组/发票明细），支持按员工筛选。查看/列出XX的发票也走此意图",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["period", "person"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "上传了多少发票", "发票总金额", "一共多少张发票", "发票统计", "陈辉有多少张发票",
            "查看公司所有发票", "查看陈辉的发票", "列出所有发票",
        ],
    ),
    Intent(
        code="A-16/B-11", name="insight_invoice_filter",
        description="按条件筛选发票列表（重复/验真失败/高风险/待审核/收据等）",
        role_scope=[UserRole.ADMIN, UserRole.BOSS],
        required_slots=[],
        optional_slots=["filter_type", "period", "person"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "重复的发票", "验真失败的", "高风险的发票", "待审核的发票", "收据有哪些",
        ],
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
        typical_utterances=[
            "哪个部门花得多", "各部门报销", "按部门统计", "部门排名", "部门费用对比",
        ],
    ),
    Intent(
        code="B-06", name="insight_person",
        description="指定员工费用查询",
        role_scope=[UserRole.BOSS, UserRole.ADMIN],
        required_slots=["person"],
        optional_slots=["period"],
        nlu_level=NluLevel.L2_SEMANTIC,
        prompt_template="请问要查询哪位员工的费用情况？",
        typical_utterances=[
            "查看张三的报销", "admin的费用", "查这个人的报销", "李四报销了多少", "某人费用",
        ],
    ),
    Intent(
        code="B-07", name="insight_compare",
        description="期间费用对比",
        role_scope=[UserRole.BOSS, UserRole.ADMIN],
        required_slots=[],
        optional_slots=["period"],
        nlu_level=NluLevel.L1_KEYWORD,
        typical_utterances=[
            "环比", "上月比本月", "期间对比", "同比", "两个时间段对比",
        ],
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
