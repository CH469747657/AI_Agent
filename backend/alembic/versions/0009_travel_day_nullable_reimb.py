"""travel_days reimbursement_id nullable + add cycle_key

Revision ID: 0009_travel_day_nullable_reimb
Revises: 0008_fix_travel_day_id_serial
Create Date: 2026-08-18 00:30:00.000000

业务规则：员工端不允许执行报销单生成操作。报销单仅由两种方式生成：
1. 封账日（每月21日）系统自动生成
2. 管理员手动提前生成

但员工可在报销单生成前标记出差日。所以 travel_days 必须支持
"未挂载到报销单"状态（reimbursement_id=NULL），等报销单生成时再批量挂载。

新增 cycle_key 字段：用于按 (applicant_id, cycle_key) 检索待挂载的 travel_days。
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_travel_day_nullable_reimb"
down_revision = "0008_fix_travel_day_id_serial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. reimbursement_id 改可空
    op.alter_column(
        "reimbursement_travel_days",
        "reimbursement_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 2. 新增 cycle_key 字段（可空，未挂载时填周期键；挂载后也保留作冗余）
    op.add_column(
        "reimbursement_travel_days",
        sa.Column("cycle_key", sa.String(length=10), nullable=True, comment="周期键 YYYY-MM"),
    )

    # 3. 回填 cycle_key：已挂载的从 reimbursements.cycle_key 拷贝
    op.execute(
        """
        UPDATE reimbursement_travel_days AS td
        SET cycle_key = r.cycle_key
        FROM reimbursements AS r
        WHERE td.reimbursement_id = r.id AND r.cycle_key IS NOT NULL
        """
    )

    # 4. 索引 (applicant_id, cycle_key) — 用于按员工+周期查待挂载 travel_days
    op.create_index(
        "ix_travel_days_applicant_cycle",
        "reimbursement_travel_days",
        ["applicant_id", "cycle_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_travel_days_applicant_cycle",
        table_name="reimbursement_travel_days",
    )
    op.drop_column("reimbursement_travel_days", "cycle_key")
    # 回滚前必须保证无 NULL reimbursement_id 行
    op.execute(
        """
        DELETE FROM reimbursement_travel_days WHERE reimbursement_id IS NULL
        """
    )
    op.alter_column(
        "reimbursement_travel_days",
        "reimbursement_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
