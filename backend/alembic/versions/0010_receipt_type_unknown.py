"""add ReceiptType.unknown enum value

Revision ID: 0010_receipt_type_unknown
Revises: 0009_travel_day_nullable_reimb
Create Date: 2026-08-18 12:00:00.000000

VLM 票据类型识别失败时，不再默认 vat_normal（误导用户），
改为标记 unknown，让用户/管理员在详情页修正类型。

PG ENUM 不支持事务内 ALTER TYPE ADD VALUE，需在事务外执行。
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0010_receipt_type_unknown"
down_revision: Union[str, None] = "0009_travel_day_nullable_reimb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PG ENUM 存储的是 enum.name（如 unknown），不是中文 value
    # 关键：PG 12+ 允许事务内 ALTER TYPE ADD VALUE，但新值在同事务内不可用
    # 文件顶部注释已说明"PG ENUM 不支持事务内 ALTER TYPE ADD VALUE，需在事务外执行"
    # 必须用 autocommit_block() 让 ADD VALUE 提交后才能在后续迁移中使用新值
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE receipttype ADD VALUE IF NOT EXISTS 'unknown'")


def downgrade() -> None:
    # PG 不支持 ALTER TYPE DROP VALUE，枚举值保留
    pass
