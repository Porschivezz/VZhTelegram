"""Main scoring engine — loads config and applies weighted scoring."""

from __future__ import annotations

import structlog
import yaml

from src.storage.models import RawArticle, ScoredArticle
from src.scorer.factors import (
    score_engagement,
    score_freshness,
    score_source_authority,
    score_topic_relevance,
    score_uniqueness,
)

logger = structlog.get_logger()


class ScoringEngine:
    """Calculates composite score for each article based on configured weights."""

    def __init__(
        self,
        scoring_config_path: str = "config/scoring.yaml",
        sources_config_path: str = "config/sources.yaml",
    ):
        with open(scoring_config_path) as f:
            config = yaml.safe_load(f)

        with open(sources_config_path) as f:
            sources_config = yaml.safe_load(f)

        self.scoring = config.get("scoring", {})
        self.topics = config.get("topics", {})
        self.weights = self.scoring.get("weights", {})
        self.freshness_lambda = self.scoring.get("freshness_lambda", 0.18)
        self.tier_scores = {
            int(k): v
            for k, v in self.scoring.get("tier_scores", {1: 1.0, 2: 0.7, 3: 0.4}).items()
        }

        # Build source lookup: source_id -> {category, tier}
        self.source_meta: dict[str, dict] = {}
        for src in sources_config.get("sources", []):
            self.source_meta[src["id"]] = {
                "category": src.get("category", ""),
                "tier": src.get("tier", 3),
            }

    def score_article(
        self,
        article: RawArticle,
        recent_titles: list[str] | None = None,
    ) -> ScoredArticle:
        """Score a single article. Returns ScoredArticle with breakdown."""
        meta = self.source_meta.get(
            article.source_id, {"category": "", "tier": 3}
        )
        recent = recent_titles or []

        breakdown = {
            "topic_relevance": score_topic_relevance(
                article, self.topics, meta["category"]
            ),
            "freshness": score_freshness(article, self.freshness_lambda),
            "source_authority": score_source_authority(
                meta["tier"], self.tier_scores
            ),
            "engagement": score_engagement(article),
            "uniqueness": score_uniqueness(article, recent),
        }

        total = sum(
            breakdown[factor] * self.weights.get(factor, 0)
            for factor in breakdown
        )

        return ScoredArticle(
            article=article,
            total_score=round(total, 4),
            breakdown={k: round(v, 4) for k, v in breakdown.items()},
        )

    def score_batch(
        self,
        articles: list[RawArticle],
        recent_titles: list[str] | None = None,
    ) -> list[ScoredArticle]:
        """Score a batch of articles."""
        scored = [
            self.score_article(article, recent_titles) for article in articles
        ]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        logger.info(
            "scoring_done",
            total=len(scored),
            top_score=scored[0].total_score if scored else 0,
            bottom_score=scored[-1].total_score if scored else 0,
        )
        return scored
