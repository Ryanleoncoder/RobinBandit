import logging
from typing import Dict, List, Optional, Tuple

import httpx

from .token_budget import model_token_budget

logger = logging.getLogger(__name__)

CLAUDE_URL = "https://api.anthropic.com/v1/messages"


def _split_messages(messages: List[Dict[str, str]]) -> Tuple[Optional[str], List[Dict]]:
    """Converte o formato de mensagens para o formato do Anthropic Claude.
    Instruções do sistema vão para o parâmetro `system` no nível do payload.
    Mensagens consecutivas do mesmo papel são mescladas para respeitar a exigência
    de alternância de papéis (user/assistant).
    """
    system_parts: List[str] = []
    formatted_messages: List[Dict] = []

    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            system_parts.append(content)
            continue

        a_role = "assistant" if role == "assistant" else "user"
        if formatted_messages and formatted_messages[-1]["role"] == a_role:
            formatted_messages[-1]["content"] += "\n\n" + content
        else:
            formatted_messages.append({"role": a_role, "content": content})

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, formatted_messages


def _usage_anthropic(bruto) -> Optional[Dict[str, int]]:
    """`usage` da Anthropic no mesmo formato dos demais provedores.

    Aqui a entrada vem repartida: `input_tokens` conta so o que NAO veio do
    cache. Somar as tres partes e o que torna o numero comparavel com o dos
    outros provedores.
    """
    if not isinstance(bruto, dict):
        return None
    lido_do_cache = int(bruto.get("cache_read_input_tokens") or 0)
    gravado_no_cache = int(bruto.get("cache_creation_input_tokens") or 0)
    entrada = int(bruto.get("input_tokens") or 0) + lido_do_cache + gravado_no_cache
    saida = int(bruto.get("output_tokens") or 0)
    if not (entrada or saida):
        return None
    usado = {"entrada": entrada, "saida": saida, "total": entrada + saida}
    if lido_do_cache:
        usado["cacheado"] = lido_do_cache
    return usado


class ClaudeProvider:
    """Provedor da API Anthropic Claude. Mesmo contrato de `complete` dos
    outros provedores.
    """

    def __init__(self, api_key: str, models: List[str]):
        self.name = "claude"
        self.api_key = (api_key or "").strip()
        self.models = models or ["claude-sonnet-4-6"]
        self.last_model: Optional[str] = None
        self.last_reasoning_summary: Optional[str] = None
        # Sem isto o turno atendido pela Anthropic aparecia com zero token: o
        # chain le `last_usage` de todo provedor, e este nao publicava nenhum.
        self.last_usage: Optional[Dict[str, int]] = None

    async def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2,
                       complexity: Optional[str] = None,
                       preferred_model: Optional[str] = None,
                       strict_model: bool = False) -> str:
        system_instruction, formatted_messages = _split_messages(messages)
        last_error: Optional[Exception] = None
        self.last_reasoning_summary = None
        self.last_model = None
        self.last_attempted_model = None
        self.model_failures = []

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            models_to_try = list(self.models)
            if preferred_model and strict_model:
                models_to_try = [preferred_model]
            elif preferred_model:
                models_to_try = [preferred_model] + [m for m in models_to_try if m != preferred_model]
            for model in models_to_try:
                self.last_attempted_model = f"claude:{model}"
                try:
                    payload = {
                        "model": model,
                        "messages": formatted_messages,
                        "temperature": temperature,
                        # Teto dinâmico por modelo (Claude exige max_tokens explícito).
                        "max_tokens": model_token_budget(model, floor=1500),
                    }
                    if system_instruction:
                        payload["system"] = system_instruction

                    response = await client.post(
                        CLAUDE_URL,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                    content = data["content"][0]["text"]
                    self.last_usage = _usage_anthropic(data.get("usage"))
                    self.last_model = f"claude:{model}"
                    logger.info("Claude respondeu com o modelo %s", model)
                    return content
                except Exception as exc:
                    self.model_failures.append(f"claude:{model}")
                    logger.warning("Claude model %s failed: %s", model, exc)
                    last_error = exc
                    continue

        raise RuntimeError(f"Todos os modelos Claude falharam: {last_error}")
