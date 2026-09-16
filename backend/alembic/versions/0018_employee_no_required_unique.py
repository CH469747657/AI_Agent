"""employee_no required + unique

Revision ID: 0018_employee_no_required_unique
Revises: 0017_reimbursement_unlock_audit
Create Date: 2026-09-16 09:00:00.000000

工号是员工登录账号，必须非空且唯一：
- 改 employee_no 列为 NOT NULL
- 加 UNIQUE 约束（uq_employees_employee_no）

前置数据校验：现有数据无 NULL employee_no（已验证 3 条员工均有工号，0 重复）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0018_employee_no_required_unique"
down_revision: Union[str, None] = "0017_reimbursement_unlock_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 清理潜在 NULL employee_no 行（防御性：把 NULL 改成占位值，避免 NOT NULL 失败）
    op.execute("""
        UPDATE employees SET employee_no = 'EMP_' || id::text
        WHERE employee_no IS NULL OR employee_no = ''
    """)

    # 2. 改列定义：NOT NULL
    op.alter_column(
        "employees",
        "employee_no",
        existing_type=sa.String(),
        nullable=False,
    )

    # 3. 加 UNIQUE 约束
    op.create_unique_constraint(
        "uq_employees_employee_no",
        "employees",
        ["employee_no"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_employees_employee_no", "employees", type_="unique")
    op.alter_column(
        "employees",
        "employee_no",
        existing_type=sa.String(),
        nullable=True,
    )
