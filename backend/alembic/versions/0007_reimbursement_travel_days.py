"""add reimbursement_travel_days table + backfill from day_subsidies

Revision ID: 0007_reimbursement_travel_days
Revises: 0006_verify_settings
Create Date: 2026-08-17 12:00:00.000000

新增表：reimbursement_travel_days
数据迁移：把 reimbursement_day_subsidies 中 included=true 的行回填到 travel_days
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_reimbursement_travel_days"
down_revision = "0006_verify_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reimbursement_travel_days",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reimbursement_id", sa.Integer(), nullable=False),
        sa.Column("travel_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("weekday", sa.SmallInteger(), nullable=True),
        sa.Column("day_type", sa.String(length=16), nullable=True),
        sa.Column("base_rate", sa.Float(), nullable=True),
        sa.Column("applicant_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["reimbursement_id"], ["reimbursements.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("reimbursement_id", "travel_date", name="uq_travel_day_reimb_date"),
    )
    op.create_index(
        "ix_reimbursement_travel_days_reimbursement_id",
        "reimbursement_travel_days",
        ["reimbursement_id"],
    )

    # 数据回填：day_subsidies 中 included=true 的行 → travel_days
    op.execute(
        """
        INSERT INTO reimbursement_travel_days
            (reimbursement_id, travel_date, note, weekday, day_type, base_rate, applicant_id, created_at, updated_at)
        SELECT
            rds.reimbursement_id,
            rds.subsidy_date,
            NULL,
            rds.weekday,
            rds.day_type,
            rds.base_rate,
            r.applicant_id,
            NOW(),
            NOW()
        FROM reimbursement_day_subsidies rds
        JOIN reimbursements r ON r.id = rds.reimbursement_id
        WHERE rds.included = true
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reimbursement_travel_days_reimbursement_id",
        table_name="reimbursement_travel_days",
    )
    op.drop_table("reimbursement_travel_days")
