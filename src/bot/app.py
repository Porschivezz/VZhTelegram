"""Bot application setup: initialization, handler registration, draft sending."""

from __future__ import annotations

import json
import os

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from src.bot.handlers import router
from src.bot.keyboards import draft_keyboard
from src.storage.models import GeneratedPost

logger = structlog.get_logger()


def create_bot() -> Bot:
    """Create and configure the Telegram bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")
    return Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))


def create_dispatcher() -> Dispatcher:
    """Create dispatcher and register all handlers."""
    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def send_draft(bot: Bot, post: GeneratedPost) -> int:
    """Send a draft post to the admin for review.

    Returns the Telegram message ID of the sent draft.
    """
    admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not admin_chat_id:
        raise ValueError("TELEGRAM_ADMIN_CHAT_ID not set")

    # Format: post text + metadata + inline buttons
    score_str = f"\U0001f4ca Score: {post.score:.2f}"
    breakdown_str = " | ".join(
        f"{k}: {v:.2f}" for k, v in post.score_breakdown.items()
    )
    meta = (
        f"\n\n---\n"
        f"{score_str}\n"
        f"{breakdown_str}\n"
        f"\U0001f517 <a href=\"{post.source_url}\">Источник</a> ({post.source_name})"
    )

    full_text = post.text + meta

    # Telegram message limit is 4096 chars
    if len(full_text) > 4096:
        full_text = full_text[:4090] + "..."

    message = await bot.send_message(
        chat_id=admin_chat_id,
        text=full_text,
        parse_mode="HTML",
        reply_markup=draft_keyboard(post.id),
        disable_web_page_preview=True,
    )

    logger.info(
        "draft_sent",
        post_id=post.id,
        message_id=message.message_id,
    )
    return message.message_id
