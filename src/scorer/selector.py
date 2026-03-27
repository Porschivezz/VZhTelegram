"""Threshold filter, top-N selection, and diversity enforcement."""

from __future__ import annotations

import structlog
import yaml

from src.storage.models import ScoredArticle

logger = structlog.get_logger()


class ArticleSelector:
    """Selects articles that pass scoring threshold with diversity constraints."""

    def __init__(self, scoring_config_path: str = "config/scoring.yaml"):
        with open(scoring_config_path) as f:
            config = yaml.safe_load(f)

        scoring = config.get("scoring", {})
        thresholds = scoring.get("thresholds", {})
        limits = scoring.get("limits", {})

        self.min_score = thresholds.get("minimum_score", 0.45)
        self.auto_select = thresholds.get("auto_select_above", 0.80)
        self.max_per_cycle = limits.get("max_posts_per_cycle", 5)
        self.min_per_cycle = limits.get("min_posts_per_cycle", 0)
        self.max_same_source = limits.get("max_from_same_source", 2)
        self.max_same_category = limits.get("max_from_same_category", 3)

    def select(
        self,
        scored_articles: list[ScoredArticle],
        source_categories: dict[str, str] | None = None,
    ) -> list[ScoredArticle]:
        """Select articles based on score threshold and diversity constraints.

        Args:
            scored_articles: Articles sorted by score (descending).
            source_categories: Mapping of source_id -> category.
        """
        source_categories = source_categories or {}

        # Filter by minimum score
        candidates = [a for a in scored_articles if a.total_score >= self.min_score]

        selected: list[ScoredArticle] = []
        source_count: dict[str, int] = {}
        category_count: dict[str, int] = {}

        for article in candidates:
            if len(selected) >= self.max_per_cycle:
                break

            source_id = article.article.source_id
            category = source_categories.get(source_id, "unknown")

            # Diversity: max per source
            if source_count.get(source_id, 0) >= self.max_same_source:
                continue

            # Diversity: max per category
            if category_count.get(category, 0) >= self.max_same_category:
                continue

            selected.append(article)
            source_count[source_id] = source_count.get(source_id, 0) + 1
            category_count[category] = category_count.get(category, 0) + 1

        logger.info(
            "selection_done",
            candidates=len(candidates),
            selected=len(selected),
            top_score=selected[0].total_score if selected else 0,
        )
        return selected
