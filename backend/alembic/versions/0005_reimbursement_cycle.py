"""add reimbursement cycle fields, items, day_subsidies, holidays, invoice expense_date

Revision ID: 0005_reimbursement_cycle
Revises: 0004_system_settings
Create Date: 2026-08-09 11:00:00.000000

核心变更：
1. reimbursements 增量字段：cycle_start/cycle_end/cycle_key/expense_total/subsidy_total/
   auto_generated/is_cycle_locked/locked_at + UNIQUE(applicant_id, cycle_key)
2. invoices 增量字段：expense_date/expense_date_source
3. 新增表：reimbursement_items（明细行）
4. 新增表：reimbursement_day_subsidies（日补贴）
5. 新增表：holidays（节假日维护）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_reimbursement_cycle"
down_revision: Union[str, None] = "0004_system_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. reimbursements 增量字段
    op.add_column("reimbursements", sa.Column("cycle_start", sa.Date(), nullable=True, comment="周期起（上月21日）"))
    op.add_column("reimbursements", sa.Column("cycle_end", sa.Date(), nullable=True, comment="周期末（本月20日）"))
    op.add_column("reimbursements", sa.Column("cycle_key", sa.String(10), nullable=True, comment="周期标识=结束月YYYY-MM"))
    op.add_column("reimbursements", sa.Column("expense_total", sa.Float(), server_default="0", nullable=True, comment="费用合计"))
    op.add_column("reimbursements", sa.Column("subsidy_total", sa.Float(), server_default="0", nullable=True, comment="补贴合计"))
    op.add_column("reimbursements", sa.Column("auto_generated", sa.Boolean(), server_default="false", nullable=True, comment="是否系统自动生成"))
    op.add_column("reimbursements", sa.Column("is_cycle_locked", sa.Boolean(), server_default="false", nullable=True, comment="周期封账标志"))
    op.add_column("reimbursements", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True, comment="封账时间"))

    op.create_index("ix_reimbursements_cycle_key", "reimbursements", ["cycle_key"])
    op.create_unique_constraint("uq_reimb_applicant_cycle", "reimbursements", ["applicant_id", "cycle_key"])

    # 回填历史报销单的 cycle_key（用 period 字段值派生）
    op.execute("""
        UPDATE reimbursements
        SET cycle_key = period,
            cycle_start = (period || '-01')::date - INTERVAL '1 month' + INTERVAL '20 days',
            cycle_end = (period || '-20')::date,
            expense_total = COALESCE(total_amount, 0),
            subsidy_total = 0
        WHERE period IS NOT NULL AND cycle_key IS NULL
    """)

    # 2. invoices 增量字段
    op.add_column("invoices", sa.Column("expense_date", sa.Date(), nullable=True, comment="费用发生日期（三级判定后回填）"))
    op.add_column("invoices", sa.Column("expense_date_source", sa.String(20), nullable=True, comment="日期来源 note/issue_date/receipt_date/upload_time"))

    # 3. 新增 reimbursement_items 明细行表
    op.create_table(
        "reimbursement_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("reimbursement_id", sa.Integer(), sa.ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("item_date", sa.Date(), nullable=True, comment="费用发生日期"),
        sa.Column("item_date_source", sa.String(20), nullable=True, comment="日期来源 note/issue_date/receipt_date/upload_time"),
        sa.Column("weekday", sa.SmallInteger(), nullable=True, comment="0=周一…6=周日"),
        sa.Column("fee_category", sa.String(20), nullable=True, comment="personal/company"),
        sa.Column("fee_subcategory", sa.String(100), nullable=True, comment="费用子类"),
        sa.Column("amount", sa.Float(), nullable=False, comment="金额"),
        sa.Column("description", sa.Text(), nullable=True, comment="内容说明"),
        sa.Column("is_late_charge", sa.Boolean(), server_default="false", nullable=True, comment="跨期标志"),
        sa.Column("intended_cycle_key", sa.String(10), nullable=True, comment="原应归属周期"),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=True, comment="排序"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )

    # 4. 新增 reimbursement_day_subsidies 日补贴表
    op.create_table(
        "reimbursement_day_subsidies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("reimbursement_id", sa.Integer(), sa.ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("subsidy_date", sa.Date(), nullable=False, comment="日期"),
        sa.Column("weekday", sa.SmallInteger(), nullable=True, comment="0=周一…6=周日"),
        sa.Column("day_type", sa.String(16), nullable=True, comment="workday/weekend/holiday"),
        sa.Column("base_rate", sa.Float(), nullable=True, comment="当日标准60或80"),
        sa.Column("subsidy_amount", sa.Float(), nullable=False, comment="补贴金额"),
        sa.Column("included", sa.Boolean(), server_default="true", nullable=True, comment="是否计入合计"),
        sa.Column("exclude_reason", sa.Text(), nullable=True, comment="取消原因"),
        sa.Column("trigger_invoice_count", sa.Integer(), server_default="0", nullable=True, comment="触发该天补贴的凭证数"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("reimbursement_id", "subsidy_date", name="uq_day_subsidy_reimb_date"),
    )

    # 5. 新增 holidays 节假日维护表
    op.create_table(
        "holidays",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("holiday_date", sa.Date(), nullable=False, comment="日期"),
        sa.Column("holiday_name", sa.String(50), nullable=True, comment="元旦/春节/国庆…"),
        sa.Column("day_type", sa.String(16), nullable=False, comment="holiday=放假, workday=调休补班"),
        sa.Column("year", sa.SmallInteger(), nullable=True, comment="年份"),
        sa.Column("source", sa.String(20), nullable=True, comment="manual/cn_calendar_sync"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("holiday_date", name="uq_holiday_date"),
    )


def downgrade() -> None:
    op.drop_table("holidays")
    op.drop_table("reimbursement_day_subsidies")
    op.drop_table("reimbursement_items")

    op.drop_column("invoices", "expense_date_source")
    op.drop_column("invoices", "expense_date")

    op.drop_constraint("uq_reimb_applicant_cycle", "reimbursements", type_="unique")
    op.drop_index("ix_reimbursements_cycle_key", table_name="reimbursements")
    op.drop_column("reimbursements", "locked_at")
    op.drop_column("reimbursements", "is_cycle_locked")
    op.drop_column("reimbursements", "auto_generated")
    op.drop_column("reimbursements", "subsidy_total")
    op.drop_column("reimbursements", "expense_total")
    op.drop_column("reimbursements", "cycle_key")
    op.drop_column("reimbursements", "cycle_end")
    op.drop_column("reimbursements", "cycle_start")
