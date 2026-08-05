"""add nonstandard receipt fields to invoices

Revision ID: 0003_nonstandard_receipt
Revises: 0002_verify_cross_check
Create Date: 2026-08-03 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_nonstandard_receipt"
down_revision: Union[str, None] = "0002_verify_cross_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 扩展 receipt_type 枚举（PostgreSQL 需要先加值）
    # 注意：PG ENUM 存储的是 Python 枚举的 name（如 bank_statement），不是中文 value
    op.execute("ALTER TYPE receipttype ADD VALUE IF NOT EXISTS 'bank_statement'")

    # 2. 新增字段
    op.add_column(
        "invoices",
        sa.Column("is_nonstandard", sa.Boolean(), server_default="false", nullable=True, comment="是否非标准票据"),
    )
    op.add_column(
        "invoices",
        sa.Column("vlm_confidence", sa.Float(), nullable=True, comment="VLM识别置信度"),
    )
    op.add_column(
        "invoices",
        sa.Column("vlm_raw_result", sa.JSON(), nullable=True, comment="VLM完整返回结果"),
    )
    op.add_column(
        "invoices",
        sa.Column("risk_level", sa.String(10), nullable=True, comment="风险等级 low/medium/high"),
    )
    op.add_column(
        "invoices",
        sa.Column("receipt_detail", sa.JSON(), nullable=True, comment="非标票据扩展字段"),
    )
    op.add_column(
        "invoices",
        sa.Column("processing_pipeline", sa.String(20), nullable=True, comment="处理链路 standard/nonstandard"),
    )

    # 3. 回填现有数据（receipt 原为 handwritten_receipt，已改名）
    op.execute("""
        UPDATE invoices
        SET is_nonstandard = true,
            processing_pipeline = 'nonstandard'
        WHERE receipt_type IN ('receipt', 'payment_screenshot', 'bank_statement')
    """)
    op.execute("""
        UPDATE invoices
        SET processing_pipeline = 'standard'
        WHERE is_nonstandard = false OR is_nonstandard IS NULL
    """)


def downgrade() -> None:
    op.drop_column("invoices", "processing_pipeline")
    op.drop_column("invoices", "receipt_detail")
    op.drop_column("invoices", "risk_level")
    op.drop_column("invoices", "vlm_raw_result")
    op.drop_column("invoices", "vlm_confidence")
    op.drop_column("invoices", "is_nonstandard")
    # 注意：PostgreSQL 不支持 ALTER TYPE DROP VALUE，枚举值保留
