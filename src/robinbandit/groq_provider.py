import json
import logging
from typing import Dict, List, Optional

import httpx

from .credentials import KeyRotator, parse_keys, is_quota_error
from .token_budget import model_token_budget

logger = logging.getLogger(__name__)


def _normalizar_usage(bruto):
    """Contagem de tokens do provedor, no formato OpenAI."""
    if not isinstance(bruto, dict):
        return None
    entrada = int(bruto.get("prompt_tokens") or 0)
    saida = int(bruto.get("completion_tokens") or 0)
    total = int(bruto.get("total_tokens") or (entrada + saida))
    if not total:
        return None
    usado = {"entrada": entrada, "saida": saida, "total": total}
    # Cache de prefixo no formato OpenAI (usado tambem pelo OpenRouter e pelo
    # Groq). Nem todo provedor informa; quem nao informa fica sem o campo, em
    # vez de aparecer com zero como se tivesse medido e dado zero.
    detalhe = bruto.get("prompt_tokens_details")
    cacheado = int((detalhe or {}).get("cached_tokens") or 0) if isinstance(detalhe, dict) else 0
    # Anthropic usa outro nome, e por ele passa tanto o OpenRouter quanto o
    # provedor direto.
    cacheado = cacheado or int(bruto.get("cache_read_input_tokens") or 0)
    if cacheado:
        usado["cacheado"] = cacheado
    custo = bruto.get("cost")
    try:
        if custo is not None and float(custo) >= 0:
            usado["custo_usd"] = float(custo)
    except (TypeError, ValueError):
        pass
    return usado

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# No Groq o effort aceito varia POR MODELO (console.groq.com/docs/reasoning).
# Mandar valor incompatível custa um retry — justo a latência que queremos
# cortar. Modelo fora da tabela: não manda nada.
GROQ_REASONING_EFFORTS = {
    "openai/gpt-oss-20b": {"low", "medium", "high"},
    "openai/gpt-oss-120b": {"low", "medium", "high"},
    "qwen/qwen3-32b": {"none", "default"},
}


def _groq_effort(model: str, effort: Optional[str]) -> Optional[str]:
    if not effort:
        return None
    aceitos = GROQ_REASONING_EFFORTS.get(model)
    if not aceitos:
        return None
    if effort in aceitos:
        return effort
    # xhigh não existe no Groq: rebaixa pro maior que o modelo aceita.
    if effort == "xhigh" and "high" in aceitos:
        return "high"
    return None


class GroqProvider:
    """O Harness nunca depende de uma única LLM: troca de modelo (ou,
    futuramente, de provedor) sem mudar nenhuma regra do Harness."""

    supports_tools = True

    def __init__(self, api_key: str, models: List[str]):
        self.name = "groq"
        # Pool de credenciais: 1 chave ou CSV ("k1,k2,k3").
        self._keys = KeyRotator(parse_keys(api_key))
        self.models = models or ["llama-3.1-8b-instant"]
        self.last_model: Optional[str] = None
        self.last_usage = None
        self.last_reasoning_summary: Optional[str] = None

    async def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2, complexity: Optional[str] = None,
                       preferred_model: Optional[str] = None, tools: Optional[list] = None,
                       reasoning_effort: Optional[str] = None,
                       strict_model: bool = False) -> str:
        last_error: Optional[Exception] = None
        self.last_reasoning_summary = None
        self.last_model = None
        self.last_attempted_model = None
        self.model_failures = []
        self.last_tool_calls = None  # native function-calling (A2b), Groq é OpenAI-compat
        is_classify = (complexity or "").upper() == "CLASSIFY"

        # Reordena os modelos com base na complexidade (Troca Inteligente de Modelos)
        models_to_try = list(self.models)
        if complexity in ("SIMPLE", "STANDARD") and len(models_to_try) > 1:
            lightweight = [m for m in models_to_try if "8b" in m or "instant" in m]
            if lightweight:
                for m in lightweight:
                    models_to_try.remove(m)
                models_to_try = lightweight + models_to_try
        # Perfil (ex.: coding → gpt-oss-120b): tenta o preferido primeiro.
        if preferred_model and strict_model:
            models_to_try = [preferred_model]
        elif preferred_model:
            models_to_try = [preferred_model] + [m for m in models_to_try if m != preferred_model]
                
        async with httpx.AsyncClient(timeout=20.0) as client:
            for key in self._keys.order():
                cota_na_chave = False
                for model in models_to_try:
                    self.last_attempted_model = f"groq:{model}"
                    try:
                        payload = {
                            "model": model,
                            "messages": messages,
                            "temperature": temperature,
                            # Teto dinâmico por modelo (folga p/ raciocínio + código).
                            "max_tokens": min(model_token_budget(model), 512) if is_classify else model_token_budget(model),
                        }
                        if tools:
                            payload["tools"] = tools
                            payload["tool_choice"] = "auto"
                        efforce = _groq_effort(model, reasoning_effort)
                        if efforce:
                            payload["reasoning_effort"] = efforce
                        response = await client.post(
                            GROQ_URL,
                            headers={"Authorization": f"Bearer {key}"},
                            json=payload,
                        )
                        response.raise_for_status()
                        data = response.json()
                        self.last_usage = _normalizar_usage(data.get("usage"))
                        message = data["choices"][0]["message"]
                        self.last_tool_calls = message.get("tool_calls")
                        from .openai_compat import _extract_reasoning
                        self.last_reasoning_summary = _extract_reasoning(message)
                        self.last_model = f"groq:{model}"
                        logger.info("Groq respondeu com o modelo %s", model)
                        return message.get("content") or ""
                    except Exception as exc:
                        self.model_failures.append(f"groq:{model}")
                        logger.warning("Groq model %s failed: %s", model, exc)
                        last_error = exc
                        if is_quota_error(exc):
                            cota_na_chave = True
                            break
                        continue
                if cota_na_chave and self._keys.has_multiple:
                    continue
        raise RuntimeError(f"Todos os modelos/chaves Groq falharam: {last_error}")


class FallbackProvider:
    """Não é um provedor: é o aviso de que nenhum respondeu.

    Só é alcançado quando todos os reais falharam, ou quando nenhuma chave
    existe. Devolve texto simples e marca `é_aviso` para quem receber saber
    que isto não é uma resposta de modelo — um aviso disfarçado de resposta é
    pior que um erro, porque o agente segue como se tivesse sido atendido.

    Não afirma "falta a chave" (pode estar tudo certo) e não inventa número
    nenhum.
    """

    name = "fallback"
    last_model = "aviso (nenhum provedor respondeu)"
    # Quem monta a cadeia pode olhar isto antes de tratar a saída como resposta.
    e_aviso = True

    async def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2, complexity: Optional[str] = None) -> str:
        return (
            "Nenhum provedor de IA respondeu agora — provavelmente limite de uso "
            "temporário. Tente de novo em alguns instantes. Se persistir, veja as "
            "chaves e os limites dos provedores configurados."
        )
