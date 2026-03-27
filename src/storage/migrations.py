"""Database schema creation and versioning."""

from __future__ import annotations

import aiosqlite

SCHEMA_VERSION = 1

MIGRATIONS = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_id TEXT NOT NULL,
            published_at TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            language TEXT DEFAULT 'en',
            engagement_score REAL,
            score REAL,
            score_breakdown TEXT,
            status TEXT DEFAULT 'new'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            article_id TEXT NOT NULL REFERENCES articles(id),
            text TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_name TEXT NOT NULL,
            score REAL,
            score_breakdown TEXT,
            generation_attempt INTEGER DEFAULT 1,
            custom_prompt TEXT,
            created_at TEXT NOT NULL,
            telegram_message_id INTEGER,
            published_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS source_cache (
            source_id TEXT PRIMARY KEY,
            etag TEXT,
            last_modified TEXT,
            last_fetched TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)",
        "CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at)",
        "CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id)",
        "CREATE INDEX IF NOT EXISTS idx_posts_article ON posts(article_id)",
    ],
}


async def run_migrations(db: aiosqlite.Connection) -> None:
    """Apply all pending migrations."""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )
    cursor = await db.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    current_version = row[0] if row[0] is not None else 0

    for version in range(current_version + 1, SCHEMA_VERSION + 1):
        if version in MIGRATIONS:
            for sql in MIGRATIONS[version]:
                await db.execute(sql)
            await db.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (version,),
            )
    await db.commit()
