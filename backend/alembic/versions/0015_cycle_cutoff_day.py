"""add cycle_cutoff_day to system_settings

Revision ID: 0015_cycle_cutoff_day
Revises: 0014_invoice_verify_message
Create Date: 2026-09-10 14:00:00.000000

让管理员能配置报销周期 cutoff 日（1-31），替代硬编码的 21-20 制。
默认 21 与现状一致，迁移不改变现有数据归属。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_cycle_cutoff_day"
down_revision: Union[str, None] = "0014_invoice_verify_message"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS 幂等：应对"列已存在但 alembic_version 未 stamp 到 0015"的场景
    # PG15 支持 ADD COLUMN IF NOT EXISTS，但不支持 ADD CONSTRAINT IF NOT EXISTS，
    # 所以约束用 DO 块查 information_schema 判断后再加，保证幂等。
    op.execute(
        "ALTER TABLE system_settings "
        "ADD COLUMN IF NOT EXISTS cycle_cutoff_day INT NOT NULL DEFAULT 21"
    )
    # CHECK 约束限制 1-31（PG 不支持 ADD CONSTRAINT IF NOT EXISTS，用 DO 块幂等）
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS ("
        "  SELECT 1 FROM information_schema.table_constraints "
        "  WHERE table_name='system_settings' "
        "    AND constraint_name='ck_cycle_cutoff_day_range'"
        ") THEN "
        "  ALTER TABLE system_settings "
        "  ADD CONSTRAINT ck_cycle_cutoff_day_range "
        "  CHECK (cycle_cutoff_day BETWEEN 1 AND 31); "
        "END IF; "
        "END $$;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE system_settings DROP CONSTRAINT IF EXISTS ck_cycle_cutoff_day_range")
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS cycle_cutoff_day")
