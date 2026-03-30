"""Prompt builder: assembles system + user prompts from style config and article."""

from __future__ import annotations

import yaml

from src.storage.models import RawArticle, ScoredArticle


class PromptBuilder:
    """Builds LLM prompts for post generation."""

    def __init__(self, style_config_path: str = "config/style.yaml"):
        with open(style_config_path) as f:
            self.config = yaml.safe_load(f)

        self.system_prompt = self.config.get("system_prompt", "")
        self.examples = self.config.get("example_posts", [])
        self.format_cfg = self.config.get("format", {})

    def _build_examples_block(self) -> str:
        """Format example posts as few-shot examples."""
        if not self.examples:
            return ""

        parts = ["\n\nПРИМЕРЫ ПОСТОВ (ориентируйся на этот стиль):\n"]
        for i, ex in enumerate(self.examples, 1):
            parts.append(f"--- Пример {i} ---")
            parts.append(ex.get("text", "").strip())
            parts.append("")
        return "\n".join(parts)

    def build_generation_prompt(
        self,
        scored_article: ScoredArticle,
    ) -> tuple[str, str]:
        """Build system + user prompts for initial post generation.

        Returns (system_prompt, user_prompt).
        """
        article = scored_article.article
        system = self.system_prompt + self._build_examples_block()

        min_len = self.format_cfg.get("min_length", 400)
        max_len = self.format_cfg.get("max_length", 2200)
        short_threshold = self.format_cfg.get("short_threshold", 800)

        # Determine format based on content depth
        content_length = len(article.content)
        if content_length < 500:
            format_hint = f"Напиши короткий пост (новостной формат, {min_len}-{short_threshold} символов)."
        else:
            format_hint = f"Напиши аналитический пост ({short_threshold}-{max_len} символов) с данными и выводами."

        user = f"""Напиши пост для Telegram-канала на основе этого материала.

ИСТОЧНИК: {article.source_id}
ЗАГОЛОВОК: {article.title}
ССЫЛКА: {article.url}

СОДЕРЖАНИЕ:
{article.content[:3000]}

ОЦЕНКА РЕЛЕВАНТНОСТИ: {scored_article.total_score:.2f}
Breakdown: {scored_article.breakdown}

{format_hint}

Используй Telegram HTML-разметку (<b>, <i>, <a href="">).
Первая строка — заголовок (без тегов, цепляющий, на русском).
Пиши ТОЛЬКО на русском языке. Не копируй текст источника — синтезируй и добавь свой взгляд."""

        return system, user

    def build_regeneration_prompt(
        self,
        scored_article: ScoredArticle,
        previous_text: str,
    ) -> tuple[str, str]:
        """Build prompt for automatic regeneration (different angle)."""
        system, base_user = self.build_generation_prompt(scored_article)

        user = f"""{base_user}

ПРЕДЫДУЩАЯ ВЕРСИЯ (напиши ИНАЧЕ — другой угол, другая структура, другая подача):
{previous_text}

Сделай пост непохожим на предыдущую версию. Другой заголовок, другой ход мысли."""

        return system, user

    def build_edit_prompt(
        self,
        scored_article: ScoredArticle,
        previous_text: str,
        edit_instruction: str,
    ) -> tuple[str, str]:
        """Build prompt for user-directed regeneration."""
        system, base_user = self.build_generation_prompt(scored_article)

        user = f"""{base_user}

ТЕКУЩИЙ ТЕКСТ ПОСТА:
{previous_text}

ИНСТРУКЦИЯ ОТ АВТОРА:
{edit_instruction}

Перепиши пост с учётом инструкции автора, сохраняя стиль канала."""

        return system, user
