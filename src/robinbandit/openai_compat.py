import logging
from typing import Any, Dict, List, Optional

import httpx

from .credentials import KeyRotator, parse_keys, is_quota_error
from .reasoning import (
    build_reasoning_payload,
    is_reasoning_rejection,
    mark_reasoning_control_rejected,
    reasoning_control_allowed,
)
from .token_budget import model_token_budget

logger = logging.getLogger(__name__)


def _normalizar_usage(bruto) -> Optional[Dict[str, int]]:
    """Contagem de tokens do provedor, no formato OpenAI."""
    if not isinstance(bruto, dict):
        return None
    entrada = bruto.get("prompt_tokens") or bruto.get("input_tokens") or 0
    saida = bruto.get("completion_tokens") or bruto.get("output_tokens") or 0
    total = bruto.get("total_tokens") or (int(entrada) + int(saida))
    if not total:
        return None
    usado = {"entrada": int(entrada), "saida": int(saida), "total": int(total)}
    # Parte da entrada servida de cache. Cada provedor chama de um jeito:
    # `prompt_tokens_details.cached_tokens` no formato OpenAI (e no OpenRouter),
    # `cache_read_input_tokens` na Anthropic. Quem nao informa fica sem o campo,
    # em vez de aparecer com zero como se tivesse medido.
    detalhe = bruto.get("prompt_tokens_details")
    cacheado = int((detalhe or {}).get("cached_tokens") or 0) if isinstance(detalhe, dict) else 0
    cacheado = cacheado or int(bruto.get("cache_read_input_tokens") or 0)
    if cacheado:
        usado["cacheado"] = cacheado
    return usado


def _parse_quota(headers: Any) -> Optional[Dict[str, Optional[int]]]:
    """Lê o quanto de cota sobrou dos headers de rate-limit (quando o provedor
    expõe). Nomes variam (Groq/OpenRouter usam x-ratelimit-remaining-*); pegamos
    o que der.

    Isto NÃO é só para o painel: alimenta o `_quota_penalty` do roteador, que
    tira prioridade de quem está perto do limite ANTES do 429 chegar. Continua
    best-effort — provedor que não expõe o header simplesmente não é penalizado,
    e nada disso pode quebrar a resposta.
    """
    if not headers:
        return None

    def _int(*names: str) -> Optional[int]:
        for n in names:
            v = headers.get(n)
            if v is None:
                continue
            try:
                return int(float(str(v).strip()))
            except (TypeError, ValueError):
                continue
        return None

    rpm = _int("x-ratelimit-remaining-requests", "x-ratelimit-remaining", "ratelimit-remaining")
    rpd = _int("x-ratelimit-remaining-requests-day", "x-ratelimit-remaining-day")
    if rpm is None and rpd is None:
        return None
    return {"rpm": rpm, "rpd": rpd}


def _extract_reasoning(message: Dict[str, Any]) -> Optional[str]:
    """Extrai o raciocínio (<think>) da mensagem no formato OpenAI/OpenRouter.
    Modelos de raciocínio (deepseek etc.) devolvem em `reasoning` (string) ou
    `reasoning_details` (lista de blocos com `text`/`summary`). Best-effort."""
    if not isinstance(message, dict):
        return None
    raw = message.get("reasoning")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:2400]
    details = message.get("reasoning_details") or message.get("reasoning_content")
    if isinstance(details, str) and details.strip():
        return details.strip()[:2400]
    if isinstance(details, list):
        partes = []
        for bloco in details:
            if isinstance(bloco, dict):
                txt = bloco.get("text") or bloco.get("summary") or bloco.get("content")
                if isinstance(txt, str) and txt.strip():
                    partes.append(txt.strip())
            elif isinstance(bloco, str) and bloco.strip():
                partes.append(bloco.strip())
        if partes:
            return " ".join(partes)[:2400]

    # Fallback: extrai do content se houver tags <think>
    content = message.get("content")
    if isinstance(content, str) and "<think>" in content.lower():
        start = content.lower().find("<think>")
        end = content.lower().find("</think>")
        if start != -1:
            if end != -1:
                return content[start + 7:end].strip()[:2400]
            else:
                return content[start + 7:].strip()[:2400]

    return None


