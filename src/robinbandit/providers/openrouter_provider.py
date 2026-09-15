"""Especialização OpenRouter sobre o adaptador OpenAI-compatible do Robin."""
from __future__ import annotations

from typing import Dict, List, Optional

from .openai_compat import OpenAICompatProvider


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_URL = f"{OPENROUTER_BASE_URL}/chat/completions"


class OpenRouterProvider(OpenAICompatProvider):
    def __init__(
        self,
        api_key: str,
        models: List[str],
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(
            name="openrouter",
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            models=models or ["openrouter/free"],
            # A atribuicao pertence ao host. O pacote nao fixa produto ou deploy.
            extra_headers=dict(extra_headers or {}),
            timeout=30.0,
        )
