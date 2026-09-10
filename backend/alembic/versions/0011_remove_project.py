"""remove project module (projects table + invoices.project_id columns)

Revision ID: 0011_remove_project
Revises: 0010_receipt_type_unknown
Create Date: 2026-08-19 12:00:00.000000

业务不再涉及"项目归属"概念，移除：
- invoices.project_id（FK → projects.id）
- invoices.project_match_source
- projects 表
- projectstatus ENUM 类型
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_remove_project"
down_revision: Union[str, None] = "0010_receipt_type_unknown"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先删 invoices 表上的外键约束（PG 自动生成的命名，约定 invoices_project_id_fkey）
    op.drop_constraint("invoices_project_id_fkey", "invoices", type_="foreignkey")
    # 再删两列
    op.drop_column("invoices", "project_id")
    op.drop_column("invoices", "project_match_source")
    # 删 projects 表
    op.drop_table("projects")
    # 删 projectstatus ENUM 类型
    op.execute("DROP TYPE IF EXISTS projectstatus")


def downgrade() -> None:
    # 重建 projectstatus ENUM
    op.execute(
        "CREATE TYPE projectstatus AS ENUM ('active', 'archived')"
    )
    # 重建 projects 表
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("member_ids", sa.JSON(), nullable=True),
        sa.Column("supplier_names", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="projectstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # 重建 invoices 两列
    op.add_column(
        "invoices",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("project_match_source", sa.String(20), nullable=True),
    )
