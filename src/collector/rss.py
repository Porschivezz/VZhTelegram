"""RSS/Atom feed collector — async fetching with ETag caching and freshness filter."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import feedparser
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.collector.base import BaseCollector
from src.storage.models import RawArticle

logger = structlog.get_logger()


def _parse_date(entry: dict) -> datetime | None:
    """Extract published date from a feed entry."""
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                from calendar import timegm

                return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


def _extract_content(entry: dict) -> str:
    """Extract the best available content from a feed entry."""
    # Try content field first (full text)
    if "content" in entry:
        for c in entry["content"]:
            if c.get("value"):
                return c["value"]
    # Fall back to summary/description
    return entry.get("summary", entry.get("description", ""))


class RSSCollector(BaseCollector):
    """Collects articles from RSS/Atom feeds."""

    def __init__(
        self,
        sources: list[dict],
        freshness_hours: int = 12,
        max_concurrent: int = 20,
        timeout_seconds: int = 30,
    ):
        self.sources = [s for s in sources if s.get("type") == "rss"]
        self.freshness_hours = freshness_hours
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        # source_id -> {"etag": ..., "last_modified": ...}
        self.cache: dict[str, dict] = {}

    def set_cache(self, source_id: str, etag: str | None, last_modified: str | None):
        """Set cached headers for a source."""
        self.cache[source_id] = {"etag": etag, "last_modified": last_modified}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=8))
    async def _fetch_feed(
        self, session: aiohttp.ClientSession, source: dict
    ) -> list[RawArticle]:
        """Fetch and parse a single RSS feed."""
        source_id = source["id"]
        url = source["url"]
        headers = {"User-Agent": "VZhTelegram/1.0 (RSS Aggregator)"}

        cached = self.cache.get(source_id, {})
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]

        async with self.semaphore:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 304:
                    logger.debug("feed_not_modified", source=source_id)
                    return []
                if resp.status != 200:
                    logger.warning(
                        "feed_fetch_failed", source=source_id, status=resp.status
                    )
                    return []

                # Update cache
                self.cache[source_id] = {
                    "etag": resp.headers.get("ETag"),
                    "last_modified": resp.headers.get("Last-Modified"),
                }

                body = await resp.text()

        feed = feedparser.parse(body)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.freshness_hours)
        articles = []

        for entry in feed.entries:
            pub_date = _parse_date(entry)
            if pub_date is None or pub_date < cutoff:
                continue

            link = entry.get("link", "")
            title = entry.get("title", "")
            content = _extract_content(entry)

            if not link or not title:
                continue

            articles.append(
                RawArticle(
                    url=link,
                    title=title,
                    content=content,
                    source_id=source_id,
                    published_at=pub_date,
                    language=source.get("language", "en"),
                )
            )

        logger.info("feed_collected", source=source_id, articles=len(articles))
        return articles

    async def collect(self) -> list[RawArticle]:
        """Fetch all RSS feeds concurrently and return fresh articles."""
        all_articles: list[RawArticle] = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [self._fetch_feed(session, src) for src in self.sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "feed_error",
                    source=self.sources[i]["id"],
                    error=str(result),
                )
            else:
                all_articles.extend(result)

        logger.info("rss_collection_done", total_articles=len(all_articles))
        return all_articles
