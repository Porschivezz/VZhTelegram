"""Publish approved posts to the Telegram channel."""

from __future__ import annotations

import os

import structlog
from aiogram import Bot

logger = structlog.get_logger()


async def publish_to_channel(bot: Bot, text: str) -> int:
    """Send a post to the Telegram channel.

    Returns the message_id of the published message.
    """
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "")
    if not channel_id:
        raise ValueError("TELEGRAM_CHANNEL_ID not set")

    message = await bot.send_message(
        chat_id=channel_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=False,
    )
    logger.info(
        "post_published",
        channel=channel_id,
        message_id=message.message_id,
    )
    return message.message_id
