"""add invoices.verify_message column

Revision ID: 0014_invoice_verify_message
Revises: 0013_boss_password_hash
Create Date: 2026-08-25 00:00:00.000000

修复部署遗漏：model Invoice.verify_message 在所有迁移中都没建，
本地 dev 库靠 init_db() 的 create_all 兜底补上，生产部署 alembic 成功
不跑 create_all，导致列缺失，发票列表查询报 UndefinedColumnError。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_invoice_verify_message"
down_revision: Union[str, None] = "0013_boss_password_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等：用 IF NOT EXISTS 应对"列已存在但 alembic_version 未 stamp 到 0014"的场景
    # （本地 dev 库靠 init_db() 的 create_all 兜底补过 verify_message，但 alembic_version 仍是 0013）
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS verify_message VARCHAR(500)"
    )
    # 补 comment（IF NOT EXISTS 时 comment 不会重复加）
    op.execute(
        "COMMENT ON COLUMN invoices.verify_message IS '验真结果说明'"
    )


def downgrade() -> None:
    op.drop_column("invoices", "verify_message")
