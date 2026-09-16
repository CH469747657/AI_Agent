"""add cycle_transition_start

Revision ID: 0020_cycle_transition_start
Revises: 0019_pending_cycle_end_day
Create Date: 2026-09-16 12:00:00.000000

设计原则：方案A 消除周期切换时的日期重叠/真空期。
- cycle_transition_start: pending 切换后的下个周期用此日期作为起点
- 该周期封账后清空，后续周期恢复正常公式（end+1day-1月）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0020_cycle_transition_start"
down_revision: Union[str, None] = "0019_pending_cycle_end_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "cycle_transition_start",
            sa.Date(),
            nullable=True,
            comment="过渡周期起点（仅 pending 切换后的下个周期用）；该周期封账后清空",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "cycle_transition_start")
