"""Inline keyboard builders for draft review."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def draft_keyboard(post_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard with Publish / Regenerate / Edit buttons."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="\u2705 \u041e\u043f\u0443\u0431\u043b\u0438\u043a\u043e\u0432\u0430\u0442\u044c",
                    callback_data=f"publish:{post_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="\U0001f504 \u041f\u0435\u0440\u0435\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u043e\u0432\u0430\u0442\u044c",
                    callback_data=f"regen:{post_id}",
                ),
                InlineKeyboardButton(
                    text="\u270f\ufe0f \u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c",
                    callback_data=f"edit:{post_id}",
                ),
            ],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    """Simple confirmation keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2705 \u0414\u0430", callback_data="confirm_yes"),
                InlineKeyboardButton(text="\u274c \u041d\u0435\u0442", callback_data="confirm_no"),
            ]
        ]
    )
