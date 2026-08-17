"""Pydantic 数据验证模型"""

from pydantic import BaseModel, Field
from datetime import datetime, date


class InvoiceUploadRequest(BaseModel):
    receipt_type: str = "增值税普通发票"
    user_id: str
    user_description: str = Field(..., min_length=1)


class InvoiceResponse(BaseModel):
    id: int
    receipt_type: str
    status: str
    user_id: str | None = None
    uploader_name: str | None = None  # 上传者显示名（员工: 姓名(工号)，管理员: admin）
    invoice_number: str | None = None
    invoice_code: str | None = None
    check_code: str | None = None
    issue_date: str | None = None
    expense_date: date | None = None  # 费用发生日期（三级判定后回填）
    expense_date_source: str | None = None  # note/issue_date/receipt_date/upload_time
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    seller_name: str | None = None
    seller_tax_id: str | None = None
    item_name: str | None = None
    total_with_tax: str | None = None
    amount: str | None = None
    tax_amount: str | None = None
    tax_rate: str | None = None
    fee_category: str | None = None
    fee_subcategory: str | None = None
    project_id: int | None = None
    diff_confidence: float | None = None
    diff_conflicts: list | None = None
    verify_status: str | None = None
    verify_message: str | None = None
    duplicate_status: str | None = None
    user_description: str | None = None
    reimbursement_id: int | None = None
    is_nonstandard: bool | None = None
    vlm_confidence: float | None = None
    risk_level: str | None = None
    receipt_detail: dict | None = None
    processing_pipeline: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class InvoiceUpdateRequest(BaseModel):
    fee_category: str | None = None
    fee_subcategory: str | None = None
    project_id: int | None = None
    status: str | None = None
    user_description: str | None = None


class InvoiceVerifyRequest(BaseModel):
    verify_status: str  # VALID / INVALID / UNABLE_TO_VERIFY


class OnlineVerifyResponse(BaseModel):
    """在线验真接口返回"""
    invoice_id: int
    verify_status: str  # VALID / INVALID / PENDING / UNABLE_TO_VERIFY
    message: str
    is_verified: bool | None = None  # None=降级未执行, True=验真通过, False=验真未通过
    invoice_status: str | None = None  # N=正常, Y=已作废, H=已冲红
    verified_fields: dict | None = None  # 百度返回的票面信息（交叉验证用）
    invoice: InvoiceResponse | None = None


class NoReceiptRequest(BaseModel):
    user_id: str
    user_description: str
    amount: str = ""


class ProjectCreateRequest(BaseModel):
    name: str
    code: str | None = None
    member_ids: list[str] = []
    supplier_names: list[str] = []
    description: str | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    code: str | None = None
    status: str

    class Config:
        from_attributes = True


class ReimbursementCreateRequest(BaseModel):
    applicant_id: str
    applicant_name: str | None = None
    department: str | None = None
    period: str | None = None
    reason: str | None = None
    invoice_ids: list[int] = []


class ReimbursementResponse(BaseModel):
    id: int
    applicant_id: str
    applicant_name: str | None = None
    department: str | None = None
    period: str | None = None
    reason: str | None = None
    total_amount: float | None = None
    expense_total: float | None = None
    subsidy_total: float | None = None
    status: str
    cycle_start: date | None = None
    cycle_end: date | None = None
    cycle_key: str | None = None
    auto_generated: bool = False
    is_cycle_locked: bool = False
    locked_at: datetime | None = None
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None
    excel_path: str | None = None
    pdf_path: str | None = None
    zip_path: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class ReimbursementItemResponse(BaseModel):
    """报销单明细行"""
    id: int
    invoice_id: int | None = None
    item_date: date | None = None
    item_date_source: str | None = None
    weekday: int | None = None
    fee_category: str | None = None
    fee_subcategory: str | None = None
    amount: float
    description: str | None = None
    is_late_charge: bool = False
    intended_cycle_key: str | None = None
    sort_order: int = 0

    class Config:
        from_attributes = True


class ReimbursementDaySubsidyResponse(BaseModel):
    """日补贴记录"""
    id: int
    subsidy_date: date
    weekday: int | None = None
    day_type: str | None = None
    base_rate: float | None = None
    subsidy_amount: float
    included: bool = True
    exclude_reason: str | None = None
    trigger_invoice_count: int = 0

    class Config:
        from_attributes = True


class TravelDayCreateRequest(BaseModel):
    """员工标记出差日请求"""
    travel_date: date
    note: str | None = None


class TravelDayResponse(BaseModel):
    """出差日记录"""
    id: int
    reimbursement_id: int
    travel_date: date
    note: str | None = None
    weekday: int | None = None
    day_type: str | None = None
    base_rate: float | None = None
    applicant_id: str

    class Config:
        from_attributes = True


class ReimbursementLinkRequest(BaseModel):
    invoice_ids: list[int]


class SubsidyToggleRequest(BaseModel):
    """手动切换日补贴计入/取消"""
    subsidy_date: date
    included: bool
    exclude_reason: str | None = None


class AggregateRequest(BaseModel):
    """批量归集游离发票到报销单"""
    user_id: str | None = None  # None=全公司，指定则只归集该用户


class StatisticsResponse(BaseModel):
    total_invoices: int
    total_amount: float
    total_tax: float
    pending_review: int
    confirmed: int
    duplicates: int
    nonstandard_count: int = 0
    high_risk_count: int = 0


class WeComProcessRequest(BaseModel):
    """企微网关转发到后端的处理请求"""
    user_id: str
    file_data: str = ""  # base64编码
    file_type: str = "jpg"
    receipt_type: str = "增值税普通发票"
    description: str = ""


# ===== 员工管理 =====

class EmployeeCreateRequest(BaseModel):
    wecom_user_id: str | None = None  # 手动创建时可留空，自动生成
    name: str
    employee_no: str | None = None
    department: str | None = None
    department_id: int | None = None
    position: str | None = None
    mobile: str | None = None
    email: str | None = None
    status: int = 1  # 1=在职 2=离职
    password: str | None = None  # 员工端登录密码（明文，存储时哈希）


class EmployeeUpdateRequest(BaseModel):
    name: str | None = None
    employee_no: str | None = None
    department: str | None = None
    department_id: int | None = None
    position: str | None = None
    mobile: str | None = None
    email: str | None = None
    status: int | None = None
    password: str | None = None  # 设置/重置密码


class EmployeeResponse(BaseModel):
    id: int
    wecom_user_id: str
    name: str
    employee_no: str | None = None
    department: str | None = None
    department_id: int | None = None
    position: str | None = None
    mobile: str | None = None
    email: str | None = None
    has_password: bool | None = None  # 是否已设置登录密码
    status: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class EmployeeSyncResult(BaseModel):
    """企微通讯录同步结果"""
    total: int
    created: int
    updated: int
    errors: list[str] = []


# ===== 员工端认证 =====

class PortalLoginRequest(BaseModel):
    employee_no: str
    password: str


class PortalChangePasswordRequest(BaseModel):
    employee_no: str
    old_password: str
    new_password: str


# ===== NLU 结果 Schema（Step 1.2.1）=====
# re-export 自 nlu_schema.py，便于 `from app.schemas import NluResultSchema` 统一导入
from app.schemas.nlu_schema import (  # noqa: E402
    NluResultSchema,
    BatchDescribeItemSchema,
    BatchDescribeResultSchema,
)
