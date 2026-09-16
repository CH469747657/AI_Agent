"""simplify cycle config — replace pending+transition with next_cycle_end_day

Revision ID: 0022_simplify_cycle_config
Revises: 0021_verify_enabled
Create Date: 2026-09-17 00:00:00.000000

简化周期配置规则：
- 删除 pending_cycle_end_day + cycle_transition_start 字段
- 新增 next_cycle_end_day 字段（仅下个周期用，封账后切换并清空）

设计原则：
- 当前周期：跨月 26~25（如 8/26~9/25），25 日含当天
- 下个周期：只设「截止日」一个数，起点 = 上个周期截止的次日（自动算）
- 一次只设一个下个周期

例：当前 8/26~9/25，设 next_cycle_end_day=20 → 下个周期 9/26~10/20（26 天短周期）
封账后 cycle_end_day=20，next_cycle_end_day=None
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0022_simplify_cycle_config"
down_revision: Union[str, None] = "0021_verify_enabled"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新增 next_cycle_end_day
    op.add_column(
        "system_settings",
        sa.Column(
            "next_cycle_end_day",
            sa.Integer(),
            nullable=True,
            comment="下个周期截止日（仅下个周期用，封账后切换并清空）",
        ),
    )
    # 把 pending_cycle_end_day 的值迁移到 next_cycle_end_day（语义一致：都是下个周期截止日）
    op.execute(
        "UPDATE system_settings SET next_cycle_end_day = pending_cycle_end_day "
        "WHERE pending_cycle_end_day IS NOT NULL"
    )
    # 删除旧字段
    op.drop_column("system_settings", "pending_cycle_end_day")
    op.drop_column("system_settings", "cycle_transition_start")


def downgrade() -> None:
    # 恢复旧字段
    op.add_column(
        "system_settings",
        sa.Column(
            "pending_cycle_end_day",
            sa.Integer(),
            nullable=True,
            comment="下个周期起生效的 cycle_end_day",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "cycle_transition_start",
            sa.Date(),
            nullable=True,
            comment="过渡周期起点",
        ),
    )
    # 把 next_cycle_end_day 迁回 pending_cycle_end_day
    op.execute(
        "UPDATE system_settings SET pending_cycle_end_day = next_cycle_end_day "
        "WHERE next_cycle_end_day IS NOT NULL"
    )
    op.drop_column("system_settings", "next_cycle_end_day")
