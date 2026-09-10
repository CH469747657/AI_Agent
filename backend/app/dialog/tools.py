"""Tool 实例定义 — Step 3.1.2

把 ActionExecutor 中的 20+ handler 改写为 Tool 实例。
采用桥接模式：每个 Tool 子类只声明元数据，run() 委托给 ActionExecutor 对应 handler。
后续若需脱离 ActionExecutor，子类覆盖 run() 即可。
"""

from __future__ import annotations

from .tool_registry import _BridgeTool, _InsightBridgeTool, Tool
from .tool_params import (
    UploadInvoiceParams, FillInvoiceDescParams, BatchDescribeParams,
    BatchModifyParams, NoReceiptParams, SubmitReimbursementParams,
    ModifyFieldParams, ConfirmCategoryParams, ConfirmProjectParams,
    DeleteInvoiceParams, QueryInvoicesParams, QueryStatusParams,
    QueryMyReimbursementParams, AdminApproveParams, AdminRejectParams,
    AdminQueryPendingParams, AdminQueryDetailParams, AdminQueryCycleSummaryParams,
    AdminMarkReimbursedParams, AdminAggregateInvoicesParams,
    LegacyFallbackParams,
    MarkTravelDayParams,
    InsightTotalParams, InsightByCategoryParams, InsightCategoryAmountParams,
    InsightTrendParams, InsightCompareParams, InsightPendingParams,
    InsightInvoiceTotalParams, InsightInvoiceFilterParams,
    InsightAnomalyParams, InsightTopParams, InsightProjectParams,
    InsightByDeptParams, InsightPersonParams,
)
from .models import UserRole


# ============================================================
# 员工提单类 Tool
# ============================================================

class UploadInvoiceTool(_BridgeTool):
    name = "emp_upload_invoice"
    description = "上传发票图片/PDF/OFD，自动 OCR 识别字段并验真"
    Parameters = UploadInvoiceParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_upload_invoice"


class FillInvoiceDescTool(_BridgeTool):
    name = "emp_fill_invoice_desc"
    description = (
        "为刚上传的发票补充用途描述/出差日期。**关键拆分规则**：用户回复中"
        "若同时包含日期+用途（如「8月2日 打车费」「出差时间8月1日，项目投标费」"
        "「7月15号去上海打车」），必须拆分为两个参数：purpose 只填用途短语（不含日期），"
        "expense_date 填 YYYY-MM-DD 日期。用户只说月日未带年份时用当前年份 2026 补全。"
        "反例：purpose=\"8月2日 打车费\" ❌（日期被塞进用途）。"
        "正例：purpose=\"打车费\" + expense_date=\"2026-08-02\" ✓"
    )
    Parameters = FillInvoiceDescParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_fill_invoice_desc"


class BatchDescribeTool(_BridgeTool):
    name = "emp_batch_describe"
    description = "批量用途描述——用户一条说明为多张发票分配用途"
    Parameters = BatchDescribeParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_batch_describe"


class BatchModifyTool(_BridgeTool):
    name = "emp_batch_modify"
    description = "批量修改发票字段——用户一次描述多个字段的修改"
    Parameters = BatchModifyParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_batch_modify"


class NoReceiptTool(_BridgeTool):
    name = "emp_no_receipt"
    description = (
        "员工无票报销。仅当用户文本明确提到「无票/无凭证/没有发票/无票报销」"
        "且提供有效金额（正数 0<金额≤100000 元）+ 有效用途描述（≥2 个汉字，"
        "明确说明费用类型/场景，如「打车费」「客户招待餐费」「办公文具采购」）"
        "时才调用此工具。若任一条件不满足，不要调用此工具，直接用自然语言"
        "引导用户补充金额或用途。"
    )
    Parameters = NoReceiptParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_no_receipt"


class SubmitReimbursementTool(_BridgeTool):
    name = "emp_submit_reimbursement"
    description = "提交报销单"
    Parameters = SubmitReimbursementParams
    required_roles = [UserRole.ADMIN]  # 员工端禁用，由系统自动归集
    handler_method = "_handle_submit_reimbursement"


class ModifyFieldTool(_BridgeTool):
    name = "emp_modify_field"
    description = "修改发票字段（金额/日期/销售方/税号等）"
    Parameters = ModifyFieldParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_modify_field"


class ConfirmCategoryTool(_BridgeTool):
    name = "emp_confirm_category"
    description = "确认费用分类"
    Parameters = ConfirmCategoryParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_confirm_category"


