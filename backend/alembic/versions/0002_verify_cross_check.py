"""add verify_cross_check column to invoices

Revision ID: 0002_verify_cross_check
Revises: 0001_baseline
Create Date: 2026-08-01 19:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_verify_cross_check"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("verify_cross_check", sa.JSON(), nullable=True, comment="验真返回票面与OCR/LLM的差异"),
    )


def downgrade() -> None:
    op.drop_column("invoices", "verify_cross_check")
