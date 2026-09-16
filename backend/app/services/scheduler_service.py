"""定时任务调度服务

使用 APScheduler AsyncIOScheduler 在 FastAPI lifespan 中启动/停止。
当前注册的任务：
- cycle_lock_job: 每月 cycle_end_day 日 00:00 归集游离发票 + 封账上一周期 + 自动生成报表
- timeout_reminder_job: 每 2 分钟检查超时用户并主动推送提醒
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pytz import timezone as tz

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# 超时提醒阈值（秒）— 用户处于 WAITING_PURPOSE 超过此时间后触发提醒
PURPOSE_TIMEOUT_SECONDS = 300  # 5 分钟


async def _cycle_lock_job() -> None:
    """定时归集 + 封账 + 自动生成报表任务

    每月 (cycle_end_day + 1) 日 00:00 执行（次日触发，让员工能用满周期最后一天）：
    1. 归集所有游离发票到对应周期报销单
    2. 封账刚结束的周期（用昨日所属周期 cycle_key）
    3. 对已封账的报销单自动生成报表三件套（Excel + PDF + ZIP）
    4. 清理过渡周期 transition_start（若刚封账的是过渡周期）
    5. 应用 pending_cycle_end_day（下个周期生效机制）+ 设置新 transition_start
    """
    from app.database import get_async_sessionmaker
    from app.services.aggregation_service import aggregate_pending_invoices
    from app.services.cycle_lock_service import lock_just_ended_cycle
    from app.services.cycle_end_service import get_cycle_end_day, get_cycle_transition_start

    logger.info("Cycle lock job triggered at %s", datetime.now().isoformat())
    try:
        sm = get_async_sessionmaker()
        async with sm() as db:
            # 读最新 cycle_end_day + transition_start 配置
            cycle_end_day = await get_cycle_end_day(db)
            transition_start = await get_cycle_transition_start(db)

            # 1. 先归集所有游离发票
            agg_result = await aggregate_pending_invoices(db, cycle_end_day=cycle_end_day)
            logger.info("Pre-lock aggregation: %s", agg_result)

            # 2. 再封账刚结束的周期（用今日作 on_date，让 just_ended_cycle_key 算昨日所属周期）
            from datetime import date as _date
            today = _date.today()
            lock_result = await lock_just_ended_cycle(db, cycle_end_day=cycle_end_day, on_date=today)
            logger.info("Cycle lock job result: %s", lock_result)

            # 3. 封账后自动生成报表三件套（Excel + PDF + ZIP）
            if lock_result and lock_result.get("locked_count", 0) > 0:
                await _generate_reports_for_locked_cycles(db, lock_result)

            # 4. 为归集涉及的报销单生成报表（历史周期未封账也生成，让用户能查看）
            agg_reimb_ids = agg_result.get("reimb_ids", []) if agg_result else []
            if agg_reimb_ids:
                await _generate_reports_for_ids(db, agg_reimb_ids)

            # 5. 清理刚封账周期的 transition_start（若它是过渡周期）
            if transition_start is not None:
                await _clear_transition_start(db)
                logger.info(
                    "Transition cycle locked (was %s), cleared cycle_transition_start",
                    transition_start.isoformat()
                )

            # 6. 应用 pending_cycle_end_day（下个周期生效机制）+ 设置新 transition_start
            # 封账刚结束的周期已锁定，下个周期开始；此时切换 cycle_end_day
            # 让新周期立即按新配置算，同时 reschedule_job 用新值
            # 方案A：设置 transition_start=今天（封账日 = 新周期第一天），消除日期重叠/真空
            await _apply_pending_cycle_end_day(db)
    except Exception:
        logger.exception("Cycle lock job failed")


async def _clear_transition_start(db) -> None:
    """清理过渡周期 transition_start（刚封账的过渡周期已结束，后续周期恢复正常公式）"""
    from app.models.settings import SystemSettings
    from sqlalchemy import select, update

    row = (
        await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    ).scalar_one_or_none()
    if not row or row.cycle_transition_start is None:
        return

    await db.execute(
        update(SystemSettings)
        .where(SystemSettings.id == 1)
        .values(cycle_transition_start=None)
    )
    await db.commit()
    from app.services.cycle_end_service import invalidate_cache
    invalidate_cache()
    logger.info("Cleared cycle_transition_start (transitional cycle locked, normal formula resumes)")


async def _apply_pending_cycle_end_day(db) -> None:
    """若 pending_cycle_end_day 不为 None 且 ≠ 当前 cycle_end_day，切换 + 重新调度 cron

    设计原则：管理员修改的是下个周期的截止日。封账刚完成的时刻切到新值，
    新周期立即按新配置算 cycle_key 和周期范围。

    方案A 过渡周期：切换 cycle_end_day 时，同时设置 cycle_transition_start=今天
    （封账日 = 新周期第一天），让新周期用此日期作起点，而非公式（end+1day-1月）。
    消除 cycle_end_day 变更时新周期与旧周期的日期重叠/真空期。
    """
    from app.models.settings import SystemSettings
    from sqlalchemy import select
    from app.services.cycle_end_service import invalidate_cache
    from datetime import date

    row = (
        await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    ).scalar_one_or_none()
    if not row:
        return

    pending = row.pending_cycle_end_day
    if pending is None or pending == row.cycle_end_day:
        return  # 无待生效值或与当前一致

    old = row.cycle_end_day
    today = date.today()
    row.cycle_end_day = pending
    row.pending_cycle_end_day = None
    row.cycle_transition_start = today  # 方案A：新周期用今天作起点，消除重叠/真空
    await db.commit()
    invalidate_cache()  # 失效 cycle_end_service 缓存
    logger.info(
        f"Cycle end_day switched: {old} → {pending} (pending cleared, "
        f"transition_start={today.isoformat()}, next cycle uses new value with transitional start)"
    )
    # 触发 cron 重新调度（用新 cycle_end_day 算 day=next）
    try:
        reschedule_cycle_lock_job()
    except Exception as e:
        logger.warning(f"reschedule_cycle_lock_job failed after pending apply: {e}")


async def _generate_reports_for_ids(db, reimb_ids: list[int]) -> None:
    """为指定报销单生成报表三件套（归集后调用，不要求封账）"""
    from app.models.reimbursement import Reimbursement
    from app.services.report_generator import ReportGenerator
    from sqlalchemy import select

    if not reimb_ids:
        return
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.id.in_(reimb_ids))
    )
    reimbursements = list(result.scalars().all())

    generator = ReportGenerator(db)
    success_count = 0
    fail_count = 0
    for reimb in reimbursements:
        try:
            await generator.generate_all(reimb.id)
            success_count += 1
            logger.info("Report generated for reimbursement #%s (aggregated)", reimb.id)
        except Exception as e:
            fail_count += 1
            logger.warning("Report generation failed for #%s: %s", reimb.id, e)
    logger.info(
        "Aggregated report generation: success=%d fail=%d total=%d",
        success_count, fail_count, len(reimbursements),
    )


async def _generate_reports_for_locked_cycles(db, lock_result: dict) -> None:
    """为刚封账的报销单自动生成报表三件套

    Args:
        db: 数据库会话
        lock_result: lock_just_ended_cycle 的返回值，含 cycle_key (单数字符串)
    """
    from app.models.reimbursement import Reimbursement, ReimbursementStatus
    from app.services.report_generator import ReportGenerator
    from sqlalchemy import select

    # lock_just_ended_cycle 返回 cycle_key (单数字符串)，需包装为列表
    cycle_key = lock_result.get("cycle_key")
    if not cycle_key:
        return
    cycle_keys = [cycle_key]

    logger.info("Generating reports for locked cycles: %s", cycle_keys)

    # 查询这些周期下已封账的报销单
    result = await db.execute(
        select(Reimbursement).where(
            Reimbursement.cycle_key.in_(cycle_keys),
            Reimbursement.is_cycle_locked == True,  # noqa: E712
            Reimbursement.status.in_([
                ReimbursementStatus.submitted,
                ReimbursementStatus.reviewed,
                ReimbursementStatus.reviewed,
            ]),
        )
    )
    reimbursements = list(result.scalars().all())

    generator = ReportGenerator(db)
    success_count = 0
    fail_count = 0

    for reimb in reimbursements:
        try:
            await generator.generate_all(reimb.id)
            success_count += 1
            logger.info("Report generated for reimbursement #%s", reimb.id)
        except Exception as e:
            fail_count += 1
            logger.warning(
                "Report generation failed for reimbursement #%s: %s",
                reimb.id, e,
            )

    logger.info(
        "Report generation complete: success=%d fail=%d total=%d",
        success_count, fail_count, len(reimbursements),
    )


async def _timeout_reminder_job() -> None:
    """超时主动提醒任务

    每 2 分钟检查一次处于 WAITING_PURPOSE 状态超过 5 分钟的用户，
    通过 wecom_client 主动推送提醒消息，并自动跳过（soft_reset）。
    """
    from app.dialog.dialog_engine import get_dialog_engine
    from app.dialog.models import DialogState

    try:
        engine = get_dialog_engine()
        waiting_users = await engine.get_waiting_users(
            state=DialogState.WAITING_PURPOSE,
            timeout_seconds=PURPOSE_TIMEOUT_SECONDS,
        )

        if not waiting_users:
            return

        logger.info("Found %d users in WAITING_PURPOSE timeout", len(waiting_users))

        # 尝试通过 wecom_client 主动推送提醒
        wecom_push_available = False
        try:
            from gateway.wecom_client import WeComClient
            import os
            corp_id = os.getenv("WECOM_CORP_ID", "")
            secret = os.getenv("WECOM_SECRET", "")
            agent_id = os.getenv("WECOM_AGENT_ID", "")
            if corp_id and secret and agent_id:
                wecom_client = WeComClient(corp_id, secret, agent_id)
                wecom_push_available = True
        except ImportError:
            pass

        for user_info in waiting_users:
            user_id = user_info.get("user_id", "")
            if not user_id:
                continue

            # 推送提醒消息
            if wecom_push_available:
                try:
                    await wecom_client.send_text(
                        user_id,
                        "您有一张发票等待补充用途说明已超时。"
                        "回复「跳过」可跳过描述，继续上传其他发票。"
                    )
                except Exception as e:
                    logger.warning("Timeout reminder push failed for user=%s: %s", user_id, e)

            # 自动跳过 — soft_reset 保留批量列表，清除意图槽位
            try:
                ctx = await engine.get_context(user_id)
                if ctx and ctx.state == DialogState.WAITING_PURPOSE:
                    ctx.soft_reset()
                    await engine._store.set(ctx)
                    logger.info("Auto-skipped WAITING_PURPOSE for user=%s", user_id)
            except Exception as e:
                logger.warning("Auto-skip failed for user=%s: %s", user_id, e)

    except Exception:
        logger.exception("Timeout reminder job failed")


def start_scheduler() -> AsyncIOScheduler:
    """启动定时任务调度器"""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.warning("Scheduler is already running")
        return _scheduler

    _scheduler = AsyncIOScheduler()

    # 读 cycle_end_day 作为初始 cron day
    from sqlalchemy import create_engine, text
    from app.config import settings as app_settings
    sync_url = app_settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT cycle_end_day FROM system_settings WHERE id=1")
            ).fetchone()
            initial_cycle_end_day = row[0] if row else 20
    finally:
        engine.dispose()

    # 每月 (cycle_end_day + 1) 日 00:00（北京时间）归集游离发票 + 封账刚结束的周期 + 自动生成报表
    # 次日触发：让员工能用满 cycle_end_day 当天（如 9/25 全天上传/提交，9/26 0:00 才封账）
    # 跨月处理：cycle_end_day=31 时次日为下月 1 日，day=1 仍然能正确触发
    next_day = initial_cycle_end_day % 31 + 1  # 25→26, 30→31, 31→1（次月）
    _scheduler.add_job(
        _cycle_lock_job,
        trigger=CronTrigger(day=next_day, hour=0, minute=0, timezone=tz("Asia/Shanghai")),
        id="cycle_lock_job",
        name="归集+封账+报表",
        replace_existing=True,
        misfire_grace_time=3600,  # 允许 1 小时的 misfire 补偿
    )

    # 每 2 分钟检查超时用户并主动推送提醒
    _scheduler.add_job(
        _timeout_reminder_job,
        trigger=IntervalTrigger(minutes=2),
        id="timeout_reminder_job",
        name="超时主动提醒",
        replace_existing=True,
        misfire_grace_time=60,
    )

    _scheduler.start()
    logger.info("Scheduler started with jobs: %s", [j.id for j in _scheduler.get_jobs()])
    return _scheduler


async def stop_scheduler() -> None:
    """停止调度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


def reschedule_cycle_lock_job() -> None:
    """管理员改 cycle_end_day 后调，重新注册 cron trigger

    从 DB 同步读最新 cycle_end_day，reschedule_job 更新 cron。
    """
    global _scheduler
    if not _scheduler or not _scheduler.running:
        return  # scheduler 未启动（首次加载时），跳过

    from sqlalchemy import create_engine, text
    from app.config import settings as app_settings
    sync_url = app_settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT cycle_end_day FROM system_settings WHERE id=1")
            ).fetchone()
            cycle_end_day = row[0] if row else 20
    finally:
        engine.dispose()

    # 次日触发：cycle_end_day=25 → cron 在 26 日 0:00 触发；31 → 1（次月）
    next_day = cycle_end_day % 31 + 1
    _scheduler.reschedule_job(
        "cycle_lock_job",
        trigger=CronTrigger(
            day=next_day, hour=0, minute=0,
            timezone=tz("Asia/Shanghai"),
        ),
    )
    logger.info(f"Cycle lock job rescheduled to day={next_day} (cycle_end_day={cycle_end_day}, 次日触发让员工能用满周期最后一天)")
