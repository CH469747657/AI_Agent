"""add verify settings columns to system_settings

Revision ID: 0006_verify_settings
Revises: 0005_reimbursement_cycle
Create Date: 2026-08-16 12:00:00.000000

新增字段（验真 API 配置，与 LLM 配置共表）：
- verify_provider（aliyun/baidu）
- verify_api_key / verify_secret_key（百度 AI 的 AK/SK）
- aliyun_verify_appcode / aliyun_verify_appsecret（阿里云云市场 AppCode/AppSecret）

数据库无记录时，回退到 .env 默认值。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_verify_settings"
down_revision: Union[str, None] = "0005_reimbursement_cycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("system_settings", sa.Column("verify_provider", sa.String(32), server_default="aliyun", nullable=True))
    op.add_column("system_settings", sa.Column("verify_api_key", sa.String(256), server_default="", nullable=True))
    op.add_column("system_settings", sa.Column("verify_secret_key", sa.String(256), server_default="", nullable=True))
    op.add_column("system_settings", sa.Column("aliyun_verify_appcode", sa.String(256), server_default="", nullable=True))
    op.add_column("system_settings", sa.Column("aliyun_verify_appsecret", sa.String(256), server_default="", nullable=True))
    op.add_column("system_settings", sa.Column("admin_password_hash", sa.String(256), server_default="", nullable=True))


def downgrade() -> None:
    op.drop_column("system_settings", "admin_password_hash")
    op.drop_column("system_settings", "aliyun_verify_appsecret")
    op.drop_column("system_settings", "aliyun_verify_appcode")
    op.drop_column("system_settings", "verify_secret_key")
    op.drop_column("system_settings", "verify_api_key")
    op.drop_column("system_settings", "verify_provider")
