"""APScheduler integration — hourly pipeline trigger coexisting with the bot."""

from __future__ import annotations

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.pipeline import Pipeline

logger = structlog.get_logger()

_scheduler: AsyncIOScheduler | None = None


async def _run_pipeline_job(pipeline: Pipeline, bot) -> None:
    """Wrapper that runs the pipeline cycle and logs results."""
    try:
        logger.info("scheduler_cycle_start")
        drafts = await pipeline.run_cycle(bot=bot)
        logger.info("scheduler_cycle_done", drafts=drafts)
    except Exception as e:
        logger.error("scheduler_cycle_error", error=str(e))


def start_scheduler(
    pipeline: Pipeline,
    bot,
    interval_minutes: int = 60,
) -> AsyncIOScheduler:
    """Start the APScheduler with hourly pipeline runs."""
    global _scheduler
    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        _run_pipeline_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        args=[pipeline, bot],
        id="pipeline_cycle",
        name="VZhTelegram Pipeline Cycle",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping runs
    )

    _scheduler.start()
    logger.info("scheduler_started", interval_minutes=interval_minutes)
    return _scheduler


def stop_scheduler() -> None:
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler_stopped")
