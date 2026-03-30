"""CRUD operations for articles, posts, and source cache."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite
import structlog

from src.storage.models import ArticleStatus, GeneratedPost, RawArticle

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


async def save_article(db: aiosqlite.Connection, article: RawArticle) -> None:
    """Insert a new article (ignore if already exists)."""
    await db.execute(
        """
        INSERT OR IGNORE INTO articles
            (id, url, title, content, source_id, published_at,
             collected_at, language, engagement_score, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article.id,
            article.url,
            article.title,
            article.content,
            article.source_id,
            article.published_at.isoformat(),
            article.collected_at.isoformat(),
            article.language,
            article.engagement_score,
            ArticleStatus.NEW.value,
        ),
    )
    await db.commit()


async def save_articles(db: aiosqlite.Connection, articles: list[RawArticle]) -> int:
    """Bulk-insert articles. Returns count of newly inserted."""
    count = 0
    for article in articles:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO articles
                (id, url, title, content, source_id, published_at,
                 collected_at, language, engagement_score, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.id,
                article.url,
                article.title,
                article.content,
                article.source_id,
                article.published_at.isoformat(),
                article.collected_at.isoformat(),
                article.language,
                article.engagement_score,
                ArticleStatus.NEW.value,
            ),
        )
        if cursor.rowcount > 0:
            count += 1
    await db.commit()
    logger.info("articles_saved", new=count, total=len(articles))
    return count


async def update_article_score(
    db: aiosqlite.Connection,
    article_id: str,
    score: float,
    breakdown: dict[str, float],
) -> None:
    """Update article score and mark as scored."""
    await db.execute(
        """
        UPDATE articles SET score = ?, score_breakdown = ?, status = ?
        WHERE id = ?
        """,
        (score, json.dumps(breakdown), ArticleStatus.SCORED.value, article_id),
    )
    await db.commit()


async def update_article_status(
    db: aiosqlite.Connection, article_id: str, status: ArticleStatus
) -> None:
    await db.execute(
        "UPDATE articles SET status = ? WHERE id = ?",
        (status.value, article_id),
    )
    await db.commit()


async def get_new_articles(db: aiosqlite.Connection) -> list[dict]:
    """Get all articles with status 'new'."""
    cursor = await db.execute(
        "SELECT * FROM articles WHERE status = ? ORDER BY published_at DESC",
        (ArticleStatus.NEW.value,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


async def save_post(db: aiosqlite.Connection, post: GeneratedPost) -> None:
    """Save a generated post."""
    data = post.to_db_dict()
    await db.execute(
        """
        INSERT OR REPLACE INTO posts
            (id, article_id, text, source_url, source_name, score,
             score_breakdown, generation_attempt, custom_prompt,
             created_at, telegram_message_id, published_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["id"],
            data["article_id"],
            data["text"],
            data["source_url"],
            data["source_name"],
            data["score"],
            data["score_breakdown"],
            data["generation_attempt"],
            data["custom_prompt"],
            data["created_at"],
            data["telegram_message_id"],
            data["published_at"],
        ),
    )
    await db.commit()


async def get_post(db: aiosqlite.Connection, post_id: str) -> dict | None:
    """Get a post by ID."""
    cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_latest_post_for_article(
    db: aiosqlite.Connection, article_id: str
) -> dict | None:
    """Get the most recent post for an article."""
    cursor = await db.execute(
        """
        SELECT * FROM posts WHERE article_id = ?
        ORDER BY generation_attempt DESC LIMIT 1
        """,
        (article_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_max_generation_attempt(
    db: aiosqlite.Connection, article_id: str
) -> int:
    """Get the highest generation attempt number for an article."""
    cursor = await db.execute(
        "SELECT MAX(generation_attempt) FROM posts WHERE article_id = ?",
        (article_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row[0] is not None else 0


async def mark_post_published(
    db: aiosqlite.Connection,
    post_id: str,
    telegram_message_id: int,
) -> None:
    """Mark a post as published."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        UPDATE posts SET published_at = ?, telegram_message_id = ?
        WHERE id = ?
        """,
        (now, telegram_message_id, post_id),
    )
    # Also update the article status
    cursor = await db.execute(
        "SELECT article_id FROM posts WHERE id = ?", (post_id,)
    )
    row = await cursor.fetchone()
    if row:
        await db.execute(
            "UPDATE articles SET status = ? WHERE id = ?",
            (ArticleStatus.PUBLISHED.value, row[0]),
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Source cache
# ---------------------------------------------------------------------------


async def get_source_cache(
    db: aiosqlite.Connection, source_id: str
) -> dict | None:
    """Get cached ETag/Last-Modified for a source."""
    cursor = await db.execute(
        "SELECT * FROM source_cache WHERE source_id = ?", (source_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_source_cache(
    db: aiosqlite.Connection,
    source_id: str,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    """Update or insert source cache entry."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        INSERT OR REPLACE INTO source_cache
            (source_id, etag, last_modified, last_fetched)
        VALUES (?, ?, ?, ?)
        """,
        (source_id, etag, last_modified, now),
    )
    await db.commit()
