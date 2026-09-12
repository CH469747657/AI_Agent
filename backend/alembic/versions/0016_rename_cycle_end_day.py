"""rename cycle_cutoff_day to cycle_end_day and recompute existing reimbursements

Revision ID: 0016_rename_cycle_end_day
Revises: 0015_cycle_cutoff_day
Create Date: 2026-09-12 00:00:00.000000

字段重命名 + 语义变更：
- cycle_cutoff_day (cutoff=21 表示 21 号属下月) → cycle_end_day (end=20 表示 20 号是本月最后一天)
- 默认值从 21 改为 20（保持「21-20 制」语义：21 号属下月，20 号属本月最后一天）
- 现有 reimbursements.cycle_start / cycle_end 按新语义重算

cycle_key 不变（仍是 YYYY-MM 结束月格式），只重算起止日期。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_rename_cycle_end_day"
down_revision: Union[str, None] = "0015_cycle_cutoff_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 重命名列（PG 自动保留 default 和 CHECK 约束，但约束名不变，需手动重命名）
    op.execute("ALTER TABLE system_settings RENAME COLUMN cycle_cutoff_day TO cycle_end_day")
    # 重命名 CHECK 约束（0015 创建时叫 ck_cycle_cutoff_day_range）
    op.execute(
        "ALTER TABLE system_settings "
        "RENAME CONSTRAINT ck_cycle_cutoff_day_range TO ck_cycle_end_day_range"
    )

    # 2. 修改默认值从 21 改为 20（保持 21-20 制语义）
    op.execute("ALTER TABLE system_settings ALTER COLUMN cycle_end_day SET DEFAULT 20")
    # 把现有行（如果 cycle_end_day 是 21）改为 20
    op.execute("UPDATE system_settings SET cycle_end_day = 20 WHERE cycle_end_day = 21")

    # 3. 重算现有 reimbursements.cycle_start / cycle_end 按新语义
    #    cycle_key 不变（YYYY-MM 结束月），只重算起止日期
    #    新语义：cycle_end_day 是本月最后一天（含），周期起 = 上月 (cycle_end_day+1) 日
    op.execute("""
        UPDATE reimbursements r
        SET
            cycle_start = (r.cycle_key::text || '-01')::date
                           - make_interval(months => 1)
                           + make_interval(days => s.cycle_end_day),
            cycle_end = (r.cycle_key::text || '-01')::date
                        + make_interval(days => s.cycle_end_day - 1)
        FROM system_settings s
        WHERE s.id = 1 AND r.cycle_key IS NOT NULL
    """)


def downgrade() -> None:
    # 回滚：把默认值改回 21，重命名列回 cycle_cutoff_day
    op.execute("ALTER TABLE system_settings ALTER COLUMN cycle_end_day SET DEFAULT 21")
    op.execute(
        "ALTER TABLE system_settings "
        "RENAME CONSTRAINT ck_cycle_end_day_range TO ck_cycle_cutoff_day_range"
    )
    op.execute("ALTER TABLE system_settings RENAME COLUMN cycle_end_day TO cycle_cutoff_day")
    # 注意：downgrade 不重算 reimbursements.cycle_start/cycle_end（无法完美回滚，保留新语义）
