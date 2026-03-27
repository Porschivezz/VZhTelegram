"""Deduplication: URL-hash (exact) + SimHash (near-duplicate content)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

import aiosqlite
from datasketch import MinHash


def url_hash(url: str) -> str:
    """Deterministic hash of a normalized URL."""
    normalized = url.strip().rstrip("/").lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def text_fingerprint(text: str, num_perm: int = 128) -> MinHash:
    """Create a MinHash fingerprint of the text for near-duplicate detection."""
    mh = MinHash(num_perm=num_perm)
    # Tokenize into shingles (3-word windows)
    words = re.sub(r"[^\w\s]", "", text.lower()).split()
    for i in range(len(words) - 2):
        shingle = " ".join(words[i : i + 3])
        mh.update(shingle.encode("utf-8"))
    return mh


async def is_duplicate_url(db: aiosqlite.Connection, url: str) -> bool:
    """Check if an article with this URL already exists."""
    article_id = url_hash(url)
    cursor = await db.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,))
    return await cursor.fetchone() is not None


async def is_near_duplicate_content(
    db: aiosqlite.Connection,
    text: str,
    window_hours: int = 72,
    similarity_threshold: float = 0.7,
) -> bool:
    """Check if similar content was already collected within the time window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    cursor = await db.execute(
        "SELECT content FROM articles WHERE collected_at > ? AND status != 'rejected'",
        (cutoff,),
    )
    new_fp = text_fingerprint(text)
    async for row in cursor:
        existing_fp = text_fingerprint(row[0])
        similarity = new_fp.jaccard(existing_fp)
        if similarity >= similarity_threshold:
            return True
    return False
