"""Web scraper fallback for sources without RSS feeds."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import structlog
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from src.collector.base import BaseCollector
from src.storage.models import RawArticle

logger = structlog.get_logger()


class WebScraperCollector(BaseCollector):
    """Scrapes web pages for sources that don't have RSS feeds."""

    def __init__(
        self,
        sources: list[dict],
        freshness_hours: int = 12,
        max_concurrent: int = 10,
        timeout_seconds: int = 30,
    ):
        self.sources = [s for s in sources if s.get("type") == "web"]
        self.freshness_hours = freshness_hours
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=8))
    async def _scrape_source(
        self, session: aiohttp.ClientSession, source: dict
    ) -> list[RawArticle]:
        """Scrape a single web source using configured CSS selectors."""
        source_id = source["id"]
        url = source["url"]
        selectors = source.get("selectors", {})
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        async with self.semaphore:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(
                        "scrape_failed", source=source_id, status=resp.status
                    )
                    return []
                html = await resp.text()

        soup = BeautifulSoup(html, "lxml")
        articles = []
        now = datetime.now(timezone.utc)

        # Use configured selectors or fall back to generic article detection
        article_sel = selectors.get("article", "article")
        title_sel = selectors.get("title", "h2, h3")
        link_sel = selectors.get("link", "a")

        for element in soup.select(article_sel)[:20]:  # Limit to 20 per source
            title_el = element.select_one(title_sel)
            link_el = element.select_one(link_sel)

            if not title_el or not link_el:
                continue

            title = title_el.get_text(strip=True)
            href = link_el.get("href", "")
            if not href:
                continue

            # Resolve relative URLs
            if href.startswith("/"):
                from urllib.parse import urljoin

                href = urljoin(url, href)

            # Extract whatever content is available
            content = element.get_text(separator=" ", strip=True)

            # Web sources don't reliably expose dates —
            # assume recent (within freshness window) and let scoring handle it
            articles.append(
                RawArticle(
                    url=href,
                    title=title,
                    content=content,
                    source_id=source_id,
                    published_at=now,  # Best guess
                    language=source.get("language", "en"),
                )
            )

        logger.info("scrape_collected", source=source_id, articles=len(articles))
        return articles

    async def collect(self) -> list[RawArticle]:
        """Scrape all web sources concurrently."""
        all_articles: list[RawArticle] = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [self._scrape_source(session, src) for src in self.sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "scrape_error",
                    source=self.sources[i]["id"],
                    error=str(result),
                )
            else:
                all_articles.extend(result)

        logger.info("scraper_collection_done", total_articles=len(all_articles))
        return all_articles
