"""Orçamento de tokens de saída do RobinBandit, dinâmico por modelo.

`max_tokens` é um TETO, não um alvo: uma resposta de texto normal para sozinha
no fim natural, então subir o teto NÃO incha respostas comuns — só destrava
código/HTML completo quando o modelo realmente precisa. Modelos grandes (Ultra,
flagships) ganham teto alto; modelos pequenos/lite ficam enxutos.
"""
from __future__ import annotations

# Marcadores de modelos GRANDES / de raciocínio (flagship): espaço para gerar um
# HTML/código completo + tokens de reasoning sem truncar.
_LARGE_MARKERS = (
    "deepseek-v4", "deepseek-v3", "deepseek-r1",
    "120b", "-70b", "70b-", "-72b", "72b-", "-80b", "80b-",
    "qwen3-next", "qwen-2.5-72b", "glm-5", "glm-4", "gpt-oss-120b",
    "llama-3.3-70b", "mixtral-8x22b", "command-r-plus",
)

# Marcadores de modelos PEQUENOS / lite: resposta curta basta.
# CUIDADO com substrings: "mini" casaria com "geMINI" (todo modelo Gemini!) →
# usa "-mini" pra pegar gpt-4o-mini/o3-mini sem colidir com Gemini.
_SMALL_MARKERS = (
    "lite", "-mini", "phi", "gemma", "-7b", "7b-", "-8b", "8b-",
    "1.5b", "-3b", "3b-", "small", "haiku", "flash-lite",
)

_LARGE_BUDGET = 8192   # HTML/código completo + reasoning
_DEFAULT_BUDGET = 4096
_SMALL_BUDGET = 2048


def model_token_budget(model: str | None, *, floor: int | None = None) -> int:
    """Teto de tokens de saída adequado ao porte do modelo.

    `floor` garante um mínimo (ex.: um provider que já usava 4096 não regride).
    """
    m = (model or "").lower()
    if any(t in m for t in _LARGE_MARKERS):
        budget = _LARGE_BUDGET
    elif any(t in m for t in _SMALL_MARKERS):
        budget = _SMALL_BUDGET
    else:
        budget = _DEFAULT_BUDGET
    if floor is not None:
        budget = max(budget, floor)
    return budget
