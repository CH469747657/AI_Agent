"""remove reimbursed status from reimbursement/invoice state machines

Revision ID: 0012_remove_reimbursed_status
Revises: 0011_remove_project
Create Date: 2026-08-20 12:00:00.000000

状态机重构：
- 报销单：删除 REIMBURSED 状态，REVIEWED 成为终态
- 发票：CONFIRMED→REVIEWED（更名"已审核"），新增 REJECTED（"审核不通过"），
  删除 REIMBURSED/NOT_REIMBURSED

数据迁移：
- 报销单 REIMBURSED → REVIEWED（审核通过语义）
- 发票 CONFIRMED/REIMBURSED → REVIEWED
- 发票 NOT_REIMBURSED → REJECTED

PostgreSQL ENUM 不支持 DROP VALUE，需重建类型。
顺序：ADD VALUE（事务外）→ 迁数据 → 重建类型。
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0012_remove_reimbursed_status"
down_revision: Union[str, None] = "0011_remove_project"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. ADD VALUE（PG ENUM ADD VALUE 需在事务外执行，且新增值必须提交后才能在后续 SQL 中使用）
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE invoicestatus ADD VALUE IF NOT EXISTS 'reviewed'")
        op.execute("ALTER TYPE invoicestatus ADD VALUE IF NOT EXISTS 'rejected'")
        op.execute("ALTER TYPE reimbursementstatus ADD VALUE IF NOT EXISTS 'reviewed'")

    # 2. 数据迁移
    # 关键：cast 到 text 绕过 PG enum 严格类型检查
    # 空库的 invoicestatus/reimbursementstatus 类型可能根本不含旧值（confirmed/reimbursed/not_reimbursed），
    # 直接 `WHERE status IN ('confirmed',...)` 会因引用不存在的 enum 值报错
    # cast 到 text 后，空库匹配不到任何行，UPDATE 是 no-op，不报错
    # 注意：SET 的小写值 'reviewed'/'rejected' 已在第 1 步 ADD VALUE 加入，所以 SET 不会失败
    op.execute("UPDATE invoices SET status='reviewed' WHERE status::text IN ('confirmed','reimbursed')")
    op.execute("UPDATE invoices SET status='rejected' WHERE status::text='not_reimbursed'")
    op.execute("UPDATE reimbursements SET status='reviewed' WHERE status::text='reimbursed'")

    # 3. 重建 invoicestatus 类型（去 confirmed/reimbursed/not_reimbursed）
    # 关键：baseline 的 invoices.status server_default='UPLOADED'（大写）
    # 直接 ALTER TYPE 到只含小写值的新类型，PG 试图把 server_default 字面量 cast 到新 enum 失败
    # 必须先 DROP server_default，ALTER TYPE，再 SET 新的小写 server_default
    op.execute("ALTER TABLE invoices ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "CREATE TYPE invoicestatus_new AS ENUM('uploaded','processing','reviewing','reviewed','rejected')"
    )
    op.execute(
        "ALTER TABLE invoices ALTER COLUMN status TYPE invoicestatus_new "
        "USING status::text::invoicestatus_new"
    )
    op.execute("DROP TYPE invoicestatus")
    op.execute("ALTER TYPE invoicestatus_new RENAME TO invoicestatus")
    op.execute("ALTER TABLE invoices ALTER COLUMN status SET DEFAULT 'uploaded'")

    # 4. 重建 reimbursementstatus 类型（去 reimbursed）
    # 同上：先 DROP DEFAULT，ALTER TYPE，再 SET 新 DEFAULT（小写）
    op.execute("ALTER TABLE reimbursements ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "CREATE TYPE reimbursementstatus_new AS ENUM('draft','submitted','reviewed')"
    )
    op.execute(
        "ALTER TABLE reimbursements ALTER COLUMN status TYPE reimbursementstatus_new "
        "USING status::text::reimbursementstatus_new"
    )
    op.execute("DROP TYPE reimbursementstatus")
    op.execute("ALTER TYPE reimbursementstatus_new RENAME TO reimbursementstatus")
    op.execute("ALTER TABLE reimbursements ALTER COLUMN status SET DEFAULT 'draft'")


def downgrade() -> None:
    # 不可逆：无法恢复 REIMBURSED/NOT_REIMBURSED 的业务语义
    pass
