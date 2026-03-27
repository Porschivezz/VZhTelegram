"""OpenRouter API client using the openai SDK with custom base_url."""

from __future__ import annotations

import os

import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


class LLMClient:
    """Async client for OpenRouter (Anthropic models)."""

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-20250514",
        fallback_model: str = "anthropic/claude-haiku-4-5-20251001",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = model
        self.fallback_model = fallback_model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=8))
    async def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
    ) -> str:
        """Make a single LLM call."""
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature_override: float | None = None,
    ) -> str:
        """Generate text, falling back to cheaper model on error."""
        temp = temperature_override or self.temperature

        try:
            return await self._call(system_prompt, user_prompt, self.model, temp)
        except Exception as e:
            logger.warning(
                "primary_model_failed",
                model=self.model,
                error=str(e),
            )
            return await self._call(
                system_prompt, user_prompt, self.fallback_model, temp
            )
