"""SQLite database connection management via aiosqlite."""

from __future__ import annotations

import os
from pathlib import Path

import aiosqlite
import structlog

from src.storage.migrations import run_migrations

logger = structlog.get_logger()

_db: aiosqlite.Connection | None = None


async def get_db(db_path: str = "data/vzhtelegram.db") -> aiosqlite.Connection:
    """Get or create a database connection, running migrations if needed."""
    global _db
    if _db is not None:
        return _db

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(path))
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")

    await run_migrations(_db)
    logger.info("database_ready", path=str(path))
    return _db


async def close_db() -> None:
    """Close the database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("database_closed")
