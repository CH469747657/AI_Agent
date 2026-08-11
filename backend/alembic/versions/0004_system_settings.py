"""add system_settings table

Revision ID: 0004_system_settings
Revises: 0003_nonstandard_receipt
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_system_settings"
down_revision: Union[str, None] = "0003_nonstandard_receipt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("llm_provider", sa.String(32), server_default="qwen", nullable=True),
        sa.Column("llm_api_key", sa.String(256), server_default="", nullable=True),
        sa.Column("llm_model", sa.String(128), server_default="qwen3-vl-plus", nullable=True),
        sa.Column("llm_text_model", sa.String(128), server_default="", nullable=True),
        sa.Column("llm_base_url", sa.String(512), server_default="", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
