"""发票/票据数据模型"""

import enum
from datetime import date
from sqlalchemy import String, Text, Integer, Float, Enum, JSON, ForeignKey, Boolean, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin


class ReceiptType(str, enum.Enum):
    vat_normal = "增值税普通发票"
    vat_special = "增值税专用发票"
    train_ticket = "火车票"
    flight_ticket = "机票"
    receipt = "收据"
    payment_screenshot = "支付截图"
    bank_statement = "交易流水单"
    no_receipt = "无票"


class FeeCategory(str, enum.Enum):
    """费用大类"""
    personal = "personal"
    company = "company"


class InvoiceStatus(str, enum.Enum):
    uploaded = "UPLOADED"
    processing = "PROCESSING"
    reviewing = "REVIEWING"
    confirmed = "CONFIRMED"
    reimbursed = "REIMBURSED"
    not_reimbursed = "NOT_REIMBURSED"


class VerifyStatus(str, enum.Enum):
    pending = "PENDING"
    valid = "VALID"
    invalid = "INVALID"
    unable = "UNABLE_TO_VERIFY"


class DuplicateStatus(str, enum.Enum):
    pending = "PENDING"
    unique = "UNIQUE"
    duplicate = "DUPLICATE"


# 双源比对可对比字段
COMPARABLE_FIELDS = [
    "invoice_number", "invoice_code", "check_code",
    "issue_date", "buyer_name", "buyer_tax_id",
    "seller_name", "seller_tax_id", "item_name",
    "total_with_tax", "amount", "tax_amount", "tax_rate",
]


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id: Mapped[int | None] = mapped_column(ForeignKey("reimbursements.id"), nullable=True)

    # 基础信息
    receipt_type: Mapped[ReceiptType] = mapped_column(Enum(ReceiptType), comment="票据类型")
    file_path: Mapped[str] = mapped_column(String(500), comment="原始文件路径")
    file_type: Mapped[str] = mapped_column(String(10), comment="文件格式 pdf/jpg/png")
    user_id: Mapped[str] = mapped_column(String(100), index=True, comment="提交者企微UserID")
    user_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="用户附加描述")

    # OCR + LLM 提取的字段（双源比对后确认值）
    invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    invoice_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    check_code: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="校验码（后6位，用于在线验真）")
    issue_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    buyer_tax_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    seller_tax_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    item_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    total_with_tax: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_amount: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_rate: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # —— 报销单归集辅助字段 ——
    expense_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="费用发生日期（三级判定后回填）")
    expense_date_source: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="日期来源 note/issue_date/receipt_date/upload_time"
    )

    # 双源比对状态
    diff_confidence: Mapped[float | None] = mapped_column(Float, nullable=True, comment="双源匹配置信度")
    diff_conflicts: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="冲突字段列表")

    # 费用分类
    fee_category: Mapped[FeeCategory | None] = mapped_column(Enum(FeeCategory), nullable=True)
    fee_subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="费用子类")
    classify_source: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="分类来源 rule/llm/manual")
    classify_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 项目归属
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    project_match_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 验真查重
    verify_status: Mapped[VerifyStatus] = mapped_column(Enum(VerifyStatus), default=VerifyStatus.pending)
    duplicate_status: Mapped[DuplicateStatus] = mapped_column(Enum(DuplicateStatus), default=DuplicateStatus.pending)
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment="感知哈希值")
    verify_cross_check: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="验真返回票面与OCR/LLM的差异")
    verify_message: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="验真结果说明")

    # 非标准票据扩展字段
    is_nonstandard: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", comment="是否非标准票据")
    vlm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True, comment="VLM识别置信度")
    vlm_raw_result: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="VLM完整返回结果")
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="风险等级 low/medium/high")
    receipt_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="非标票据扩展字段(平台/支付方式等)")
    processing_pipeline: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="处理链路 standard/nonstandard")

    # 状态
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.uploaded)

    # 关系
    ocr_result: Mapped["OcrResult | None"] = relationship(back_populates="invoice", uselist=False, cascade="all, delete-orphan")
    llm_result: Mapped["LlmResult | None"] = relationship(back_populates="invoice", uselist=False, cascade="all, delete-orphan")


class OcrResult(Base):
    """OCR识别结果"""
    __tablename__ = "ocr_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extracted_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="字段提取结果")
    ocr_lines: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="原始识别行")

    invoice: Mapped["Invoice"] = relationship(back_populates="ocr_result")


class LlmResult(Base):
    """LLM解析结果"""
    __tablename__ = "llm_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extracted_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="llm_result")
