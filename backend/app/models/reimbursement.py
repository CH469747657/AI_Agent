"""报销单数据模型"""

import enum
from sqlalchemy import String, Text, Integer, Float, Numeric, Boolean, SmallInteger, Enum, ForeignKey, DateTime, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin
from datetime import datetime, date


class ReimbursementStatus(str, enum.Enum):
    draft = "DRAFT"
    submitted = "SUBMITTED"
    reviewed = "REVIEWED"


class Reimbursement(Base, TimestampMixin):
    __tablename__ = "reimbursements"
    __table_args__ = (
        UniqueConstraint("applicant_id", "cycle_key", name="uq_reimb_applicant_cycle"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    applicant_id: Mapped[str] = mapped_column(String(100), index=True, comment="申请人企微UserID")
    applicant_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    period: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="报销期间如 2026-07（兼容字段，= cycle_key）")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="报销事由及补充说明")
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True, comment="总金额=expense_total+subsidy_total")
    status: Mapped[ReimbursementStatus] = mapped_column(Enum(ReimbursementStatus), default=ReimbursementStatus.draft)
    excel_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    zip_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # —— 自然月滚动周期字段（21-20） ——
    cycle_start: Mapped[date | None] = mapped_column(Date, nullable=True, comment="周期起（上月21日）")
    cycle_end: Mapped[date | None] = mapped_column(Date, nullable=True, comment="周期末（本月20日）")
    cycle_key: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True, comment="周期标识=结束月YYYY-MM")
    expense_total: Mapped[float] = mapped_column(Float, default=0.0, comment="费用合计（凭证金额之和）")
    subsidy_total: Mapped[float] = mapped_column(Float, default=0.0, comment="补贴合计")
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否系统自动生成")
    is_cycle_locked: Mapped[bool] = mapped_column(Boolean, default=False, comment="周期封账标志")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="封账时间")

    invoices: Mapped[list] = relationship("Invoice", backref="reimbursement")
    attachments: Mapped[list] = relationship("ReimbursementAttachment", backref="reimbursement", cascade="all, delete-orphan")
    items: Mapped[list] = relationship("ReimbursementItem", backref="reimbursement", cascade="all, delete-orphan", order_by="ReimbursementItem.sort_order")
    day_subsidies: Mapped[list] = relationship("ReimbursementDaySubsidy", backref="reimbursement", cascade="all, delete-orphan", order_by="ReimbursementDaySubsidy.subsidy_date")


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


class ReimbursementItem(Base, TimestampMixin):
    """报销单明细行 — 每张凭证一行，承载费用发生日期与子类"""

    __tablename__ = "reimbursement_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True, nullable=False
    )
    invoice_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    item_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="费用发生日期")
    item_date_source: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="日期来源 note/issue_date/receipt_date/upload_time"
    )
    weekday: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="冗余星期0=周一…6=周日")
    fee_category: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="personal/company")
    fee_subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="油费/停车费/住宿/打印/高速/公司汇款/其他")
    amount: Mapped[float] = mapped_column(Float, nullable=False, comment="金额")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="内容说明")
    is_late_charge: Mapped[bool] = mapped_column(Boolean, default=False, comment="跨期标志")
    intended_cycle_key: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="原应归属周期")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序")


class ReimbursementDaySubsidy(Base, TimestampMixin):
    """报销单日补贴 — 每个有费用发生的天一行"""

    __tablename__ = "reimbursement_day_subsidies"
    __table_args__ = (
        UniqueConstraint("reimbursement_id", "subsidy_date", name="uq_day_subsidy_reimb_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subsidy_date: Mapped[date] = mapped_column(Date, nullable=False, comment="日期")
    weekday: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="0=周一…6=周日")
    day_type: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="workday/weekend/holiday")
    base_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当日标准60或80")
    subsidy_amount: Mapped[float] = mapped_column(Float, nullable=False, comment="补贴金额")
    included: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否计入合计")
    exclude_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="取消原因")
    trigger_invoice_count: Mapped[int] = mapped_column(Integer, default=0, comment="触发该天补贴的凭证数")


class ReimbursementTravelDay(Base, TimestampMixin):
    """员工标记的出差日 — 触发报销补贴核算

    与 Reimbursement 的关系：
    - reimbursement_id 可空：员工标记时报销单可能尚未生成（系统在封账日自动生成
      或管理员手动提前生成）。此时 cycle_key 填充，待报销单生成时由
      aggregation_service.get_or_create_reimbursement 批量挂载。
    - reimbursement_id 非空时：已挂载到具体报销单，参与补贴核算。

    与 ReimbursementDaySubsidy 的关系：
    - travel_days 是触发源（员工主动标记）
    - day_subsidies 是补贴计算结果（由 subsidy_engine.recompute_subsidies 生成）
    - 一个 travel_day 对应一行 day_subsidy
    """

    __tablename__ = "reimbursement_travel_days"
    __table_args__ = (
        UniqueConstraint("reimbursement_id", "travel_date", name="uq_travel_day_reimb_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True, nullable=True,
        comment="所属报销单 ID，未挂载时为 NULL",
    )
    cycle_key: Mapped[str | None] = mapped_column(
        String(10), nullable=True, index=True, comment="周期键 YYYY-MM，未挂载时用于按员工+周期检索"
    )
    travel_date: Mapped[date] = mapped_column(Date, nullable=False, comment="出差日期")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注，如北京出差/返程")
    weekday: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="0=周一…6=周日")
    day_type: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="workday/weekend/holiday")
    base_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当日标准60或80")
    applicant_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="标记人 employee_no")
