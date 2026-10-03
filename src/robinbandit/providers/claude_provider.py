import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..catalog.token_budget import model_token_budget
from .recusa import RecusaDoModelo, recusa_anthropic

logger = logging.getLogger(__name__)

CLAUDE_URL = "https://api.anthropic.com/v1/messages"


def _texto_nativo(m: Dict[str, Any]) -> str:
    """Chamada de ferramenta e resposta `tool` viram texto para quem nao fala o
    formato nativo; mensagem vazia com `tool_calls` seria recusada."""
    if m.get("role") == "tool":
        return "[resultado de ferramenta]\n" + str(m.get("content") or "")
    texto = str(m.get("content") or "")
    for call in m.get("tool_calls") or []:
        fn = (call or {}).get("function") or {}
        texto += ("\n" if texto else "") + f"(chamei {fn.get('name')} com {fn.get('arguments') or '{}'})"
    return texto


def _blocos(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Uma mensagem no formato da Anthropic: texto, `tool_use` e `tool_result`.

    A API recusa bloco de texto vazio, entao ele so entra quando tem conteudo.
    """
    if m.get("role") == "tool":
        return [{"type": "tool_result", "tool_use_id": str(m.get("tool_call_id") or ""),
                 "content": str(m.get("content") or "")}]
    blocos: List[Dict[str, Any]] = []
    texto = str(m.get("content") or "")
    if texto.strip():
        blocos.append({"type": "text", "text": texto})
    for call in m.get("tool_calls") or []:
        fn = (call or {}).get("function") or {}
        argumentos = fn.get("arguments") or "{}"
        try:
            entrada = json.loads(argumentos) if isinstance(argumentos, str) else dict(argumentos)
        except (TypeError, ValueError):
            entrada = {}
        blocos.append({"type": "tool_use", "id": str((call or {}).get("id") or ""),
                       "name": str(fn.get("name") or ""), "input": entrada})
    return blocos


def _split_messages(messages: List[Dict[str, str]], nativo: bool = False) -> Tuple[Optional[str], List[Dict]]:
    """Converte o formato de mensagens para o formato do Anthropic Claude.
    Instruções do sistema vão para o parâmetro `system` no nível do payload.
    Mensagens consecutivas do mesmo papel são mescladas para respeitar a exigência
    de alternância de papéis (user/assistant).

    Com `nativo`, chamada e resultado de ferramenta viram blocos `tool_use` e
    `tool_result`; sem ele, texto.
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
        if nativo:
            blocos = _blocos(m)
            if not blocos:
                continue
            if formatted_messages and formatted_messages[-1]["role"] == a_role:
                formatted_messages[-1]["content"].extend(blocos)
            else:
                formatted_messages.append({"role": a_role, "content": blocos})
            continue

        if role == "tool" or m.get("tool_calls"):
            content = _texto_nativo(m)
        if formatted_messages and formatted_messages[-1]["role"] == a_role:
            formatted_messages[-1]["content"] += "\n\n" + content
        else:
            formatted_messages.append({"role": a_role, "content": content})

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, formatted_messages


def _ferramentas(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Esquema no formato da OpenAI (o que o orquestrador monta) para o da Anthropic."""
    saida = []
    for t in tools or []:
        fn = (t or {}).get("function") or t or {}
        nome = str(fn.get("name") or "").strip()
        if not nome:
            continue
        saida.append({
            "name": nome,
            "description": str(fn.get("description") or ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return saida


def _ler_resposta(data: Dict[str, Any]) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
    """Texto e chamadas de ferramenta, no formato da OpenAI que o laço lê."""
    textos, chamadas = [], []
    for bloco in data.get("content") or []:
        if bloco.get("type") == "text":
            textos.append(str(bloco.get("text") or ""))
        elif bloco.get("type") == "tool_use":
            chamadas.append({"id": str(bloco.get("id") or ""), "type": "function", "function": {
                "name": str(bloco.get("name") or ""),
                "arguments": json.dumps(bloco.get("input") or {}, ensure_ascii=False)}})
    return "".join(textos), (chamadas or None)


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

    # A API usa blocos nativos de chamada e resultado de ferramenta.
    supports_tools = True

    def __init__(self, api_key: str, models: List[str]):
        self.name = "claude"
        self.api_key = (api_key or "").strip()
        self.models = models or ["claude-sonnet-4-6"]
        self.last_model: Optional[str] = None
        self.last_reasoning_summary: Optional[str] = None
        self.last_tool_calls: Optional[List[Dict[str, Any]]] = None
        # Uso do último turno para contabilidade do painel.
        self.last_usage: Optional[Dict[str, int]] = None

    async def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2,
                       complexity: Optional[str] = None,
                       preferred_model: Optional[str] = None,
                       strict_model: bool = False,
                       tools: Optional[List[Dict[str, Any]]] = None) -> str:
        ferramentas = _ferramentas(tools or [])
        system_instruction, formatted_messages = _split_messages(messages, nativo=bool(ferramentas))
        last_error: Optional[Exception] = None
        self.last_reasoning_summary = None
        self.last_model = None
        self.last_tool_calls = None
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
                    if ferramentas:
                        payload["tools"] = ferramentas

                    response = await client.post(
                        CLAUDE_URL,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                    content, self.last_tool_calls = _ler_resposta(data)
                    recusa = recusa_anthropic(data, content)
                    if recusa is not None:
                        raise RecusaDoModelo(f"claude:{model}", recusa)
                    self.last_usage = _usage_anthropic(data.get("usage"))
                    self.last_model = f"claude:{model}"
                    logger.info("Claude respondeu com o modelo %s", model)
                    return content
                except RecusaDoModelo:
                    raise
                except Exception as exc:
                    self.model_failures.append(f"claude:{model}")
                    logger.warning("Claude model %s failed: %s", model, exc)
                    last_error = exc
                    continue

        raise RuntimeError(f"Todos os modelos Claude falharam: {last_error}") from last_error
