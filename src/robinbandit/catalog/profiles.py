"""Perfis de tarefa universais para o gateway de modelos do RobinBandit.

Um "perfil" (analysis | artifact | coding | fallback) é uma preferência de
`provider:model` para um TIPO de tarefa. É uma camada SUAVE sobre o gateway
provider-cêntrico atual: quando um perfil é passado, o roteador dá um bônus de
score aos provedores preferidos daquele perfil — sem quebrar o cooldown/bandit/
saúde já existentes. Sem perfil, o comportamento é idêntico ao de hoje.

As listas vêm do .env (SENTURY_{ANALYSIS,ARTIFACT,CODING,FALLBACK}_MODELS) no
formato CSV `provider:model`; quando vazio, cai no DEFAULT_PROFILE_MODELS abaixo.
"""
from __future__ import annotations

from typing import Dict, List

ProfileTargets = List[Dict[str, str]]

DEFAULT_PROFILE_MODELS: Dict[str, ProfileTargets] = {
    "classify": [
        {"provider": "groq", "model": "llama-3.1-8b-instant"},
        {"provider": "gemini", "model": "gemini-2.5-flash-lite"},
    ],
    "analysis": [
        {"provider": "groq", "model": "openai/gpt-oss-120b"},
        {"provider": "groq", "model": "qwen/qwen3-32b"},
        {"provider": "gemini", "model": "gemini-3.5-flash"},
    ],
    "artifact": [
        {"provider": "gemini", "model": "gemini-2.5-flash"},
        {"provider": "groq", "model": "openai/gpt-oss-120b"},
    ],
    "coding": [
        # Antigravity (modelo agêntico de código do Google) como primário do
        # perfil coding. Cota-preview pequena → ao bater 429 o roteador cai pro
        # openrouter/free (200k de contexto). Os ids antigos do OpenRouter
        # (qwen3-coder:free, gpt-oss-120b:free, llama-3.3-70b:free) foram
        # aposentados: conferido contra o catálogo vivo em 2026-09-09.
        {"provider": "gemini", "model": "antigravity-preview-05-2026"},
        {"provider": "openrouter", "model": "openrouter/free"},
        {"provider": "groq", "model": "openai/gpt-oss-120b"},
        {"provider": "deepinfra", "model": "deepseek-ai/DeepSeek-V3"},
    ],
    "fallback": [
        {"provider": "groq", "model": "llama-3.1-8b-instant"},
        {"provider": "gemini", "model": "gemini-2.5-flash-lite"},
    ],
}


def parse_profile_targets(raw: str | None) -> ProfileTargets:
    """Parse CSV `provider:model` → lista de {provider, model}. Ignora entradas
    inválidas (sem `:`, provider ou model vazios). Preserva o `:` do model
    (ex.: `openrouter/free`) porque só o PRIMEIRO `:` separa."""
    out: ProfileTargets = []
    for chunk in (raw or "").split(","):
        item = chunk.strip()
        if not item or ":" not in item:
            continue
        provider, model = item.split(":", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if not provider or not model:
            continue
        out.append({"provider": provider, "model": model})
    return out


# Mapa ATIVO de perfis. Por padrão é o DEFAULT; no startup o main.py injeta o
# resolvido do .env (set_active_profiles(resolve_profile_models(settings))), pra
# os SENTURY_*_MODELS realmente valerem no roteamento.
_ACTIVE_PROFILE_MODELS: Dict[str, ProfileTargets] | None = None


def set_active_profiles(mapping: Dict[str, ProfileTargets] | None) -> None:
    global _ACTIVE_PROFILE_MODELS
    _ACTIVE_PROFILE_MODELS = mapping or None


def active_profile_models() -> Dict[str, ProfileTargets]:
    """Mapa em uso agora: o do .env (se injetado) ou o DEFAULT."""
    return _ACTIVE_PROFILE_MODELS if _ACTIVE_PROFILE_MODELS is not None else DEFAULT_PROFILE_MODELS


def preferred_model_for(profile: str | None, provider_key: str) -> str | None:
    """Primeiro modelo que o perfil prefere PARA aquele provedor (ou None).
    É o que faz o modelo certo ser chamado: ex.: coding+gemini → antigravity.
    Sem perfil = None (o provedor usa a ordem normal da lista dele)."""
    if not profile:
        return None
    for item in active_profile_models().get(profile, []):
        if item["provider"] == provider_key:
            return item["model"]
    return None


def resolve_profile_models(settings, defaults: Dict[str, ProfileTargets] | None = None) -> Dict[str, ProfileTargets]:
    """Mapa perfil → targets: usa o .env quando presente, senão o default."""
    base = defaults or DEFAULT_PROFILE_MODELS
    env_map = {
        "classify": getattr(settings, "SENTURY_CLASSIFY_MODELS", ""),
        "analysis": getattr(settings, "SENTURY_ANALYSIS_MODELS", ""),
        "artifact": getattr(settings, "SENTURY_ARTIFACT_MODELS", ""),
        "coding": getattr(settings, "SENTURY_CODING_MODELS", ""),
        "fallback": getattr(settings, "SENTURY_FALLBACK_MODELS", ""),
    }
    resolved: Dict[str, ProfileTargets] = {}
    for profile, raw in env_map.items():
        parsed = parse_profile_targets(raw)
        resolved[profile] = parsed or list(base.get(profile) or DEFAULT_PROFILE_MODELS[profile])
    return resolved
