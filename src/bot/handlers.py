"""Callback query handlers for inline buttons and text input."""

from __future__ import annotations

import json
import os

import structlog
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import draft_keyboard
from src.bot.publisher import publish_to_channel
from src.generator.client import LLMClient
from src.generator.postprocessor import postprocess
from src.generator.prompt import PromptBuilder
from src.storage.db import get_db
from src.storage.models import GeneratedPost, RawArticle, ScoredArticle
from src.storage.repository import (
    get_max_generation_attempt,
    get_post,
    mark_post_published,
    save_post,
)

logger = structlog.get_logger()
router = Router()

# Track which users are in "edit" mode (awaiting edit prompt)
# admin_chat_id -> post_id
_edit_state: dict[int, str] = {}


def _get_admin_chat_id() -> int:
    return int(os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "0"))


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("publish:"))
async def handle_publish(callback: CallbackQuery) -> None:
    """Publish the post to the channel."""
    post_id = callback.data.split(":", 1)[1]
    db = await get_db()
    post = await get_post(db, post_id)

    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return

    try:
        msg_id = await publish_to_channel(callback.bot, post["text"])
        await mark_post_published(db, post_id, msg_id)
        await callback.message.edit_text(
            f"\u2705 <b>Опубликовано!</b>\n\nMessage ID: {msg_id}",
            parse_mode="HTML",
        )
        await callback.answer("Опубликовано!")
    except Exception as e:
        logger.error("publish_failed", post_id=post_id, error=str(e))
        await callback.answer(f"Ошибка публикации: {e}", show_alert=True)


# ---------------------------------------------------------------------------
# Regenerate
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("regen:"))
async def handle_regenerate(callback: CallbackQuery) -> None:
    """Regenerate the post with a different angle."""
    post_id = callback.data.split(":", 1)[1]
    db = await get_db()
    post = await get_post(db, post_id)

    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return

    await callback.answer("Перегенерирую...")
    await callback.message.edit_text(
        "\U0001f504 <i>Генерирую новую версию...</i>", parse_mode="HTML"
    )

    try:
        # Reconstruct article for prompt
        article_id = post["article_id"]
        scored = _build_scored_article_from_post(post)

        prompt_builder = PromptBuilder()
        system, user = prompt_builder.build_regeneration_prompt(
            scored, post["text"]
        )

        llm = LLMClient()
        raw_text = await llm.generate(system, user)
        text = postprocess(raw_text)

        # Save new generation
        attempt = await get_max_generation_attempt(db, article_id) + 1
        new_post = GeneratedPost(
            article_id=article_id,
            text=text,
            source_url=post["source_url"],
            source_name=post["source_name"],
            score=post["score"],
            score_breakdown=json.loads(post["score_breakdown"]),
            generation_attempt=attempt,
        )
        await save_post(db, new_post)

        # Send new version with buttons
        await callback.message.edit_text(
            f"{text}\n\n---\n\U0001f4ca Score: {post['score']:.2f} | v{attempt}",
            parse_mode="HTML",
            reply_markup=draft_keyboard(new_post.id),
        )
    except Exception as e:
        logger.error("regen_failed", post_id=post_id, error=str(e))
        await callback.message.edit_text(
            f"\u274c Ошибка: {e}\n\nПопробуйте ещё раз.",
            parse_mode="HTML",
            reply_markup=draft_keyboard(post_id),
        )


# ---------------------------------------------------------------------------
# Edit (with custom prompt)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("edit:"))
async def handle_edit_start(callback: CallbackQuery) -> None:
    """Start the edit flow: ask user what to change."""
    post_id = callback.data.split(":", 1)[1]
    admin_id = _get_admin_chat_id()

    _edit_state[admin_id] = post_id
    await callback.answer()
    await callback.message.reply(
        "\u270f\ufe0f <b>Что изменить?</b>\n\nНапишите в ответ, что поправить в посте "
        "(например: «сделай короче», «добавь больше сарказма», «убери последний абзац»).",
        parse_mode="HTML",
    )


@router.message(F.text)
async def handle_edit_text(message: Message) -> None:
    """Handle edit instruction from the user."""
    admin_id = _get_admin_chat_id()
    if message.chat.id != admin_id or admin_id not in _edit_state:
        return

    post_id = _edit_state.pop(admin_id)
    edit_instruction = message.text

    db = await get_db()
    post = await get_post(db, post_id)

    if not post:
        await message.reply("Пост не найден.")
        return

    await message.reply(
        "\u270f\ufe0f <i>Перегенерирую с учётом правок...</i>", parse_mode="HTML"
    )

    try:
        scored = _build_scored_article_from_post(post)
        prompt_builder = PromptBuilder()
        system, user = prompt_builder.build_edit_prompt(
            scored, post["text"], edit_instruction
        )

        llm = LLMClient()
        raw_text = await llm.generate(system, user)
        text = postprocess(raw_text)

        article_id = post["article_id"]
        attempt = await get_max_generation_attempt(db, article_id) + 1
        new_post = GeneratedPost(
            article_id=article_id,
            text=text,
            source_url=post["source_url"],
            source_name=post["source_name"],
            score=post["score"],
            score_breakdown=json.loads(post["score_breakdown"]),
            generation_attempt=attempt,
            custom_prompt=edit_instruction,
        )
        await save_post(db, new_post)

        await message.reply(
            f"{text}\n\n---\n\U0001f4ca Score: {post['score']:.2f} | v{attempt} | \u270f\ufe0f \u00ab{edit_instruction[:50]}\u00bb",
            parse_mode="HTML",
            reply_markup=draft_keyboard(new_post.id),
        )
    except Exception as e:
        logger.error("edit_failed", post_id=post_id, error=str(e))
        await message.reply(f"\u274c Ошибка: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_scored_article_from_post(post: dict) -> ScoredArticle:
    """Reconstruct a ScoredArticle from DB post data for prompt building."""
    from datetime import datetime, timezone

    breakdown = json.loads(post.get("score_breakdown", "{}"))
    article = RawArticle(
        url=post["source_url"],
        title=post.get("source_name", ""),
        content="",
        source_id=post.get("source_name", ""),
        published_at=datetime.now(timezone.utc),
    )
    return ScoredArticle(
        article=article,
        total_score=post.get("score", 0),
        breakdown=breakdown,
    )
