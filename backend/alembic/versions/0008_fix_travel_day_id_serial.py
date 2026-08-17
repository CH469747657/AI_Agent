"""fix travel_days id serial

Revision ID: 0008_fix_travel_day_id_serial
Revises: 0007_reimbursement_travel_days
Create Date: 2026-08-17 13:00:00.000000

把 reimbursement_travel_days.id 改成 SERIAL（带自增序列）。
0007 建表时 Alembic 没有自动生成 SERIAL，导致 INSERT 不传 id 时违反 NOT NULL。
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_fix_travel_day_id_serial"
down_revision = "0007_reimbursement_travel_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建序列
    op.execute("CREATE SEQUENCE IF NOT EXISTS reimbursement_travel_days_id_seq")
    # 给 id 设 default 为 nextval
    op.execute(
        "ALTER TABLE reimbursement_travel_days "
        "ALTER COLUMN id SET DEFAULT nextval('reimbursement_travel_days_id_seq')"
    )
    # 把序列值设为当前 max(id) + 1，避免后续 INSERT 冲突
    op.execute(
        "SELECT setval('reimbursement_travel_days_id_seq', "
        "COALESCE((SELECT MAX(id) FROM reimbursement_travel_days), 0) + 1, false)"
    )
    # 让序列 OWNER 是 id 列
    op.execute(
        "ALTER SEQUENCE reimbursement_travel_days_id_seq "
        "OWNED BY reimbursement_travel_days.id"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE reimbursement_travel_days "
        "ALTER COLUMN id DROP DEFAULT"
    )
    op.execute("DROP SEQUENCE IF EXISTS reimbursement_travel_days_id_seq")
