"""报销单数据模型"""

import enum
from sqlalchemy import String, Text, Integer, Float, Enum, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin
from datetime import datetime


class ReimbursementStatus(str, enum.Enum):
    draft = "DRAFT"
    submitted = "SUBMITTED"
    reviewed = "REVIEWED"
    reimbursed = "REIMBURSED"


class Reimbursement(Base, TimestampMixin):
    __tablename__ = "reimbursements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    applicant_id: Mapped[str] = mapped_column(String(100), index=True, comment="申请人企微UserID")
    applicant_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    period: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="报销期间如 2026-07")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="报销事由及补充说明")
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True, comment="总金额")
    status: Mapped[ReimbursementStatus] = mapped_column(Enum(ReimbursementStatus), default=ReimbursementStatus.draft)
    excel_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    zip_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invoices: Mapped[list] = relationship("Invoice", backref="reimbursement")
    attachments: Mapped[list] = relationship("ReimbursementAttachment", backref="reimbursement", cascade="all, delete-orphan")


class ReimbursementAttachment(Base, TimestampMixin):
    """报销单附件"""

    __tablename__ = "reimbursement_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), comment="原始文件名")
    file_path: Mapped[str] = mapped_column(String(500), comment="服务器存储路径")
    file_size: Mapped[int] = mapped_column(Integer, comment="文件大小(字节)")
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="MIME类型")
