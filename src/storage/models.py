"""Data models shared across all pipeline stages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ArticleStatus(str, Enum):
    NEW = "new"
    SCORED = "scored"
    GENERATING = "generating"
    DRAFT_SENT = "draft_sent"
    PUBLISHED = "published"
    REJECTED = "rejected"


@dataclass
class RawArticle:
    """Article collected from a source (Step 1 output)."""

    url: str
    title: str
    content: str
    source_id: str
    published_at: datetime
    language: str = "en"
    engagement_score: float | None = None  # Social signals if available
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def id(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:32]


@dataclass
class ScoredArticle:
    """Article with scoring breakdown (Step 2 output)."""

    article: RawArticle
    total_score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    # breakdown example: {"topic_relevance": 0.8, "freshness": 0.9, ...}

    @property
    def id(self) -> str:
        return self.article.id


@dataclass
class GeneratedPost:
    """Generated Telegram post (Step 3 output)."""

    article_id: str
    text: str
    source_url: str
    source_name: str
    score: float
    score_breakdown: dict[str, float]
    generation_attempt: int = 1
    custom_prompt: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    telegram_message_id: int | None = None
    published_at: datetime | None = None

    @property
    def id(self) -> str:
        return f"{self.article_id}_{self.generation_attempt}"

    def to_db_dict(self) -> dict:
        return {
            "id": self.id,
            "article_id": self.article_id,
            "text": self.text,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "score": self.score,
            "score_breakdown": json.dumps(self.score_breakdown),
            "generation_attempt": self.generation_attempt,
            "custom_prompt": self.custom_prompt,
            "created_at": self.created_at.isoformat(),
            "telegram_message_id": self.telegram_message_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }
