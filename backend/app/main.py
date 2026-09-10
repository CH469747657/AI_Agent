"""FastAPI 应用入口"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routers import invoices, reports, reimbursements, employees
from app.routers import portal_auth, portal, dialog
from app.routers import settings as settings_router
from app.routers import holidays
# 企业微信 MCP 功能暂时关闭（main.py:11 注释 wecom import，main.py:166 注释 router 注册）
# 如需恢复：取消下面这行的注释，并恢复下方 app.include_router(wecom.router, ...) 行
# from app.routers import wecom

logger = logging.getLogger(__name__)


def _configure_app_logger() -> None:
    """给 app.* logger 配置 stdout handler，避免被 uvicorn dictConfig 覆盖"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        app_logger.addHandler(handler)
    app_logger.propagate = False


def _get_current_alembic_revision() -> str | None:
    """查询当前数据库的 Alembic 版本（同步，用于启动时判断）

    返回 None 表示数据库无 alembic_version 表（空库或未纳入 alembic 管理）。
    注意：此处异常静默吞掉是故意的，但调用方需根据 None 走 upgrade head。
    """
    from sqlalchemy import create_engine, text
    from app.config import settings

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None
    except Exception as e:
        # alembic_version 表不存在 — 空库或未纳入 alembic 管理
        logger.info("alembic_version table not found (likely fresh DB): %s", e)
        return None
    finally:
        engine.dispose()


def _run_alembic_upgrade_sync():
    """同步执行 Alembic 迁移到最新版本（在线程中调用，避免事件循环冲突）

    策略（修复了"表建不全+反复重启"的根因）：
    1. 动态从 alembic ScriptDirectory 获取 head revision（不再硬编码）
    2. 已在 head → 跳过
    3. 有中间版本 → upgrade head，失败则 raise（容器崩溃退出，不静默兜底）
    4. 空库（无 alembic_version 表）→ upgrade head，失败 raise

    重要：移除了原来"upgrade 失败 → stamp head"的危险兜底。
    stamp head 会把版本假性标记成 head，但表没建全，后续重启看到"已在 head"就跳过，
    永远不补建表——这就是"表建不全+反复重启"的根因。
    """
    from alembic.config import Config
    from alembic import command
    from alembic.script import ScriptDirectory

    alembic_ini = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
    if not os.path.exists(alembic_ini):
        logger.warning("alembic.ini not found, falling back to create_all")
        return False

    alembic_cfg = Config(alembic_ini)

    # 动态获取 head revision（替代原来的硬编码 "0004_system_settings"）
    head_revision = ScriptDirectory.from_config(alembic_cfg).get_current_head()
    logger.info("Alembic head revision: %s", head_revision)

    # 先检查当前版本，避免不必要的 upgrade 尝试
    current_rev = _get_current_alembic_revision()
    if current_rev == head_revision:
        logger.info("Alembic already at head (%s), skipping migration", current_rev)
        return True

    if current_rev is not None:
        # 有中间版本，执行 upgrade
        logger.info("Alembic at %s, upgrading to %s...", current_rev, head_revision)
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migration completed successfully")
            return True
        except Exception as e:
            # 失败 raise 让容器崩溃退出 — docker-compose restart 会重启，
            # 但 alembic_version 保留原中间版本（不会假性标记 head），重启后可继续 upgrade
            logger.error("Alembic upgrade failed from %s to %s: %s", current_rev, head_revision, e, exc_info=True)
            raise
    else:
        # 无版本记录——空库或未纳入 alembic 管理
        logger.info("No Alembic version found (fresh DB), attempting upgrade head...")
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migration completed successfully (fresh database)")
            return True
        except Exception as e:
            # 空库升级失败也 raise — 不再 stamp head 兜底
            logger.error("Alembic upgrade failed on fresh DB: %s", e, exc_info=True)
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 配置 app logger（避免被 uvicorn dictConfig 覆盖）
    _configure_app_logger()

    logger.info("==== Application starting ====")
    logger.info("LLM provider: %s, model: %s, base_url: %s",
                settings.llm_provider, settings.llm_model, settings.llm_base_url or "(default)")
    logger.info("Database URL: %s", settings.database_url)
    logger.info("Agent mode: enabled=%s, gray_ratio=%s",
                os.getenv("AGENT_MODE_ENABLED", "false"), os.getenv("AGENT_MODE_GRAY_RATIO", "0.0"))

    # 启动时执行数据库迁移（在线程中运行避免事件循环冲突）
    # 修复"表建不全+反复重启"：迁移失败直接 raise，容器崩溃退出由 docker-compose 重启，
    # 不再用 init_db() 兜底（create_all 不写 alembic_version，会跟 alembic 管理脱节）
    logger.info("[startup] Step 1/5: Alembic migration starting...")
    try:
        migrated = await asyncio.to_thread(_run_alembic_upgrade_sync)
        if not migrated:
            # alembic.ini 不存在等场景，用 create_all 兜底
            logger.warning("[startup] Alembic skipped, falling back to create_all")
            await init_db()
        logger.info("[startup] Step 1/5: Alembic migration done")
    except Exception as e:
        logger.error("[startup] Alembic migration FAILED, container will exit: %s", e, exc_info=True)
        raise

    # 预加载OCR模型
    logger.info("[startup] Step 2/5: Preloading OCR model...")
    from app.services.ocr_service import get_ocr_service
    get_ocr_service()  # 触发懒加载
    logger.info("[startup] Step 2/5: OCR model loaded")

    # 从数据库加载 LLM 配置覆写到运行时 settings
    logger.info("[startup] Step 3/5: Loading settings from DB...")
    try:
        from app.database import get_async_sessionmaker
        from app.routers.settings import load_settings_from_db
        async with get_async_sessionmaker()() as db:
            await load_settings_from_db(db)
        logger.info("[startup] Step 3/5: Settings loaded from DB")
    except Exception as e:
        logger.warning("[startup] Failed to load settings from DB: %s", e)

    # 启动定时任务调度器
    logger.info("[startup] Step 4/5: Starting scheduler...")
    try:
        from app.services.scheduler_service import start_scheduler
        start_scheduler()
        logger.info("[startup] Step 4/5: Scheduler started")
    except Exception as e:
        logger.warning("[startup] Failed to start scheduler: %s", e)

    # Step 2.1.3：构建意图 embedding 索引（用于 RAG 检索）
    # 失败时不阻塞启动，retrieve 会自动降级到空列表
    logger.info("[startup] Step 5/5: Building intent retriever index...")
    try:
        from app.dialog.intent_retriever import get_intent_retriever
        retriever = get_intent_retriever()
        count = await retriever.build_index()
        logger.info("[startup] Step 5/5: Intent retriever index built: %d intents", count)
    except Exception as e:
        logger.warning("[startup] Failed to build intent retriever index: %s", e)

    logger.info("==== Application startup complete ====")

    yield

    logger.info("==== Application shutting down ====")

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
# 企业微信 MCP 功能暂时关闭：注释下一行（import 已在文件顶部注释）
# 如需恢复：取消下一行注释 + 文件顶部 from app.routers import wecom 注释
# app.include_router(wecom.router, prefix="/api/wecom", tags=["企业微信"])
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