class ConfirmProjectTool(_BridgeTool):
    name = "emp_confirm_project"
    description = "确认项目归属"
    Parameters = ConfirmProjectParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_confirm_project"


class DeleteInvoiceTool(_BridgeTool):
    name = "emp_delete_invoice"
    description = "删除/撤销已上传但未提交的发票"
    Parameters = DeleteInvoiceParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_delete_invoice"


class MarkTravelDayTool(_BridgeTool):
    name = "emp_mark_travel_day"
    description = (
        "员工在对话中描述出差日期/行程，标记为报销补贴用的出差日。"
        "如：8月15日去北京出差、8月15-17日出差、2026-08-15 出差、下周二出差。"
        "标记后自动核算补贴（工作日60/节假日80元）。"
        "注意：travel_dates 必须展开为完整日期数组（区间如 8月15-17日 → 3 个日期），"
        "不要返回 ['8月15-17日'] 这种字符串"
    )
    Parameters = MarkTravelDayParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_mark_travel_day"


# ============================================================
# 员工查询类 Tool
# ============================================================

class QueryInvoicesTool(_BridgeTool):
    name = "emp_query_invoices"
    description = "查询用户发票列表"
    Parameters = QueryInvoicesParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    handler_method = "_handle_query_invoices"


class QueryStatusTool(_BridgeTool):
    name = "emp_query_status"
    description = "查询报销单进度"
    Parameters = QueryStatusParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS]
    handler_method = "_handle_query_status"


class QueryMyReimbursementTool(_BridgeTool):
    name = "emp_query_my_reimbursement"
    description = "查询本人的报销单列表（含报销周期、费用/补贴明细、封账状态）"
    Parameters = QueryMyReimbursementParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS]
    handler_method = "_handle_query_my_reimbursement"


# ============================================================
# 管理员操作 Tool
# ============================================================

class AdminApproveTool(_BridgeTool):
    name = "admin_approve"
    description = "批准报销单"
    Parameters = AdminApproveParams
    required_roles = [UserRole.ADMIN]
    handler_method = "_handle_admin_approve"


class AdminRejectTool(_BridgeTool):
    name = "admin_reject"
    description = "驳回报销单"
    Parameters = AdminRejectParams
    required_roles = [UserRole.ADMIN]
    handler_method = "_handle_admin_reject"


class AdminQueryPendingTool(_BridgeTool):
    name = "admin_query_pending"
    description = "查询待审批报销单列表"
    Parameters = AdminQueryPendingParams
    required_roles = [UserRole.ADMIN]
    handler_method = "_handle_admin_pending"


class AdminQueryDetailTool(_BridgeTool):
    name = "admin_query_detail"
    description = "查看报销单详情"
    Parameters = AdminQueryDetailParams
    required_roles = [UserRole.ADMIN]
    handler_method = "_handle_admin_detail"


class AdminQueryCycleSummaryTool(_BridgeTool):
    name = "admin_query_cycle_summary"
    description = "查询某报销周期汇总（报销单数、费用/补贴分拆、封账状态）"
    Parameters = AdminQueryCycleSummaryParams
    required_roles = [UserRole.ADMIN]
    handler_method = "_handle_admin_cycle_summary"


class AdminMarkReimbursedTool(_BridgeTool):
    name = "admin_mark_reimbursed"
    description = "标记已审核报销单为已打款"
    Parameters = AdminMarkReimbursedParams
    required_roles = [UserRole.ADMIN]
    handler_method = "_handle_admin_mark_reimbursed"


class AdminAggregateInvoicesTool(_BridgeTool):
    name = "admin_aggregate_invoices"
    description = "批量归集游离发票到报销单（也支持「生成报销单」「为陈辉生成报销单」「把发票汇总到报销单」等说法）。可指定员工或全部员工"
    Parameters = AdminAggregateInvoicesParams
    required_roles = [UserRole.ADMIN]
    handler_method = "_handle_admin_aggregate_invoices"


# ============================================================
# 降级 meta-tool — LLM 主动降级到 legacy 路径
# ============================================================

