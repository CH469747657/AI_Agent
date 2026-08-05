"""数据库连接管理"""

from functools import lru_cache
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_engine():
    """懒加载 engine — 避免模块导入即触发驱动加载"""
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_async_sessionmaker():
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """依赖注入：每个请求一个 session，异常时回滚防止脏 session 归还连接池"""
    async with get_async_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """初始化数据库表

    生产环境推荐用 Alembic: `alembic upgrade head`
    此处保留 create_all 作为开发环境首次启动的兜底，
    避免未配置 Alembic 时表不存在导致启动失败。
    """
    async with get_engine().begin() as conn:
        from app.models import invoice, project, reimbursement, employee  # noqa
        await conn.run_sync(Base.metadata.create_all)

