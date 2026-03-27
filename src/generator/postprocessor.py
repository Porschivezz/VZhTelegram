"""Post-processing: cleanup, Telegram HTML validation, length check."""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger()

# Allowed Telegram HTML tags
ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre", "blockquote"}


def clean_text(text: str) -> str:
    """Clean up LLM output for Telegram posting."""
    # Remove markdown artifacts that LLM might produce
    text = text.strip()

    # Remove ```html wrapping if present
    text = re.sub(r"^```html?\s*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)

    # Replace ** markdown bold with <b> HTML
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Replace * markdown italic with <i> HTML
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # Remove stray markdown headers (#, ##, etc.)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Fix double newlines (keep max 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


def validate_html(text: str) -> str:
    """Ensure only Telegram-safe HTML tags are present, close unclosed tags."""
    # Find all HTML tags
    tags = re.findall(r"<(/?)(\w+)([^>]*)>", text)

    # Remove non-allowed tags
    for full_match in re.finditer(r"</?(\w+)[^>]*>", text):
        tag_name = full_match.group(1).lower()
        if tag_name not in ALLOWED_TAGS:
            text = text.replace(full_match.group(0), "")

    # Simple check for unclosed tags (basic, not full HTML parser)
    open_tags: list[str] = []
    for is_close, tag_name, _ in tags:
        tag_name = tag_name.lower()
        if tag_name not in ALLOWED_TAGS:
            continue
        if is_close == "/":
            if open_tags and open_tags[-1] == tag_name:
                open_tags.pop()
        else:
            open_tags.append(tag_name)

    # Close any remaining open tags
    for tag in reversed(open_tags):
        text += f"</{tag}>"

    return text


def enforce_length(text: str, min_length: int = 400, max_length: int = 2200) -> str:
    """Truncate if too long (at paragraph boundary). Warn if too short."""
    if len(text) <= max_length:
        if len(text) < min_length:
            logger.warning("post_too_short", length=len(text), min=min_length)
        return text

    # Truncate at last paragraph boundary before max_length
    truncated = text[:max_length]
    last_para = truncated.rfind("\n\n")
    if last_para > max_length // 2:
        truncated = truncated[:last_para]

    logger.info("post_truncated", original=len(text), truncated=len(truncated))
    return truncated


def postprocess(
    text: str,
    min_length: int = 400,
    max_length: int = 2200,
) -> str:
    """Full post-processing pipeline."""
    text = clean_text(text)
    text = validate_html(text)
    text = enforce_length(text, min_length, max_length)
    return text