class LegacyFallbackTool(Tool):
    """legacy_fallback meta-tool — LLM 判断本工具列表无法处理时调用

    触发场景：用户请求涉及报销统计/趋势/异常/占比等洞察分析
    （如"我花了多少""公司报销总额""趋势""异常""占比"），
    这些洞察类意图无对应 Tool，由 LLM 主动调用本 tool 降级到 legacy 路径。
    """
    name = "legacy_fallback"
    description = (
        "当用户请求涉及报销统计/趋势/异常/占比等洞察分析"
        "（如'我花了多少''公司报销总额''趋势''异常''占比''哪个部门花得多'），"
        "或本工具列表无法处理该请求时，调用此工具。系统将切换到 legacy 路径处理。"
    )
    Parameters = LegacyFallbackParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.BOSS]

    async def run(self, ctx, db, params) -> dict:
        logger_info = getattr(ctx, "current_text", "")
        from .tool_registry import logger as _logger
        _logger.info(
            "LegacyFallbackTool invoked: user=%s reason=%s text=%r",
            ctx.user_id,
            params.reason if params else "",
            logger_info[:50],
        )
        return {
            "text": "",
            "data": {"legacy_fallback": True},
        }


# ============================================================
# Insight 洞察类 Tool — 让 LLM 通过 Function Calling 自决查询维度
# 替代 legacy 路径的 if-else 硬路由，消除 insight_category_amount vs
# insight_invoice_filter 的路由歧义（LLM 自决调哪个 Tool）
# ============================================================

# ---- 员工自我洞察（数据范围限本人，由 InsightEngine 内部 WHERE user_id=ctx.user_id 强制）----

class SelfInsightTotalTool(_InsightBridgeTool):
    name = "self_insight_total"
    description = "我的报销总额（金额汇总+按状态分组），如'我花了多少''我报了多少'"
    Parameters = InsightTotalParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_total"


class SelfInsightCategoryTool(_InsightBridgeTool):
    name = "self_insight_category"
    description = "我的费用分类占比分布，如'我哪类费用多''我的费用分布''各类占比'"
    Parameters = InsightByCategoryParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_category"


class SelfInsightCategoryAmountTool(_InsightBridgeTool):
    name = "self_insight_category_amount"
    description = (
        "我的某类费用金额/明细，如'快递费花了多少''我有哪些打车费的发票''打车费明细'"
        "'差旅费报了多少''哪些是打车费'。指定具体分类名查询该分类下的发票或金额"
    )
    Parameters = InsightCategoryAmountParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_category_amount"


class SelfInsightTrendTool(_InsightBridgeTool):
    name = "self_insight_trend"
    description = "我的费用趋势，如'我的费用变化''我最近开支走势''有没有涨'"
    Parameters = InsightTrendParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_trend"


class SelfInsightCompareTool(_InsightBridgeTool):
    name = "self_insight_compare"
    description = "我的期间费用对比，如'这个月比上个月花得多吗''环比''上月和本月对比'"
    Parameters = InsightCompareParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_compare"


class SelfInsightPendingTool(_InsightBridgeTool):
    name = "self_insight_pending"
    description = "我的未提交票据，如'有没有没报的''还有发票没提交''还有多少没报的'"
    Parameters = InsightPendingParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_pending"


class SelfInsightInvoiceTotalTool(_InsightBridgeTool):
    name = "self_insight_invoice_total"
    description = "我的发票统计（张数/金额/按状态分组+明细列表），如'我上传了多少发票''我有多少张发票'"
    Parameters = InsightInvoiceTotalParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_invoice_total"


class SelfInsightInvoiceFilterTool(_InsightBridgeTool):
    name = "self_insight_invoice_filter"
    description = (
        "按异常条件筛选我的发票列表，如'重复的发票''验真失败的''高风险的发票'"
        "'待审核的发票''有收据吗''收据有哪些'。**仅筛异常条件**，"
        "若用户问'我有哪些X费的发票'应改调 self_insight_category_amount 工具"
    )
    Parameters = InsightInvoiceFilterParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]
    intent_name = "self_insight_invoice_filter"


# ---- 管理员/老板全局洞察（数据范围全公司）----

class InsightTotalTool(_InsightBridgeTool):
    name = "insight_total"
    description = "全公司报销总额，如'公司花了多少''报销总额'"
    Parameters = InsightTotalParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_total"


class InsightByCategoryTool(_InsightBridgeTool):
    name = "insight_by_category"
    description = "全公司费用分类占比，如'差旅费占多少''各类占比''费用分布'"
    Parameters = InsightByCategoryParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_by_category"


class InsightCategoryAmountTool(_InsightBridgeTool):
    name = "insight_category_amount"
    description = (
        "全公司某分类费用金额/明细，如'快递费花了多少''公司打车费有多少'"
        "'差旅费报了多少''哪些是差旅费'。指定分类名查该分类下的发票或金额"
    )
    Parameters = InsightCategoryAmountParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_category_amount"


