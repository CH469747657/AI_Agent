"""add verify_enabled

Revision ID: 0021_verify_enabled
Revises: 0020_cycle_transition_start
Create Date: 2026-09-17 00:00:00.000000

添加 verify_enabled 字段：
- True（默认）: 开启发票验真，发票必须验真通过才能归集到报销单
- False: 关闭发票验真，忽略验真状态，发票可正常上传归集
场景：验真账户欠费时关闭开关，发票可正常走报销流程，由管理员人工审核
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0021_verify_enabled"
down_revision: Union[str, None] = "0020_cycle_transition_start"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "verify_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="是否开启发票验真（True=开启，False=关闭忽略验真）",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "verify_enabled")
