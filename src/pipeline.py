"""Main pipeline orchestrator: Step 1 → Step 2 → Step 3 → Step 4."""

from __future__ import annotations

import json

import structlog
import yaml

from src.bot.app import send_draft
from src.collector.manager import CollectorManager
from src.generator.client import LLMClient
from src.generator.postprocessor import postprocess
from src.generator.prompt import PromptBuilder
from src.scorer.engine import ScoringEngine
from src.scorer.selector import ArticleSelector
from src.storage.db import get_db
from src.storage.models import GeneratedPost, RawArticle, ArticleStatus
from src.storage.repository import (
    get_new_articles,
    save_post,
    update_article_score,
    update_article_status,
)

logger = structlog.get_logger()


class Pipeline:
    """Orchestrates the full monitoring → scoring → generation → review cycle."""

    def __init__(self, settings_path: str = "config/settings.yaml"):
        with open(settings_path) as f:
            self.settings = yaml.safe_load(f)

        with open("config/sources.yaml") as f:
            sources_config = yaml.safe_load(f)

        self.collector = CollectorManager(settings=self.settings)
        self.scoring_engine = ScoringEngine()
        self.selector = ArticleSelector()
        self.prompt_builder = PromptBuilder()

        gen_settings = self.settings.get("generator", {})
        self.llm = LLMClient(
            model=gen_settings.get("model", "anthropic/claude-sonnet-4-20250514"),
            fallback_model=gen_settings.get(
                "fallback_model", "anthropic/claude-haiku-4-5-20251001"
            ),
            temperature=gen_settings.get("temperature", 0.7),
            max_tokens=gen_settings.get("max_tokens", 2048),
        )

        # Build source category lookup for selector
        self.source_categories = {
            src["id"]: src.get("category", "")
            for src in sources_config.get("sources", [])
        }

    async def run_cycle(self, bot=None) -> int:
        """Run one full pipeline cycle.

        Returns the number of drafts generated and sent.
        """
        db = await get_db(self.settings.get("storage", {}).get(
            "database_path", "data/vzhtelegram.db"
        ))

        # --- Step 1: Collect ---
        logger.info("pipeline_step1_collect")
        new_articles = await self.collector.collect_all(db)

        if not new_articles:
            logger.info("pipeline_no_new_articles")
            return 0

        # Convert DB format back to RawArticle for scoring
        raw_articles = self._to_raw_articles(new_articles)

        # --- Step 2: Score & Select ---
        logger.info("pipeline_step2_score", articles=len(raw_articles))

        # Get recent titles for uniqueness scoring
        recent_rows = await self._get_recent_titles(db)
        scored = self.scoring_engine.score_batch(raw_articles, recent_rows)

        # Update scores in DB
        for sa in scored:
            await update_article_score(db, sa.article.id, sa.total_score, sa.breakdown)

        selected = self.selector.select(scored, self.source_categories)
        logger.info("pipeline_step2_selected", count=len(selected))

        if not selected:
            logger.info("pipeline_nothing_selected")
            return 0

        # --- Step 3: Generate ---
        logger.info("pipeline_step3_generate", count=len(selected))
        drafts_sent = 0

        for scored_article in selected:
            try:
                await update_article_status(
                    db, scored_article.article.id, ArticleStatus.GENERATING
                )

                system, user = self.prompt_builder.build_generation_prompt(
                    scored_article
                )
                raw_text = await self.llm.generate(system, user)
                text = postprocess(raw_text)

                post = GeneratedPost(
                    article_id=scored_article.article.id,
                    text=text,
                    source_url=scored_article.article.url,
                    source_name=scored_article.article.source_id,
                    score=scored_article.total_score,
                    score_breakdown=scored_article.breakdown,
                )
                await save_post(db, post)

                # --- Step 4: Send to bot ---
                if bot:
                    await send_draft(bot, post)
                    await update_article_status(
                        db, scored_article.article.id, ArticleStatus.DRAFT_SENT
                    )
                    drafts_sent += 1

                logger.info(
                    "draft_generated",
                    article_id=scored_article.article.id,
                    score=scored_article.total_score,
                )

            except Exception as e:
                logger.error(
                    "generation_failed",
                    article_id=scored_article.article.id,
                    error=str(e),
                )
                continue

        logger.info("pipeline_cycle_complete", drafts_sent=drafts_sent)
        return drafts_sent

    def _to_raw_articles(self, articles: list) -> list[RawArticle]:
        """Convert collected articles (RawArticle or list) to RawArticle objects."""
        if not articles:
            return []
        if isinstance(articles[0], RawArticle):
            return articles
        # If they're dicts from DB
        from datetime import datetime

        result = []
        for a in articles:
            if isinstance(a, dict):
                result.append(
                    RawArticle(
                        url=a["url"],
                        title=a["title"],
                        content=a["content"],
                        source_id=a["source_id"],
                        published_at=datetime.fromisoformat(a["published_at"]),
                        language=a.get("language", "en"),
                        engagement_score=a.get("engagement_score"),
                    )
                )
            else:
                result.append(a)
        return result

    async def _get_recent_titles(self, db) -> list[str]:
        """Get titles of recently published posts for uniqueness scoring."""
        cursor = await db.execute(
            """
            SELECT title FROM articles
            WHERE status IN ('published', 'draft_sent')
            ORDER BY collected_at DESC LIMIT 50
            """
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
