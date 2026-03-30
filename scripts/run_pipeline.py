"""CLI entry point: runs the bot + scheduler, or a single pipeline cycle."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import structlog
import yaml

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configure structlog for console or JSON output."""
    if fmt == "json":
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.BoundLogger,
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )
    else:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.BoundLogger,
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )


async def run_once() -> None:
    """Run a single pipeline cycle without the bot (dry-run/testing)."""
    from src.pipeline import Pipeline

    pipeline = Pipeline()
    drafts = await pipeline.run_cycle(bot=None)
    print(f"\nPipeline complete: {drafts} drafts generated (not sent — no bot).")


async def run_bot() -> None:
    """Run the bot with scheduler (production mode)."""
    from src.bot.app import create_bot, create_dispatcher
    from src.pipeline import Pipeline
    from src.scheduler import start_scheduler, stop_scheduler
    from src.storage.db import close_db

    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)

    interval = settings.get("pipeline", {}).get("cycle_interval_minutes", 60)

    bot = create_bot()
    dp = create_dispatcher()
    pipeline = Pipeline()

    # Start scheduler
    scheduler = start_scheduler(pipeline, bot, interval_minutes=interval)

    # Run initial cycle immediately
    asyncio.create_task(pipeline.run_cycle(bot=bot))

    try:
        # Start polling (blocks until stopped)
        await dp.start_polling(bot)
    finally:
        stop_scheduler()
        await close_db()
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VZhTelegram — Automated Telegram channel pipeline"
    )
    parser.add_argument(
        "--mode",
        choices=["bot", "once"],
        default="bot",
        help="'bot' = run bot + scheduler (default), 'once' = single pipeline run",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--log-format",
        default="console",
        choices=["console", "json"],
    )
    args = parser.parse_args()

    configure_logging(args.log_level, args.log_format)

    if args.mode == "once":
        asyncio.run(run_once())
    else:
        asyncio.run(run_bot())


if __name__ == "__main__":
    main()
