"""FastAPI 应用入口"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routers import invoices, reports, wecom, reimbursements, employees
from app.routers import portal_auth, portal, dialog
from app.routers import settings as settings_router
from app.routers import holidays

logger = logging.getLogger(__name__)


def _get_current_alembic_revision() -> str | None:
    """查询当前数据库的 Alembic 版本（同步，用于启动时判断）"""
    from sqlalchemy import create_engine, text
    from app.config import settings

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            # alembic_version 表可能不存在
            result = conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        # alembic_version 表不存在
        return None
    finally:
        engine.dispose()


def _run_alembic_upgrade_sync():
    """同步执行 Alembic 迁移到最新版本（在线程中调用，避免事件循环冲突）

    策略：
    1. 先检查当前 Alembic 版本
    2. 已在 head → 跳过
    3. 无版本记录（新库或未纳入管理）→ 尝试 upgrade head，失败则 stamp head
    4. 有中间版本 → upgrade head
    """
    from alembic.config import Config
    from alembic import command

    alembic_ini = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
    if not os.path.exists(alembic_ini):
        logger.warning("alembic.ini not found, falling back to create_all")
        return False

    # 查询 head 版本 ID
    head_revision = "0004_system_settings"

    # 先检查当前版本，避免不必要的 upgrade 尝试
    current_rev = _get_current_alembic_revision()
    if current_rev == head_revision:
        logger.info("Alembic already at head (%s), skipping migration", current_rev)
        return True

    alembic_cfg = Config(alembic_ini)

    if current_rev is not None:
        # 有中间版本，执行 upgrade
        logger.info("Alembic at %s, upgrading to head...", current_rev)
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migration completed successfully")
            return True
        except Exception as e:
            logger.warning("Alembic upgrade failed (%s), falling back to create_all", e)
            return False
    else:
        # 无版本记录——可能是新库或已有库未纳入 Alembic 管理
        logger.info("No Alembic version found, attempting upgrade head...")
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migration completed successfully (fresh database)")
            return True
        except Exception as e:
            logger.warning("Alembic upgrade failed (%s), trying stamp head...", e)
            try:
                # 已有数据库未纳入 Alembic 管理 → 标记当前版本为 head
                command.stamp(alembic_cfg, "head")
                logger.info("Alembic stamp head completed (existing schema marked as current)")
                return True
            except Exception as e2:
                logger.warning("Alembic stamp also failed (%s), falling back to create_all", e2)
                return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行数据库迁移（在线程中运行避免事件循环冲突）
    try:
        migrated = await asyncio.to_thread(_run_alembic_upgrade_sync)
    except Exception as e:
        logger.warning("Alembic upgrade failed (%s), falling back to create_all", e)
        migrated = False
    if not migrated:
        await init_db()
    # 预加载OCR模型
    from app.services.ocr_service import get_ocr_service
    get_ocr_service()  # 触发懒加载

    # 从数据库加载 LLM 配置覆写到运行时 settings
    try:
        from app.database import get_async_sessionmaker
        from app.routers.settings import load_settings_from_db
        async with get_async_sessionmaker()() as db:
            await load_settings_from_db(db)
    except Exception as e:
        logger.warning("Failed to load settings from DB: %s", e)

    # 启动定时任务调度器
    try:
        from app.services.scheduler_service import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning("Failed to start scheduler: %s", e)

    # Step 2.1.3：构建意图 embedding 索引（用于 RAG 检索）
    # 失败时不阻塞启动，retrieve 会自动降级到空列表
    try:
        from app.dialog.intent_retriever import get_intent_retriever
        retriever = get_intent_retriever()
        count = await retriever.build_index()
        logger.info("Intent retriever index built: %d intents", count)
    except Exception as e:
        logger.warning("Failed to build intent retriever index: %s", e)

    yield

    # 停止调度器
    try:
        from app.services.scheduler_service import stop_scheduler
        await stop_scheduler()
    except Exception as e:
        logger.warning("Failed to stop scheduler: %s", e)


app = FastAPI(
    title="发票报销智能助手",
    description="基于OCR+LLM双源验证的报销预审系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# 注册路由
app.include_router(invoices.router, prefix="/api/invoices", tags=["发票管理"])
app.include_router(reports.router, prefix="/api/reports", tags=["报表生成"])
app.include_router(wecom.router, prefix="/api/wecom", tags=["企业微信"])
app.include_router(reimbursements.router, prefix="/api/reimbursements", tags=["报销单管理"])
app.include_router(employees.router, prefix="/api/employees", tags=["员工管理"])
app.include_router(holidays.router, prefix="/api/holidays", tags=["节假日管理"])

# 管理端认证路由（admin 账户，与员工端 portal_auth 完全独立）
from app.routers.admin_auth import router as admin_auth_router
app.include_router(admin_auth_router, prefix="/api/admin/auth", tags=["管理端-认证"])

# 老板端认证路由（boss 账户，与管理端 admin 账户独立）
from app.routers.admin_auth import boss_router as boss_auth_router
app.include_router(boss_auth_router, prefix="/api/boss/auth", tags=["老板端-认证"])

# 员工端路由（portal）
app.include_router(portal_auth.router, prefix="/api/portal/auth", tags=["员工端-认证"])
app.include_router(portal.router, prefix="/api/portal", tags=["员工端-业务"])

# 出差日路由（员工端 + 管理端）
from app.routers.travel_days import portal_router as travel_portal_router
from app.routers.travel_days import admin_router as travel_admin_router
app.include_router(travel_portal_router, prefix="/api/portal/travel-days", tags=["员工端-出差日"])
app.include_router(travel_admin_router, prefix="/api/admin/travel-days", tags=["管理端-出差日"])

# 对话引擎路由（Phase 1 骨架）
app.include_router(dialog.router, prefix="/api/dialog", tags=["对话引擎"])

# 系统设置路由
app.include_router(settings_router.router, prefix="/api/settings", tags=["系统设置"])


@app.get("/")
async def root():
    return {"name": "发票报销智能助手", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}
