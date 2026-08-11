"""Alembic 环境配置（异步 + 从 app.config 读取 URL）"""

import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 让 alembic 能 import 到 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import invoice, project, reimbursement, employee  # noqa: E402, F401
from app.models import settings as _settings_model  # noqa: E402, F401  (避免覆盖 config.settings)

config = context.config
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # logging 配置不是关键路径，跳过即可
        pass

target_metadata = Base.metadata


def get_url() -> str:
    """从 app.config 读取 async URL，转为同步驱动 URL 供 Alembic 使用"""
    url = settings.database_url
    # postgresql+asyncpg://... → postgresql+psycopg2://...
    return url.replace("+asyncpg", "+psycopg2")


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接 DB"""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """在线模式：用异步引擎连接 DB（与生产环境一致）"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # SQLAlchemy 2.0 异步连接不会自动 commit，
        # 必须显式提交，否则 alembic_version 表和迁移结果会被回滚
        await connection.commit()

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