class OpenAICompatProvider:
    """Provedor genérico para qualquer API compatível com o formato OpenAI
    Chat Completions (`POST {base_url}/chat/completions`, mensagens `role`/`content`,
    resposta em `choices[0].message.content`).

    Um só código cobre Cerebras, GitHub Models, Hugging Face (router), SambaNova,
    Mistral e Cohere (endpoint de compatibilidade) — é a mesma ideia do LiteLLM:
    o que muda entre provedores é só a URL base, a chave e a lista de modelos.
    Mesma interface do GroqProvider/OpenRouterProvider: tenta cada modelo da
    lista na ordem até um responder, e expõe `last_model` pro painel de debug.

    O `name` vira o prefixo do `last_model` (ex.: "cerebras:llama-3.3-70b") e
    aparece nos logs — é como o resto do sistema sabe QUEM respondeu."""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        models: List[str],
        extra_headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ):
        self.name = name
        # normaliza: aceita base com ou sem barra final, com ou sem /chat/completions
        base = (base_url or "").rstrip("/")
        if base.endswith("/chat/completions"):
            self.url = base
        else:
            self.url = f"{base}/chat/completions"
        # Pool de credenciais: api_key pode ser 1 chave ou CSV ("k1,k2,k3").
        self._keys = KeyRotator(parse_keys(api_key))
        self.models = [m for m in (models or []) if m]
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self.last_model: Optional[str] = None
        self.last_reasoning_summary: Optional[str] = None
        self.last_quota: Optional[Dict[str, Optional[int]]] = None
        # Tokens do ultimo turno. Sem isto nao existe custo honesto na tela.
        self.last_usage: Optional[Dict[str, int]] = None

    async def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2,
                       complexity: Optional[str] = None, preferred_model: Optional[str] = None,
                       tools: Optional[list] = None, reasoning_effort: Optional[str] = None,
                       strict_model: bool = False) -> str:
        if not self.models:
            raise RuntimeError(f"{self.name}: nenhum modelo configurado")
        last_error: Optional[Exception] = None
        self.last_reasoning_summary = None
        self.last_model = None
        self.last_attempted_model = None
        self.model_failures = []
        # Native function-calling (A2b): populado se o modelo devolver tool_calls.
        # Só ativa quando o caller passa `tools=` (atrás de flag). Default: intacto.
        self.last_tool_calls = None
        self.last_truncated = False
        is_classify = (complexity or "").upper() == "CLASSIFY"
        # Perfil (ex.: coding → qwen3-coder): tenta o preferido primeiro.
        models_to_try = list(self.models)
        if preferred_model and strict_model:
            models_to_try = [preferred_model]
        elif preferred_model:
            models_to_try = [preferred_model] + [m for m in models_to_try if m != preferred_model]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # rotaciona as chaves (round-robin espalha; failover se uma bater cota)
            for key in self._keys.order():
                headers = {"Authorization": f"Bearer {key}", **self.extra_headers}
                cota_na_chave = False
                for model in models_to_try:
                  self.last_attempted_model = f"{self.name}:{model}"
                  # 2ª volta só acontece se o modelo recusar o controle de raciocínio.
                  for _ in range(2):
                    try:
                        controla_think = ("openrouter.ai" in self.url
                                          and reasoning_control_allowed(model))
                        payload = {
                            "model": model,
                            "messages": messages,
                            "temperature": temperature,
                            # Classify deve ser curto e sem think; demais fluxos mantem teto dinamico.
                            "max_tokens": min(model_token_budget(model), 512) if is_classify else model_token_budget(model),
                        }
                        if is_classify and controla_think:
                            # Trio legado já provado em prod pro classify — não mexer.
                            payload.update({
                                "reasoning_effort": "none",
                                "include_reasoning": False,
                                "reasoning": {"enabled": False, "exclude": True},
                            })
                        elif reasoning_effort and controla_think:
                            payload.update(build_reasoning_payload(reasoning_effort))
                        if tools:
                            payload["tools"] = tools
                            payload["tool_choice"] = "auto"
                        response = await client.post(
                            self.url,
                            headers=headers,
                            json=payload,

                        )
                        # Modelo que exige raciocínio (gpt-oss: "Reasoning is mandatory")
                        # devolve 400. Reenvia sem o controle e nunca mais tenta nele —
                        # senão o usuário no 'Leve' perde o turno inteiro (no Ultra não
                        # há fallback pra outro provedor).
                        if response.status_code == 400 and controla_think and is_reasoning_rejection(response.text):
                            mark_reasoning_control_rejected(model)
                            logger.info("%s: modelo %s nao aceita controle de raciocinio; reenviando sem.",
                                        self.name, model)
                            continue
                        response.raise_for_status()
                        self.last_quota = _parse_quota(response.headers)
                        data = response.json()
                        self.last_usage = _normalizar_usage(data.get("usage"))
                        escolha = data["choices"][0]
                        message = escolha["message"]
                        content = message.get("content") or ""
                        # `max_tokens` é um teto DURO: ao bater nele o modelo para
                        # no meio da frase (às vezes no meio da palavra, porque o
                        # corte é por token, não por palavra) e a resposta chega
                        # como se estivesse completa. Sem olhar o finish_reason a
                        # gente entrega texto cortado sem saber.
                        self.last_truncated = escolha.get("finish_reason") == "length"
                        if self.last_truncated:
                            logger.warning("%s: modelo %s bateu no teto de tokens (%s) e a resposta "
                                           "foi cortada.", self.name, model, payload["max_tokens"])
                        # Resposta de tool-call nativo vem com content vazio + tool_calls:
                        # nesse caso não é erro. Captura os tool_calls pro caller ler.
                        self.last_tool_calls = message.get("tool_calls")
                        if not content.strip() and not self.last_tool_calls:
                            # "reasoning" às vezes devolve content vazio — tenta o próximo.
                            raise RuntimeError(f"modelo {model} devolveu content vazio")
                        # Captura o <think> real do modelo (deepseek/OpenRouter devolve
                        # em `reasoning` ou `reasoning_details`) → surfaça como narração
                        # ao vivo e vai pra Deliberação.
                        self.last_reasoning_summary = _extract_reasoning(message)
                        self.last_model = f"{self.name}:{model}"
                        logger.info("%s respondeu com o modelo %s", self.name, model)
                        return content
                    except Exception as exc:
                        self.model_failures.append(f"{self.name}:{model}")
                        logger.warning("%s modelo %s falhou: %s", self.name, model, exc)
                        last_error = exc
                        if is_quota_error(exc):
                            # essa CHAVE está sem cota/crédito: não insiste nos outros
                            # modelos dela — pula direto pra próxima chave.
                            cota_na_chave = True
                        break  # sai do retry de raciocínio; próximo modelo
                  if cota_na_chave:
                      break
                if cota_na_chave and self._keys.has_multiple:
                    continue  # próxima chave
        raise RuntimeError(f"Todos os modelos/chaves {self.name} falharam: {last_error}")
