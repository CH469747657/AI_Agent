"""Tool 参数 Pydantic schema 定义 — Step 3.1.2

为每个 Tool 定义严格的参数 schema，替代 Intent 的 required_slots list。
LLM 通过 function calling 输出 tool_call 时，参数会被 Pydantic 自动校验。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================
# 员工提单类 Tool 参数
# ============================================================

class UploadInvoiceParams(BaseModel):
    """上传发票参数"""
    model_config = {"extra": "allow"}  # 允许额外字段（如 base64 附件）
    receipt_type: Optional[str] = Field(
        default="增值税普通发票",
        description="发票类型：增值税普通发票/增值税专用发票/火车票/机票/收据/支付截图/交易流水单",
    )
    user_description: Optional[str] = Field(default="", description="费用用途描述")


class FillInvoiceDescParams(BaseModel):
    """补充发票用途描述参数

    支持一次性同时补充用途和出差日期——用户回复"出差时间8月1日，项目投标费"
    或"8月2日 打车费"时，LLM 应拆分为：
    - purpose="项目投标费"（仅用途短语，**不含日期**）
    - expense_date="2026-08-01"（YYYY-MM-DD，未识别到日期则不填）
    两个参数同时传入，避免日期信息被塞进 purpose。
    """
    model_config = {"extra": "allow"}
    purpose: str = Field(
        description=(
            "费用用途短语，**仅用途描述，不含日期**。如：去机场打车 / 项目投标费 / 寄合同至北京 / 员工培训住宿费"
        ),
    )
    expense_date: Optional[str] = Field(
        default=None,
        description=(
            "出差/费用发生日期，YYYY-MM-DD 格式。用户文本中提到日期时必须提取并填入此字段，"
            "不要把日期塞进 purpose。如：用户说「8月2日 打车费」→ purpose=\"打车费\" + expense_date=\"2026-08-02\"。"
            "用户只说月日未带年份时用当前年份 2026 补全。未识别到日期则留空。"
        ),
    )
    expense_date: Optional[str] = Field(
        default=None,
        description=(
            "出差日期/费用发生日期，格式 YYYY-MM-DD（如 2026-08-01）。"
            "用户提到'出差时间8月1日''7月15号出差''费用日期2026-08-01'时填此参数。"
            "不涉及日期时留空。年份缺省时用当前年份 2026"
        ),
    )


class BatchDescribeParams(BaseModel):
    """批量描述用途参数"""
    model_config = {"extra": "allow"}
    batch_description: str = Field(description='批量描述，如："前两张是差旅-交通，第三张是餐费"')


class BatchModifyParams(BaseModel):
    """批量修改字段参数"""
    model_config = {"extra": "allow"}
    batch_modifications: str = Field(description='批量修改描述，如："金额改为100，日期改为2026-08-01"')


class NoReceiptParams(BaseModel):
    """无票报销参数

    LLM 通过 function calling 输出参数时由 Pydantic 自动校验：
    - amount 必须为正数（> 0），负数 / 零 / 非数字 / 过大金额（>100000）会被拒绝
    - description 不能为空或仅含符号/单字符
    """
    model_config = {"extra": "allow"}
    amount: float = Field(
        gt=0,
        le=100000,
        description="报销金额（正数，单位：元，最大 100000）。如：120 / 88.5",
    )
    description: str = Field(
        min_length=2,
        max_length=200,
        description="费用用途说明（2-200 字，需为有意义的中文描述，不能仅为符号或单字符）",
    )


class MarkTravelDayParams(BaseModel):
    """标记出差日参数"""
    model_config = {"extra": "allow"}
    travel_dates: list[str] = Field(
        description=(
            "出差日期列表，YYYY-MM-DD 格式字符串数组。"
            "支持单日['2026-08-15']、多日['2026-08-15','2026-08-16','2026-08-17']、"
            "区间必须展开为完整列表。"
        )
    )
    note: Optional[str] = Field(
        default=None,
        description="出差备注，如：北京出差、返程、上海谈客户。无明确备注则留空",
    )


class SubmitReimbursementParams(BaseModel):
    """提交报销单参数"""
    model_config = {"extra": "allow"}
    invoice_ids: Optional[list[int]] = Field(default=None, description="发票ID列表，缺省时用 batch_invoice_ids")


class ModifyFieldParams(BaseModel):
    """修改发票字段参数"""
    model_config = {"extra": "allow"}
    field_name: str = Field(description="要修改的字段名：金额/日期/销售方/税号/发票号/用途")
    field_value: str = Field(description="字段新值")
    invoice_id: Optional[int] = Field(default=None, description="发票编号（如 #896 → 896），精准定位，优先于 invoice_index")
    invoice_index: Optional[int] = Field(default=None, description="第N张（1-based，按用户发票列表 created_at DESC 排序），缺省时用 pending_invoice_id")


class ConfirmCategoryParams(BaseModel):
    """确认费用分类参数"""
    model_config = {"extra": "allow"}
    category_selection: str = Field(description="分类选项")


class ConfirmProjectParams(BaseModel):
    """确认项目归属参数"""
    model_config = {"extra": "allow"}
    project_id: int = Field(description="项目ID")


class DeleteInvoiceParams(BaseModel):
    """删除发票参数"""
    model_config = {"extra": "allow"}
    delete_target: Optional[str] = Field(
        default="last",
        description='删除目标：last=最近一张 / index:N=第N张 / type:关键词=按类型匹配',
    )


# ============================================================
# 员工查询类 Tool 参数
# ============================================================

class QueryInvoicesParams(BaseModel):
    """查询发票列表参数"""
    model_config = {"extra": "allow"}
    status_filter: Optional[str] = Field(default=None, description="状态筛选")


class QueryStatusParams(BaseModel):
    """查询报销进度参数"""
    model_config = {"extra": "allow"}
    reimbursement_id: Optional[int] = Field(default=None, description="报销单ID")


class QueryMyReimbursementParams(BaseModel):
    """查询我的报销单参数"""
    model_config = {"extra": "allow"}
    period: Optional[str] = Field(default=None, description="时间段，如：current_month/last_month")


# ============================================================
# 管理员操作 Tool 参数
# ============================================================

class AdminApproveParams(BaseModel):
    """管理员批准报销参数"""
    model_config = {"extra": "allow"}
    reimbursement_id: Optional[int] = Field(default=None, description="报销单ID")
    person: Optional[str] = Field(default=None, description="申请人姓名（按人操作）")


class AdminRejectParams(BaseModel):
    """管理员驳回报销参数"""
    model_config = {"extra": "allow"}
    reimbursement_id: int = Field(description="报销单ID")
    reason: Optional[str] = Field(default=None, description="驳回原因")


class AdminQueryPendingParams(BaseModel):
    """查询待审批列表参数"""
    model_config = {"extra": "allow"}


class AdminQueryDetailParams(BaseModel):
    """查看报销单详情参数"""
    model_config = {"extra": "allow"}
    reimbursement_id: int = Field(description="报销单ID")


class AdminQueryCycleSummaryParams(BaseModel):
    """查询周期汇总参数"""
    model_config = {"extra": "allow"}
    period: Optional[str] = Field(default=None, description="周期，如：2026-07")


class AdminMarkReimbursedParams(BaseModel):
    """标记已打款参数"""
    model_config = {"extra": "allow"}
    reimbursement_id: Optional[int] = Field(default=None, description="报销单ID")
    person: Optional[str] = Field(default=None, description="申请人姓名")


class AdminAggregateInvoicesParams(BaseModel):
    """批量归集发票参数"""
    model_config = {"extra": "allow"}
    user_id: Optional[str] = Field(default=None, description="指定员工ID，缺省归集所有人")
    person: Optional[str] = Field(default=None, description="员工姓名或工号（如「陈辉」「EMP001」），用于定位单个员工归集；与 user_id 二选一")


# ============================================================
# 通用空参数（无参 Tool 用）
# ============================================================

class EmptyParams(BaseModel):
    """无参数 Tool 的空 schema"""
    model_config = {"extra": "allow"}


class LegacyFallbackParams(BaseModel):
    """legacy_fallback meta-tool 参数 — LLM 主动降级到 legacy 路径"""
    model_config = {"extra": "allow"}
    reason: str = Field(description="降级原因，说明为何本工具列表无法处理该请求")


# ============================================================
# Insight 类 Tool 参数 — 让 LLM 通过参数自决查询维度
# ============================================================

class InsightBaseParams(BaseModel):
    """Insight Tool 通用参数基类

    period / person 是所有 insight 查询都可能用到的通用筛选参数。
    各子类按需追加自身专属参数（如 fee_category_keyword、filter_type、anomaly_type 等）。
    """
    model_config = {"extra": "allow"}
    period: Optional[str] = Field(
        default=None,
        description=(
            "时间段，标准枚举值：today/yesterday/current_week/last_week/"
            "current_month/last_month/current_year/last_year/last_6_months/last_12_months/all_time/"
            "YYYY-MM（如 2026-08）/YYYY（如 2026）。"
            "口语词如'上上周''前天''Q2''本月''去年'由 LLM 转换为标准值"
        ),
    )
    person: Optional[str] = Field(
        default=None,
        description="指定员工姓名或工号（仅 admin/boss 角色有效，员工角色填本人会被忽略，非本人会被拒绝）",
    )


class InsightTotalParams(InsightBaseParams):
    """报销总额统计 — self_insight_total / insight_total"""
    # 无额外字段，仅通用 period+person


class InsightByCategoryParams(InsightBaseParams):
    """费用分类占比 — self_insight_category / insight_by_category"""
    # 通用参数即可


class InsightCategoryAmountParams(InsightBaseParams):
    """某分类费用金额/明细 — self_insight_category_amount / insight_category_amount

    用户问"我有哪些打车费的发票""快递费花了多少""差旅费报了多少"等，
    指定具体分类名查该分类下的发票或金额明细。
    """
    fee_category_keyword: Optional[str] = Field(
        default=None,
        description=(
            "费用分类关键词，如：打车费/快递费/差旅费/餐饮费/培训费/投标费/办公费/住宿费/交通费。"
            "可以是口语词（如'打车费''出行费'），系统会用 LLM 语义匹配 subcategory/description 字段"
        ),
    )


class InsightTrendParams(InsightBaseParams):
    """费用趋势 — self_insight_trend / insight_trend"""
    # 通用参数即可


class InsightCompareParams(InsightBaseParams):
    """期间费用对比 — self_insight_compare / insight_compare"""
    # 通用参数即可


class InsightPendingParams(InsightBaseParams):
    """未提交票据 — self_insight_pending"""
    # 通用参数即可


class InsightInvoiceTotalParams(InsightBaseParams):
    """发票统计（张数/金额/按状态分组+明细）— self_insight_invoice_total / insight_invoice_total"""
    # 通用参数即可


class InsightInvoiceFilterParams(InsightBaseParams):
    """按条件筛选发票列表 — self_insight_invoice_filter / insight_invoice_filter

    filter_type 用 Literal 严格枚举，Pydantic 校验失败会触发重试或参数错误。
    LLM 无法将费用分类词填入此字段，避免误路由。
    """
    filter_type: Optional[Literal["duplicate", "invalid", "high_risk", "pending", "receipt"]] = Field(
        default=None,
        description=(
            "异常筛选类型，**严格枚举**："
            "duplicate=重复发票 / invalid=验真失败 / high_risk=高风险 / pending=待审核 / receipt=收据。"
            "**绝不能填入费用分类名**（如打车费/快递费），分类查询应改调 query_category_amount 工具"
        ),
    )


class InsightAnomalyParams(InsightBaseParams):
    """异常检测综合报告 — insight_anomaly"""
    anomaly_type: Optional[str] = Field(
        default=None,
        description="异常类型，可选：duplicate/invalid/high_risk/over_budget。不填则综合扫描所有异常",
    )


class InsightTopParams(InsightBaseParams):
    """费用排名 — insight_top"""
    top_n: Optional[int] = Field(default=5, description="排名前N，默认5")
    sort_by: Optional[str] = Field(
        default="amount",
        description="排序维度，可选：amount=按金额 / count=按张数",
    )


class InsightProjectParams(InsightBaseParams):
    """项目费用统计 — insight_project"""
    project_name: Optional[str] = Field(default=None, description="项目名称关键词")


class InsightByDeptParams(InsightBaseParams):
    """部门费用统计 — insight_by_dept"""
    # 通用参数即可


class InsightPersonParams(InsightBaseParams):
    """某人报销费用 — insight_person

    person 是必填（要查谁的报销）。继承 InsightBaseParams 已含 person 字段。
    """