class InsightTrendTool(_InsightBridgeTool):
    name = "insight_trend"
    description = "全公司费用趋势，如'趋势''变化''增长''走势'"
    Parameters = InsightTrendParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_trend"


class InsightAnomalyTool(_InsightBridgeTool):
    name = "insight_anomaly"
    description = "异常检测综合报告，如'有没有异常''超标''违规''重复报销'"
    Parameters = InsightAnomalyParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_anomaly"


class InsightTopTool(_InsightBridgeTool):
    name = "insight_top"
    description = "费用排名，如'前5名''排行榜''谁花得最多'"
    Parameters = InsightTopParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_top"


class InsightProjectTool(_InsightBridgeTool):
    name = "insight_project"
    description = "项目费用统计，如'项目投标的报销''智慧城市项目花了多少'"
    Parameters = InsightProjectParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_project"


class InsightByDeptTool(_InsightBridgeTool):
    name = "insight_by_dept"
    description = "部门费用统计，如'哪个部门花得多''各部门报销'"
    Parameters = InsightByDeptParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_by_dept"


class InsightPersonTool(_InsightBridgeTool):
    name = "insight_person"
    description = "某人报销费用，如'查看张三的报销''admin的费用''陈辉报销了多少'"
    Parameters = InsightPersonParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_person"


class InsightCompareTool(_InsightBridgeTool):
    name = "insight_compare"
    description = "全公司期间费用对比，如'环比''上月比本月''同比'"
    Parameters = InsightCompareParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_compare"


class InsightInvoiceTotalTool(_InsightBridgeTool):
    name = "insight_invoice_total"
    description = (
        "全公司发票统计（张数/金额/按状态分组+明细列表），如'上传了多少发票'"
        "'发票总金额''一共多少张发票''查看公司所有的发票'。支持 person 按员工筛选"
    )
    Parameters = InsightInvoiceTotalParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_invoice_total"


class InsightInvoiceFilterTool(_InsightBridgeTool):
    name = "insight_invoice_filter"
    description = (
        "按异常条件筛选全公司发票列表，如'重复的发票''验真失败的''高风险的发票'"
        "'待审核的发票''有收据吗''陈辉的重复发票'。支持 person 按员工筛选。"
        "**仅筛异常条件**，若用户问'X费的发票有哪些'应改调 insight_category_amount 工具"
    )
    Parameters = InsightInvoiceFilterParams
    required_roles = [UserRole.ADMIN, UserRole.BOSS]
    intent_name = "insight_invoice_filter"


# ============================================================
# 注册所有 Tool
# ============================================================

ALL_TOOLS: list[type] = [
    # 员工提单
    UploadInvoiceTool,
    FillInvoiceDescTool,
    BatchDescribeTool,
    BatchModifyTool,
    NoReceiptTool,
    SubmitReimbursementTool,
    ModifyFieldTool,
    ConfirmCategoryTool,
    ConfirmProjectTool,
    DeleteInvoiceTool,
    MarkTravelDayTool,
    # 员工查询
    QueryInvoicesTool,
    QueryStatusTool,
    QueryMyReimbursementTool,
    # 管理员操作
    AdminApproveTool,
    AdminRejectTool,
    AdminQueryPendingTool,
    AdminQueryDetailTool,
    AdminQueryCycleSummaryTool,
    AdminMarkReimbursedTool,
    AdminAggregateInvoicesTool,
    # 员工自我洞察
    SelfInsightTotalTool,
    SelfInsightCategoryTool,
    SelfInsightCategoryAmountTool,
    SelfInsightTrendTool,
    SelfInsightCompareTool,
    SelfInsightPendingTool,
    SelfInsightInvoiceTotalTool,
    SelfInsightInvoiceFilterTool,
    # 管理员/老板全局洞察
    InsightTotalTool,
    InsightByCategoryTool,
    InsightCategoryAmountTool,
    InsightTrendTool,
    InsightAnomalyTool,
    InsightTopTool,
    InsightProjectTool,
    InsightByDeptTool,
    InsightPersonTool,
    InsightCompareTool,
    InsightInvoiceTotalTool,
    InsightInvoiceFilterTool,
    # 降级 meta-tool
    LegacyFallbackTool,
]


def register_all_tools() -> int:
    """把所有 Tool 实例注册到全局 ToolRegistry

    Returns:
        注册的 Tool 数量
    """
    from .tool_registry import get_tool_registry
    registry = get_tool_registry()
    registry._tools.clear()  # 清空旧注册
    for ToolClass in ALL_TOOLS:
        registry.register(ToolClass())
    return len(ALL_TOOLS)
