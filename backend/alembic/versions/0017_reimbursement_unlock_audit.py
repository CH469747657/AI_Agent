"""add unlock audit fields to reimbursements

Revision ID: 0017_reimbursement_unlock_audit
Revises: 0016_rename_cycle_end_day
Create Date: 2026-09-12 01:00:00.000000

管理员手动 unlock 报销单的审计字段：
- unlocked_by: 解锁的管理员用户名
- unlocked_at: 解锁时间
- unlock_reason: 解锁原因

管理员重新 lock 时清空这 3 个字段。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_reimbursement_unlock_audit"
down_revision: Union[str, None] = "0016_rename_cycle_end_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reimbursements",
        sa.Column(
            "unlocked_by",
            sa.String(100),
            nullable=True,
            comment="解锁的管理员用户名",
        ),
    )
    op.add_column(
        "reimbursements",
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="解锁时间",
        ),
    )
    op.add_column(
        "reimbursements",
        sa.Column(
            "unlock_reason",
            sa.Text(),
            nullable=True,
            comment="解锁原因",
        ),
    )


def downgrade() -> None:
    op.drop_column("reimbursements", "unlock_reason")
    op.drop_column("reimbursements", "unlocked_at")
    op.drop_column("reimbursements", "unlocked_by")
