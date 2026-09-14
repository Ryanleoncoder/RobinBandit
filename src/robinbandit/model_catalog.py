"""Catalogo vivo e seguro de modelos dos providers.

O modulo pertence ao RobinBandit porque disponibilidade, custo e capacidades
fazem parte da decisao de roteamento. Nenhuma credencial atravessa o retorno.
"""
from __future__ import annotations

import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300


def _source_value(settings: Any, *names: str) -> str:
    from . import secrets

    for name in names:
        key = str(name or "").strip()
        if not key:
            continue
        value = secrets.ler(key) or os.environ.get(key, "")
        if not value and settings is not None:
            value = getattr(settings, key, "") or ""
        if str(value).strip():
            return str(value).strip()
    return ""


def _number(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _first_number(mapping: Dict[str, Any], names: Iterable[str]) -> Optional[Decimal]:
    for name in names:
        value = _number(mapping.get(name))
        if value is not None:
            return value
    return None


def _as_strings(value: Any) -> List[str]:
    if isinstance(value, dict):
        return [str(key) for key, enabled in value.items() if enabled]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return []


# Papel = para que o modelo serve. Um modelo pode servir a varios, e a lista
# cresce sem tocar na interface: as abas vem do que o catalogo declarar.
PAPEIS_CONHECIDOS = ("texto", "imagem", "audio", "transcricao", "embedding", "video")


def _papeis(
    model_id: str,
    input_modalities: List[str],
    output_modalities: List[str],
) -> List[str]:
    entrada = {item.lower() for item in input_modalities}
    saida = {item.lower() for item in output_modalities}
    nome = model_id.lower()
    papeis: List[str] = []

    if any(token in nome for token in ("embed", "embedding")):
        return ["embedding"]
    if any(token in nome for token in ("whisper", "transcribe", "stt")) or "audio" in entrada and not saida:
        papeis.append("transcricao")
    if "audio" in saida or any(token in nome for token in ("tts", "speech", "voice")):
        papeis.append("audio")
    if "image" in saida:
        papeis.append("imagem")
    if "video" in saida:
        papeis.append("video")
    if "audio" in entrada and "transcricao" not in papeis:
        papeis.append("transcricao")
    if not saida or "text" in saida:
        papeis.insert(0, "texto")
    return papeis or ["texto"]


def _normalizar(provider: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    model_id = str(raw.get("id") or raw.get("model") or "").strip()
    architecture = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
    top_provider = raw.get("top_provider") if isinstance(raw.get("top_provider"), dict) else {}
    pricing = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}

    prompt = _first_number(pricing, ("prompt", "input", "prompt_token"))
    completion = _first_number(pricing, ("completion", "output", "completion_token"))
    request = _first_number(pricing, ("request", "per_request"))
    known_prices = [value for value in (prompt, completion, request) if value is not None]
    if model_id.endswith(":free") or (known_prices and all(value == 0 for value in known_prices)):
        price_class = "free"
    elif any(value > 0 for value in known_prices):
        price_class = "paid"
    else:
        price_class = "unknown"

    input_modalities = _as_strings(raw.get("input_modalities") or architecture.get("input_modalities"))
    output_modalities = _as_strings(raw.get("output_modalities") or architecture.get("output_modalities"))
    supported = _as_strings(raw.get("supported_parameters")) + _as_strings(raw.get("supported_features"))
    lowered = {item.lower() for item in supported}
    capabilities: List[str] = []
    if any(item in lowered for item in ("tools", "tool_choice", "tool_use", "function_calling")):
        capabilities.append("tools")
    if any(item in lowered for item in ("reasoning", "include_reasoning")):
        capabilities.append("reasoning")
    if any(item in lowered for item in ("structured_outputs", "response_format", "json_mode")):
        capabilities.append("structured_output")
    if "image" in {item.lower() for item in input_modalities}:
        capabilities.append("vision")

    active = raw.get("active") is not False
    guard_only = any(token in model_id.lower() for token in ("guard", "safeguard"))
    papeis = _papeis(model_id, input_modalities, output_modalities)
    if "imagem" in papeis:
        capabilities.append("image_gen")
    if "audio" in papeis:
        capabilities.append("audio")
    if "embedding" in papeis:
        capabilities.append("embedding")

    def per_million(value: Optional[Decimal]) -> Optional[float]:
        return float(value * Decimal(1_000_000)) if value is not None else None

    return {
        "id": model_id,
        "name": str(raw.get("name") or model_id),
        "description": str(raw.get("description") or "")[:500],
        "price_class": price_class,
        "pricing": {
            "prompt_per_million": per_million(prompt),
            "completion_per_million": per_million(completion),
            "request": float(request) if request is not None else None,
        },
        "context_length": raw.get("context_length") or raw.get("context_window"),
        "max_output_tokens": raw.get("max_completion_tokens") or top_provider.get("max_completion_tokens"),
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
        "capabilities": capabilities,
        "expiration_date": raw.get("expiration_date"),
        "active": active,
        "selectable": bool(model_id and active and papeis and not guard_only),
        "roles": papeis,
        "provider": provider,
    }


def _fallback(config: Any, provider: str, warning: str) -> Dict[str, Any]:
    models = [
        {
            "id": model_id,
            "name": model_id,
            "description": "Modelo configurado localmente; disponibilidade ainda nao confirmada.",
            "price_class": "unknown",
            "pricing": {"prompt_per_million": None, "completion_per_million": None, "request": None},
            "context_length": None,
            "max_output_tokens": None,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "capabilities": [],
            "roles": ["texto"],
            "expiration_date": None,
            "active": True,
            "selectable": True,
            "provider": provider,
        }
        for model_id in config.provider_models(provider)
    ]
    return {
        "provider": provider,
        "source": "configured",
        "fetched_at": time.time(),
        "models": models,
        "warnings": [warning],
    }


def precos_conhecidos() -> Dict[str, Dict[str, Any]]:
    """Preco por modelo, a partir do que ja foi buscado ao vivo.

    So conhece o que o catalogo trouxe: nada de tabela fixa que envelhece
    sozinha e vira numero errado na tela.
    """
    saida: Dict[str, Dict[str, Any]] = {}
    for entrada in _CACHE.values():
        for modelo in entrada.get("models", []):
            preco = modelo.get("pricing") or {}
            if preco.get("prompt_per_million") is not None or preco.get("completion_per_million") is not None:
                saida[str(modelo.get("id"))] = preco
    return saida


async def fetch_model_catalog(
    config: Any,
    provider: str,
    settings: Any = None,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Busca e normaliza o catalogo OpenRouter/Groq com cache de cinco minutos."""
    key = str(provider or "").strip().lower()
    if key not in {"openrouter", "groq"}:
        return _fallback(config, key, "Este provedor ainda nao expoe catalogo vivo; exibindo a configuracao local.")
    cached = _CACHE.get(key)
    if not force and cached and time.time() - float(cached["fetched_at"]) < _CACHE_TTL_SECONDS:
        return {**cached, "models": [dict(item) for item in cached["models"]]}

    spec = dict(config.providers.get(key) or {})
    base_url = str(spec.get("base_url") or "").rstrip("/")
    api_key = _source_value(settings, str(spec.get("api_key_env") or ""))
    if key == "groq" and not api_key:
        return _fallback(config, key, "Groq precisa de uma chave configurada para consultar /models.")

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # Sem filtro de modalidade: modelos de imagem tambem sao escolhiveis, por papel.
    params = {"sort": "most-popular"} if key == "openrouter" else None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{base_url}/models", headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
        raw_models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raise ValueError("resposta sem lista data")
        models = [_normalizar(key, item) for item in raw_models if isinstance(item, dict)]
        models = [item for item in models if item["selectable"]]
        result = {
            "provider": key,
            "source": "live",
            "fetched_at": time.time(),
            "models": models,
            "warnings": [],
        }
        _CACHE[key] = result
        return {**result, "models": [dict(item) for item in models]}
    except Exception as exc:
        return _fallback(config, key, f"Catalogo ao vivo indisponivel ({type(exc).__name__}); exibindo configuracao local.")

