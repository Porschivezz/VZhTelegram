"""Bot-specific types for tracking draft message state."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DraftState:
    """Tracks the state of a draft message in the admin chat."""

    post_id: str
    article_id: str
    telegram_message_id: int | None = None
    awaiting_edit_prompt: bool = False
