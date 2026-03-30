"""Collection manager — orchestrates all collectors with deduplication."""

from __future__ import annotations

import asyncio

import aiosqlite
import structlog
import yaml

from src.collector.rss import RSSCollector
from src.collector.scraper import WebScraperCollector
from src.collector.social import SocialCollector
from src.storage.dedup import is_duplicate_url, is_near_duplicate_content
from src.storage.models import RawArticle
from src.storage.repository import save_articles, get_source_cache, update_source_cache

logger = structlog.get_logger()


class CollectorManager:
    """Orchestrates RSS, web scraper, and social collectors."""

    def __init__(self, config_path: str = "config/sources.yaml", settings: dict | None = None):
        with open(config_path) as f:
            config = yaml.safe_load(f)

        settings = settings or {}
        freshness = settings.get("pipeline", {}).get("freshness_hours", 12)
        concurrent = settings.get("pipeline", {}).get("concurrent_fetches", 20)
        timeout = settings.get("pipeline", {}).get("request_timeout_seconds", 30)

        sources = config.get("sources", [])
        social_config = config.get("social_sources", {})

        self.rss_collector = RSSCollector(
            sources=sources,
            freshness_hours=freshness,
            max_concurrent=concurrent,
            timeout_seconds=timeout,
        )
        self.scraper_collector = WebScraperCollector(
            sources=sources,
            freshness_hours=freshness,
            max_concurrent=concurrent // 2,
            timeout_seconds=timeout,
        )

        social_settings = settings.get("social", {})
        self.social_collector = SocialCollector(
            social_config=social_config,
            last30days_script=social_settings.get(
                "last30days_script",
                "~/.claude/skills/last30days/scripts/last30days.py",
            ),
            timeout_seconds=social_settings.get("timeout_seconds", 300),
            use_fallback=social_settings.get("use_fallback_apis", True),
            freshness_hours=freshness,
        )

    async def _load_source_cache(self, db: aiosqlite.Connection) -> None:
        """Pre-load ETag/Last-Modified cache from DB."""
        for source in self.rss_collector.sources:
            cached = await get_source_cache(db, source["id"])
            if cached:
                self.rss_collector.set_cache(
                    source["id"],
                    cached.get("etag"),
                    cached.get("last_modified"),
                )

    async def _save_source_cache(self, db: aiosqlite.Connection) -> None:
        """Persist ETag/Last-Modified cache to DB."""
        for source_id, cache_data in self.rss_collector.cache.items():
            await update_source_cache(
                db,
                source_id,
                etag=cache_data.get("etag"),
                last_modified=cache_data.get("last_modified"),
            )

    async def _dedup(
        self, db: aiosqlite.Connection, articles: list[RawArticle]
    ) -> list[RawArticle]:
        """Remove duplicates by URL hash and content similarity."""
        unique: list[RawArticle] = []
        seen_urls: set[str] = set()

        for article in articles:
            if not article.url or article.url in seen_urls:
                continue
            seen_urls.add(article.url)

            if await is_duplicate_url(db, article.url):
                continue

            # Content dedup is slower — only check if URL is new
            if article.content and await is_near_duplicate_content(
                db, article.content
            ):
                logger.debug("near_duplicate_skipped", url=article.url)
                continue

            unique.append(article)

        logger.info(
            "dedup_done", before=len(articles), after=len(unique)
        )
        return unique

    async def collect_all(self, db: aiosqlite.Connection) -> list[RawArticle]:
        """Run all collectors, dedup, and save to DB. Returns new articles."""
        await self._load_source_cache(db)

        # Run all collectors concurrently
        rss_task = self.rss_collector.collect()
        scraper_task = self.scraper_collector.collect()
        social_task = self.social_collector.collect()

        results = await asyncio.gather(
            rss_task, scraper_task, social_task, return_exceptions=True
        )

        all_articles: list[RawArticle] = []
        for i, result in enumerate(results):
            collector_name = ["rss", "scraper", "social"][i]
            if isinstance(result, Exception):
                logger.error(
                    "collector_failed", collector=collector_name, error=str(result)
                )
            else:
                all_articles.extend(result)

        logger.info("total_raw_articles", count=len(all_articles))

        # Dedup
        unique_articles = await self._dedup(db, all_articles)

        # Save to DB
        new_count = await save_articles(db, unique_articles)

        # Save cache
        await self._save_source_cache(db)

        logger.info(
            "collection_complete",
            total_raw=len(all_articles),
            unique=len(unique_articles),
            new_saved=new_count,
        )
        return unique_articles
