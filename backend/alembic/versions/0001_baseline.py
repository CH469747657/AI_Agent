"""baseline: 现有 schema 快照

把当前数据库表结构作为首条迁移。对已有库执行时需配合 --sql 离线生成
或在 init_db() 中跳过 create_all，改为 `alembic upgrade head`。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-01 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === projects ===
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("member_ids", sa.JSON(), nullable=True),
        sa.Column("supplier_names", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="projectstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # === employees ===
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("wecom_user_id", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("employee_no", sa.String(50), nullable=True),
        sa.Column("department", sa.String(200), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.String(100), nullable=True),
        sa.Column("mobile", sa.String(20), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("password_hash", sa.String(200), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("1", "2", name="employeestatus"),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_employees_employee_no", "employees", ["employee_no"])
    op.create_index("ix_employees_wecom_user_id", "employees", ["wecom_user_id"])

    # === reimbursements ===
    op.create_table(
        "reimbursements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("applicant_id", sa.String(100), nullable=False),
        sa.Column("applicant_name", sa.String(100), nullable=True),
        sa.Column("department", sa.String(200), nullable=True),
        sa.Column("period", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "SUBMITTED", "REVIEWED", "REIMBURSED", name="reimbursementstatus"),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("excel_path", sa.String(500), nullable=True),
        sa.Column("pdf_path", sa.String(500), nullable=True),
        sa.Column("zip_path", sa.String(500), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reimbursements_applicant_id", "reimbursements", ["applicant_id"])

    # === invoices ===
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "reimbursement_id",
            sa.Integer(),
            sa.ForeignKey("reimbursements.id"),
            nullable=True,
        ),
        sa.Column(
            "receipt_type",
            sa.Enum(
                "vat_normal", "vat_special", "train_ticket", "flight_ticket",
                "receipt", "payment_screenshot", "no_receipt",
                name="receipttype",
            ),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("user_description", sa.Text(), nullable=True),
        sa.Column("invoice_number", sa.String(50), nullable=True),
        sa.Column("invoice_code", sa.String(50), nullable=True),
        sa.Column("check_code", sa.String(20), nullable=True),
        sa.Column("issue_date", sa.String(20), nullable=True),
        sa.Column("buyer_name", sa.String(200), nullable=True),
        sa.Column("buyer_tax_id", sa.String(30), nullable=True),
        sa.Column("seller_name", sa.String(200), nullable=True),
        sa.Column("seller_tax_id", sa.String(30), nullable=True),
        sa.Column("item_name", sa.String(500), nullable=True),
        sa.Column("total_with_tax", sa.String(20), nullable=True),
        sa.Column("amount", sa.String(20), nullable=True),
        sa.Column("tax_amount", sa.String(20), nullable=True),
        sa.Column("tax_rate", sa.String(10), nullable=True),
        sa.Column("diff_confidence", sa.Float(), nullable=True),
        sa.Column("diff_conflicts", sa.JSON(), nullable=True),
        sa.Column(
            "fee_category",
            sa.Enum("personal", "company", name="feecategory"),
            nullable=True,
        ),
        sa.Column("fee_subcategory", sa.String(100), nullable=True),
        sa.Column("classify_source", sa.String(20), nullable=True),
        sa.Column("classify_confidence", sa.Float(), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("project_match_source", sa.String(20), nullable=True),
        sa.Column(
            "verify_status",
            sa.Enum("PENDING", "VALID", "INVALID", "UNABLE_TO_VERIFY", name="verifystatus"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "duplicate_status",
            sa.Enum("PENDING", "UNIQUE", "DUPLICATE", name="duplicatestatus"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("image_hash", sa.String(64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED", "PROCESSING", "REVIEWING", "CONFIRMED",
                "REIMBURSED", "NOT_REIMBURSED",
                name="invoicestatus",
            ),
            nullable=False,
            server_default="UPLOADED",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_invoices_user_id", "invoices", ["user_id"])
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"])
    op.create_index("ix_invoices_image_hash", "invoices", ["image_hash"])
    op.create_index("ix_invoices_reimbursement_id", "invoices", ["reimbursement_id"])

    # === ocr_results ===
    op.create_table(
        "ocr_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extracted_fields", sa.JSON(), nullable=True),
        sa.Column("ocr_lines", sa.JSON(), nullable=True),
    )
    op.create_index("ix_ocr_results_invoice_id", "ocr_results", ["invoice_id"])

    # === llm_results ===
    op.create_table(
        "llm_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("extracted_fields", sa.JSON(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
    )
    op.create_index("ix_llm_results_invoice_id", "llm_results", ["invoice_id"])

    # === reimbursement_attachments ===
    op.create_table(
        "reimbursement_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "reimbursement_id",
            sa.Integer(),
            sa.ForeignKey("reimbursements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_reimbursement_attachments_reimbursement_id",
        "reimbursement_attachments",
        ["reimbursement_id"],
    )


def downgrade() -> None:
    op.drop_table("reimbursement_attachments")
    op.drop_table("llm_results")
    op.drop_table("ocr_results")
    op.drop_index("ix_invoices_reimbursement_id", table_name="invoices")
    op.drop_index("ix_invoices_image_hash", table_name="invoices")
    op.drop_index("ix_invoices_invoice_number", table_name="invoices")
    op.drop_index("ix_invoices_user_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_reimbursements_applicant_id", table_name="reimbursements")
    op.drop_table("reimbursements")
    op.drop_index("ix_employees_wecom_user_id", table_name="employees")
    op.drop_index("ix_employees_employee_no", table_name="employees")
    op.drop_table("employees")
    op.drop_table("projects")
