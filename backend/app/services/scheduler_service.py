"""定时任务调度服务

使用 APScheduler AsyncIOScheduler 在 FastAPI lifespan 中启动/停止。
当前注册的任务：
- cycle_lock_job: 每月 21 日 00:00 归集游离发票 + 封账上一周期 + 自动生成报表
- timeout_reminder_job: 每 2 分钟检查超时用户并主动推送提醒
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# 超时提醒阈值（秒）— 用户处于 WAITING_PURPOSE 超过此时间后触发提醒
PURPOSE_TIMEOUT_SECONDS = 300  # 5 分钟


async def _cycle_lock_job() -> None:
    """定时归集 + 封账 + 自动生成报表任务

    每月 21 日 00:00 执行：
    1. 归集所有游离发票到对应周期报销单
    2. 封账刚结束的周期（自动提交 DRAFT）
    3. 对已封账的报销单自动生成报表三件套（Excel + PDF + ZIP）
    """
    from app.database import get_async_sessionmaker
    from app.services.aggregation_service import aggregate_pending_invoices
    from app.services.cycle_lock_service import lock_just_ended_cycle

    logger.info("Cycle lock job triggered at %s", datetime.now().isoformat())
    try:
        sm = get_async_sessionmaker()
        async with sm() as db:
            # 1. 先归集所有游离发票
            agg_result = await aggregate_pending_invoices(db)
            logger.info("Pre-lock aggregation: %s", agg_result)

            # 2. 再封账刚结束的周期
            lock_result = await lock_just_ended_cycle(db)
            logger.info("Cycle lock job result: %s", lock_result)

            # 3. 封账后自动生成报表三件套（Excel + PDF + ZIP）
            if lock_result and lock_result.get("locked_count", 0) > 0:
                await _generate_reports_for_locked_cycles(db, lock_result)
    except Exception:
        logger.exception("Cycle lock job failed")


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

    # 每月 21 日 00:00 归集游离发票 + 封账上一周期 + 自动生成报表
    _scheduler.add_job(
        _cycle_lock_job,
        trigger=CronTrigger(day=21, hour=0, minute=0),
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
