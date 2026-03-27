"""Social media collector — wraps last30days-skill + fallback direct APIs."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import structlog

from src.collector.base import BaseCollector
from src.storage.models import RawArticle

logger = structlog.get_logger()


class SocialCollector(BaseCollector):
    """Collects trending content from social platforms.

    Primary: calls last30days-skill CLI.
    Fallback: direct API calls to Hacker News, Reddit, etc.
    """

    def __init__(
        self,
        social_config: dict,
        last30days_script: str = "~/.claude/skills/last30days/scripts/last30days.py",
        timeout_seconds: int = 300,
        use_fallback: bool = True,
        freshness_hours: int = 12,
    ):
        self.config = social_config
        self.script = os.path.expanduser(last30days_script)
        self.timeout = timeout_seconds
        self.use_fallback = use_fallback
        self.freshness_hours = freshness_hours

    async def _run_last30days(self, query: str) -> list[dict]:
        """Run last30days-skill via subprocess and parse output."""
        if not Path(self.script).exists():
            logger.warning("last30days_not_found", path=self.script)
            return []

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                self.script,
                query,
                "--emit=compact",
                "--days=1",
                "--quick",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            if proc.returncode != 0:
                logger.warning(
                    "last30days_error",
                    query=query,
                    stderr=stderr.decode()[:500],
                )
                return []

            output = stdout.decode()
            # Parse compact JSON output
            try:
                return json.loads(output) if output.strip() else []
            except json.JSONDecodeError:
                # Output may be text, not JSON — skip
                return []

        except asyncio.TimeoutError:
            logger.warning("last30days_timeout", query=query)
            return []
        except FileNotFoundError:
            logger.warning("last30days_not_installed")
            return []

    async def _collect_hackernews(self) -> list[RawArticle]:
        """Fetch top stories from Hacker News (free, no auth)."""
        hn_config = self.config.get("hackernews", {})
        min_score = hn_config.get("min_score", 100)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.freshness_hours)

        async with aiohttp.ClientSession() as session:
            # Get top story IDs
            async with session.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            ) as resp:
                if resp.status != 200:
                    return []
                story_ids = await resp.json()

            articles = []
            # Check top 30 stories
            for story_id in story_ids[:30]:
                async with session.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                ) as resp:
                    if resp.status != 200:
                        continue
                    item = await resp.json()

                if not item or item.get("type") != "story":
                    continue

                score = item.get("score", 0)
                if score < min_score:
                    continue

                pub_time = datetime.fromtimestamp(
                    item.get("time", 0), tz=timezone.utc
                )
                if pub_time < cutoff:
                    continue

                url = item.get("url", f"https://news.ycombinator.com/item?id={story_id}")
                articles.append(
                    RawArticle(
                        url=url,
                        title=item.get("title", ""),
                        content=item.get("title", ""),  # HN has no body
                        source_id="hackernews",
                        published_at=pub_time,
                        language="en",
                        engagement_score=float(score),
                    )
                )

        logger.info("hn_collected", articles=len(articles))
        return articles

    async def _collect_polymarket(self) -> list[RawArticle]:
        """Fetch trending markets from Polymarket (free, no auth)."""
        categories = self.config.get("polymarket", {}).get("categories", [])

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://gamma-api.polymarket.com/markets",
                params={"limit": 20, "active": "true", "order": "volume24hr"},
            ) as resp:
                if resp.status != 200:
                    return []
                markets = await resp.json()

        articles = []
        now = datetime.now(timezone.utc)

        for market in markets[:15]:
            question = market.get("question", "")
            description = market.get("description", "")
            volume = market.get("volume24hr", 0)

            if volume < 10000:
                continue

            articles.append(
                RawArticle(
                    url=f"https://polymarket.com/event/{market.get('slug', '')}",
                    title=question,
                    content=f"{question}\n\n{description}",
                    source_id="polymarket",
                    published_at=now,
                    language="en",
                    engagement_score=float(volume),
                )
            )

        logger.info("polymarket_collected", articles=len(articles))
        return articles

    async def collect(self) -> list[RawArticle]:
        """Collect from all social sources."""
        all_articles: list[RawArticle] = []

        # Try last30days-skill first for broad social scanning
        topics = [
            "AI artificial intelligence latest breakthroughs",
            "management consulting strategy trends",
            "financial markets macro economy",
            "biotech medicine breakthroughs",
            "media marketing digital trends",
        ]

        last30days_tasks = [self._run_last30days(topic) for topic in topics]
        results = await asyncio.gather(*last30days_tasks, return_exceptions=True)

        now = datetime.now(timezone.utc)
        for result in results:
            if isinstance(result, Exception) or not result:
                continue
            for item in result:
                if isinstance(item, dict):
                    all_articles.append(
                        RawArticle(
                            url=item.get("url", ""),
                            title=item.get("title", ""),
                            content=item.get("summary", item.get("content", "")),
                            source_id=f"social_{item.get('platform', 'unknown')}",
                            published_at=now,
                            language="en",
                            engagement_score=item.get("score"),
                        )
                    )

        # Always run free fallback APIs
        if self.use_fallback:
            fallback_tasks = [
                self._collect_hackernews(),
                self._collect_polymarket(),
            ]
            fallback_results = await asyncio.gather(
                *fallback_tasks, return_exceptions=True
            )
            for result in fallback_results:
                if isinstance(result, list):
                    all_articles.extend(result)

        logger.info("social_collection_done", total=len(all_articles))
        return all_articles
