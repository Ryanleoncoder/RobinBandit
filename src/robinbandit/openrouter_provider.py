"""Especialização OpenRouter sobre o adaptador OpenAI-compatible do Robin."""
from __future__ import annotations

from typing import List

from .openai_compat import OpenAICompatProvider


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_URL = f"{OPENROUTER_BASE_URL}/chat/completions"


class OpenRouterProvider(OpenAICompatProvider):
    def __init__(self, api_key: str, models: List[str]):
        super().__init__(
            name="openrouter",
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            models=models or ["openrouter/free"],
            extra_headers={
                "HTTP-Referer": "https://sentury-intelligence.onrender.com",
                "X-Title": "Sentury Intelligence",
            },
            timeout=30.0,
        )
