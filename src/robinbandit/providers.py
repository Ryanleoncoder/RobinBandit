"""Fábrica executável do catálogo YAML do RobinBandit.

URL, tier, custo, prioridade, segredo referenciado e modelos vivem no YAML.
Este módulo apenas valida/resolve essas referências e monta os adaptadores.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .config import RobinConfig


class UnavailableProvider:
    """Alvo configurado, porém indisponível, preservando a política do modo.

    Em Reforçado a falha segue para o Router; em Dedicado a seleção estrita
    termina aqui. Isso impede que Dedicado sem chave vire Router em silêncio.
    """

    def __init__(self, name: str, reason: str):
        self.name = name
        self.models: List[str] = []
        self.last_model = None
        self.last_attempted_model = None
        self.last_quota = None
        self.model_failures: List[str] = []
        self._reason = reason

    async def complete(self, *args, **kwargs):
        raise RuntimeError(self._reason)

def _source_value(settings: Any, name: str, fallback_name: str = "") -> str:
    """Resolve referência sem expor o valor.

    Ordem: o que o chamador passou > cofre > ambiente. Quem monta o provedor
    com um `settings` na mão escolheu aquele valor; o ambiente é o padrão de
    quem não escolheu nada. Com o ambiente na frente, um `.env` carregado no
    processo sobrescrevia em silêncio a configuração explícita — e o mesmo
    código dava resultados diferentes conforme o que já estivesse carregado.
    """
    from . import secrets

    for candidate in (name, fallback_name):
        key = str(candidate or "").strip()
        if not key:
            continue
        value = ""
        if settings is not None:
            value = getattr(settings, key, "") or ""
        if not str(value).strip():
            value = secrets.ler(key) or os.environ.get(key, "")
        if str(value).strip():
            return str(value).strip()
    return ""


def _csv(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _allowed_models(spec: Dict[str, Any], models: List[str]) -> List[str]:
    """Remove IDs aposentados inclusive de overrides antigos do ambiente."""
    blocked = {str(item).strip() for item in spec.get("disabled_models") or []}
    return [model for model in models if model not in blocked]


def _configure_runtime(config: RobinConfig) -> None:
    from . import account_config, accounts, secrets

    accounts.vincular_config(config)
    secrets.configure(config.secrets)
    account_config.configure(config.secrets)


def build_provider(
    config: RobinConfig,
    key: str,
    settings: Any = None,
    *,
    models: Optional[List[str]] = None,
    name: Optional[str] = None,
    api_key: Optional[str] = None,
    model_role: Optional[str] = None,
):
    """Instancia um provedor inteiramente a partir do YAML Robin.

    `settings` é apenas uma fonte opcional de valores já carregados de `.env`;
    nenhum tipo do Sentury é importado ou conhecido pelo Robin.
    """
    _configure_runtime(config)
    provider_key = str(key or "").strip().lower()
    spec = dict(config.providers.get(provider_key) or {})
    if not spec:
        raise KeyError(f"provedor não declarado no Robin YAML: {provider_key}")
    if spec.get("enabled") is False:
        return None

    adapter = str(spec.get("adapter") or "openai").strip().lower()
    runtime_name = str(name or provider_key)
    configured_models = models
    if configured_models is None:
        role_prefix = f"{str(model_role).strip().lower()}_" if model_role else ""
        try:
            from .account_config import overrides_de_modelos
            from_panel = _allowed_models(
                spec, overrides_de_modelos().get(provider_key, [])
            )
        except Exception:
            from_panel = []
        from_env = _allowed_models(
            spec,
            _csv(_source_value(settings, str(spec.get(f"{role_prefix}models_env") or ""))),
        )
        configured_models = from_panel or from_env or _allowed_models(
            spec, config.provider_models(provider_key, model_role)
        )
    else:
        configured_models = _allowed_models(spec, configured_models)

    if adapter == "fallback":
        from .groq_provider import FallbackProvider
        provider = FallbackProvider()
        provider.name = runtime_name
        return provider

    if adapter == "claude_code":
        from .claude_code_provider import ClaudeCodeProvider, claude_code_auth_status

        binary = _source_value(settings, str(spec.get("binary_env") or "")) or str(
            spec.get("binary") or "claude"
        ).strip()
        if not claude_code_auth_status(binary).configured:
            return None
        provider = ClaudeCodeProvider(
            name=runtime_name,
            binary=binary,
            models=configured_models,
            timeout=float(spec.get("timeout", 300.0)),
        )
        return provider

    if adapter in {"codex", "codex_app_server"}:
        from .codex_provider import CodexProvider, codex_auth_status

        binary = _source_value(settings, str(spec.get("binary_env") or "")) or str(
            spec.get("binary") or "codex"
        ).strip()
        if not configured_models or not codex_auth_status(binary).configured:
            return None
        provider = CodexProvider(
            configured_models,
            binary=binary,
            timeout=float(spec.get("timeout", 180.0)),
        )
        provider.name = runtime_name
        return provider

    base_url = str(spec.get("base_url") or "").strip()
    base_from_env = _source_value(
        settings,
        str(spec.get("base_url_env") or ""),
        str(spec.get("base_url_fallback_env") or ""),
    )
    if base_from_env:
        base_url = base_from_env
    if api_key is None:
        api_key = _source_value(
            settings,
            str(spec.get("api_key_env") or ""),
            str(spec.get("api_key_fallback_env") or ""),
        )

    # Provedor remoto sem segredo não entra na cadeia. Mas gateway que roda na
    # própria máquina (Ollama, 9Router, OmniRoute, LiteLLM) não tem segredo
    # nenhum a exigir — e alguns ainda assim querem o header preenchido. Isso
    # era uma exceção escrita em código para o Ollama; virou declaração, senão
    # cada gateway novo pedia uma linha nova aqui.
    if not api_key and base_url and spec.get("chave_opcional"):
        api_key = str(spec.get("chave_fixa") or provider_key)
    if not api_key or not configured_models:
        return None

    if adapter == "groq":
        from .groq_provider import GroqProvider
        provider = GroqProvider(api_key, configured_models)
    elif adapter == "gemini":
        from .gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key, configured_models)
    elif adapter == "openrouter":
        from .openrouter_provider import OpenRouterProvider
        provider = OpenRouterProvider(api_key, configured_models)
    elif adapter in {"anthropic", "claude"}:
        from .claude_provider import ClaudeProvider
        provider = ClaudeProvider(api_key, configured_models)
    elif adapter == "openai":
        from .openai_compat import OpenAICompatProvider
        if not base_url:
            raise ValueError(f"providers.{provider_key}.base_url não configurada")
        provider = OpenAICompatProvider(
            runtime_name,
            base_url,
            api_key,
            configured_models,
            extra_headers=dict(spec.get("extra_headers") or {}),
            timeout=float(spec.get("timeout", 30.0)),
        )
    else:
        raise ValueError(f"adapter desconhecido para {provider_key}: {adapter}")
    provider.name = runtime_name
    return provider


def build_provider_set(config: RobinConfig, settings: Any = None) -> Dict[str, Any]:
    """Monta todos os provedores configurados, inclusive o fallback local."""
    _configure_runtime(config)
    out: Dict[str, Any] = {}
    for key in config.providers:
        provider = build_provider(config, key, settings)
        if provider is not None:
            out[key] = provider
    return out


def _dono_do_tier(config: RobinConfig, tier: str) -> str:
    """Quem declara este tier de seleção no YAML."""
    for chave, spec in config.providers.items():
        if str(spec.get("selection_tier") or "").strip().lower() == tier:
            return chave
        if tier in (spec.get("modelo_do_tier") or {}):
            return chave
    return ""


def build_tier_provider(
    config: RobinConfig,
    tier: str,
    settings: Any = None,
):
    """Monta Reforçado/Dedicado usando a conta efetivamente escolhida.

    A resolução ocorre por request. Assim trocar uma chave ou apontar o tier
    para outra conta no painel passa a valer sem reiniciar o processo.
    """
    from .accounts import catalogo_efetivo

    _configure_runtime(config)
    tier_key = str(tier or "").strip().lower()
    if tier_key not in {"ultra", "ultra_max"}:
        raise ValueError("tier deve ser ultra (Reforçado) ou ultra_max (Dedicado)")
    account = catalogo_efetivo(settings, config).conta_do_tier(tier_key)
    if account is None:
        # `ultra_max` não é mais um provedor: quem serve os dois tiers é a
        # conta paga declarada com `selection_tier`.
        alvo = tier_key if tier_key in config.providers else _dono_do_tier(config, tier_key)
        provider = build_provider(config, alvo, settings) if alvo else None
        return provider or UnavailableProvider(
            tier_key, f"{tier_key} não possui conta/credencial configurada"
        )
    source_key = tier_key if account.id == tier_key else account.provider
    if source_key not in config.providers:
        raise ValueError(
            f"conta '{account.id}' usa provedor '{source_key}' ausente no YAML Robin"
        )
    # Reforçado e Dedicado deixaram de ser dois provedores: são a mesma conta
    # paga com modelos diferentes, e o YAML diz qual é de quem. Sem isto, os
    # dois tiers pegariam o primeiro modelo da lista e ficariam idênticos.
    #
    # A conta vem primeiro: quem escolheu os modelos dela no painel tomou a
    # decisão mais recente, e o padrão do YAML não pode passar por cima.
    do_tier = str((config.providers.get(source_key) or {}).get("modelo_do_tier", {}).get(tier_key, "")).strip()
    models = list(account.models) or ([do_tier] if do_tier else config.provider_models(source_key))
    provider = build_provider(
        config,
        source_key,
        settings,
        models=models,
        name=tier_key,
        api_key=account.resolver_chave(),
    )
    return provider or UnavailableProvider(
        tier_key, f"conta '{account.id}' não possui credencial ou modelos válidos"
    )


def describe_from_config(config: RobinConfig, settings: Any = None) -> List[Dict[str, Any]]:
    """Visão segura do catálogo YAML; nunca devolve segredo."""
    descriptions: List[Dict[str, Any]] = []
    for key, spec in config.providers.items():
        try:
            from .account_config import overrides_de_modelos
            panel_models = _allowed_models(spec, overrides_de_modelos().get(key, []))
        except Exception:
            panel_models = []
        models_env = _source_value(settings, str(spec.get("models_env") or ""))
        models = panel_models or _allowed_models(spec, _csv(models_env)) or _allowed_models(
            spec, config.provider_models(key)
        )
        is_fallback = str(spec.get("adapter") or "") == "fallback"
        base = str(spec.get("base_url") or "") or _source_value(
            settings, str(spec.get("base_url_env") or "")
        )
        has_secret = bool(_source_value(
            settings,
            str(spec.get("api_key_env") or ""),
            str(spec.get("api_key_fallback_env") or ""),
        ))
        adapter = str(spec.get("adapter") or "").strip().lower()
        auth_type = str(spec.get("auth_type") or "").strip().lower()
        has_auth = False
        if adapter in {"codex", "codex_app_server"}:
            from .codex_provider import codex_auth_status
            binary = _source_value(settings, str(spec.get("binary_env") or "")) or str(
                spec.get("binary") or "codex"
            ).strip()
            has_auth = codex_auth_status(binary).configured
        elif adapter == "claude_code":
            from .claude_code_provider import claude_code_auth_status
            binary = _source_value(settings, str(spec.get("binary_env") or "")) or str(
                spec.get("binary") or "claude"
            ).strip()
            has_auth = claude_code_auth_status(binary).configured
        try:
            from .account_config import overrides_de_tier
            tier = int(overrides_de_tier().get(key, spec.get("tier", 2)))
        except Exception:
            tier = int(spec.get("tier", 2))
        if spec.get("catalog_visible") is False:
            continue
        descriptions.append({
            "key": key,
            "label": str(spec.get("label") or key),
            "icon": str(spec.get("icon") or ""),
            "tier": tier,
            "priority": int(spec.get("priority", 99)),
            "cost_class": str(spec.get("cost_class") or ""),
            "enabled": spec.get("enabled") is not False,
            "disabled_reason": str(spec.get("disabled_reason") or ""),
            "configured": spec.get("enabled") is not False and (is_fallback or bool(
                models and (has_secret or has_auth or (key == "ollama" and base))
            )),
            "auth_type": auth_type or ("api_key" if has_secret else ""),
            "models": models,
            "models_overridden": bool(panel_models),
            "kinds": list(spec.get("kinds") or ["text"]),
            # Gateway nao serve modelo: ele roteia para outros. Misturado aos
            # provedores, parece que o Sentury fala com ele como fala com a
            # Groq — e nao e isso que acontece.
            "categoria": str(spec.get("categoria") or "provedor"),
        })
    return descriptions
