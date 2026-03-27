"""Individual scoring factor implementations."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from src.storage.models import RawArticle


def score_topic_relevance(
    article: RawArticle,
    topics: dict,
    source_category: str,
) -> float:
    """Score how relevant the article is to channel topics.

    Returns 0.0-1.0 based on keyword matches and source category alignment.
    """
    text = f"{article.title} {article.content}".lower()
    best_score = 0.0

    for topic_id, topic_def in topics.items():
        topic_weight = topic_def.get("weight", 0.5)
        categories = topic_def.get("categories", [])

        # Category match: source belongs to this topic
        cat_bonus = 0.3 if source_category in categories else 0.0

        # Keyword matches
        all_keywords = topic_def.get("keywords_en", []) + topic_def.get("keywords_ru", [])
        if not all_keywords:
            continue

        matches = sum(1 for kw in all_keywords if kw.lower() in text)
        keyword_score = min(matches / max(len(all_keywords) * 0.15, 1), 1.0)

        combined = min((keyword_score * 0.7 + cat_bonus) * topic_weight, 1.0)
        best_score = max(best_score, combined)

    return best_score


def score_freshness(article: RawArticle, lambda_decay: float = 0.18) -> float:
    """Exponential decay based on hours since publication.

    score = exp(-lambda * hours)
    Default lambda=0.18 gives: 1h→0.84, 6h→0.34, 12h→0.11
    """
    now = datetime.now(timezone.utc)
    hours = (now - article.published_at).total_seconds() / 3600
    hours = max(hours, 0)
    return math.exp(-lambda_decay * hours)


def score_source_authority(tier: int, tier_scores: dict[int, float]) -> float:
    """Score based on source tier (1=premium, 2=strong, 3=supplementary)."""
    return tier_scores.get(tier, 0.3)


def score_engagement(article: RawArticle) -> float:
    """Score based on social engagement signals.

    Returns 0.0-1.0 normalized. If no engagement data, returns 0.5 (neutral).
    """
    if article.engagement_score is None:
        return 0.5

    # Log-scale normalization: 100 → ~0.5, 1000 → ~0.75, 10000 → ~1.0
    score = article.engagement_score
    if score <= 0:
        return 0.0
    return min(math.log10(score + 1) / 4, 1.0)


def score_uniqueness(
    article: RawArticle,
    recent_titles: list[str],
) -> float:
    """Score based on how different this article is from recently published content.

    Simple approach: check title similarity against recent titles.
    Returns 1.0 if completely unique, lower if similar titles exist.
    """
    if not recent_titles:
        return 1.0

    title_words = set(re.sub(r"[^\w\s]", "", article.title.lower()).split())
    if not title_words:
        return 1.0

    max_overlap = 0.0
    for recent in recent_titles:
        recent_words = set(re.sub(r"[^\w\s]", "", recent.lower()).split())
        if not recent_words:
            continue
        overlap = len(title_words & recent_words) / max(
            len(title_words | recent_words), 1
        )
        max_overlap = max(max_overlap, overlap)

    return 1.0 - max_overlap
