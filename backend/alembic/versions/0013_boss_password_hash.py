"""add boss_password_hash to system_settings

Revision ID: 0013_boss_password_hash
Revises: 0012_remove_reimbursed_status
Create Date: 2026-08-21 00:00:00.000000

老板端改密功能：system_settings 加 boss_password_hash 列，
为空时回退到 .env 的 BOSS_PASSWORD_HASH。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_boss_password_hash"
down_revision: Union[str, None] = "0012_remove_reimbursed_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("boss_password_hash", sa.String(256), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "boss_password_hash")
