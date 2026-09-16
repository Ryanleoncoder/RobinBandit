"""Fábrica executável do catálogo YAML do RobinBandit.

URL, tier, custo, prioridade, segredo referenciado e modelos vivem no YAML.
Este módulo apenas valida/resolve essas referências e monta os adaptadores.
"""
from __future__ import annotations

import inspect
import os
from typing import Any, Dict, List, Optional

from ..config import RobinConfig


class UnavailableProvider:
    """Alvo configurado, porém indisponível."""

    def __init__(self, name: str, reason: str):
        self.supports_tools = False
        self.name = name
        self.models: List[str] = []
        self.last_model = None
        self.last_attempted_model = None
        self.last_quota = None
        self.model_failures: List[str] = []
        self._reason = reason

    async def complete(self, *args, **kwargs):
        raise RuntimeError(self._reason)


class ReinforcedProvider:
    """Tenta uma fila explícita de contas antes de devolver ao Router."""

    def __init__(self, providers: List[Any], name: str = "ultra"):
        self.name = name
        self.providers = [p for p in providers if p is not None]
        self.models: List[str] = []
        self.last_model = None
        self.last_provider = None
        self.last_usage = None
        self.last_quota = None
        self.last_attempted_model = None
        self.last_reasoning_summary = None
        self.last_tool_calls = None
        self.model_failures: List[str] = []

    @staticmethod
    def _suporta_ferramentas(provider) -> bool:
        declarado = getattr(provider, "supports_tools", None)
        if declarado is not None:
            return bool(declarado)
        try:
            parametros = inspect.signature(provider.complete).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parametro.name == "tools"
            or parametro.kind is inspect.Parameter.VAR_KEYWORD
            for parametro in parametros
        )

    @property
    def supports_tools(self) -> bool:
        return any(self._suporta_ferramentas(provider) for provider in self.providers)

    async def complete(self, messages, temperature: float = 0.2, **kwargs):
        self.last_model = None
        self.last_provider = None
        self.last_usage = None
        self.last_quota = None
        self.model_failures = []
        ultimo_erro = None
        for provider in self.providers:
            if kwargs.get("tools") and not self._suporta_ferramentas(provider):
                continue
            try:
                parametros = inspect.signature(provider.complete).parameters
                aceita_tudo = any(
                    p.kind is inspect.Parameter.VAR_KEYWORD
                    for p in parametros.values()
                )
                extras = {
                    chave: valor for chave, valor in kwargs.items()
                    if aceita_tudo or chave in parametros
                }
                resposta = await provider.complete(messages, temperature, **extras)
                self.last_provider = getattr(provider, "name", type(provider).__name__)
                for atributo in (
                    "last_model", "last_usage", "last_quota", "last_attempted_model",
                    "last_reasoning_summary", "last_tool_calls",
                ):
                    setattr(self, atributo, getattr(provider, atributo, None))
                self.model_failures.extend(
                    list(getattr(provider, "model_failures", []) or [])
                )
                return resposta
            except Exception as exc:
                ultimo_erro = exc
                self.model_failures.extend(
                    list(getattr(provider, "model_failures", []) or [])
                )
        raise RuntimeError("nenhuma conta do Reforçado respondeu") from ultimo_erro

def _source_value(settings: Any, name: str, fallback_name: str = "") -> str:
    """Resolve referência de segredo sem expor o valor."""
    from ..accounts import secrets

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
    from ..accounts import account_config, secrets; from .. import accounts

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
            from ..accounts.account_config import overrides_de_modelos
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
        provider = OpenRouterProvider(
            api_key,
            configured_models,
            extra_headers=dict(spec.get("extra_headers") or {}),
        )
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
    from ..accounts import account_config

    # Um endpoint publico sem chave nao prova que a pessoa escolheu usa-lo.
    # Sem esta guarda, `chave_opcional` bastava para o LLM7 entrar sozinho na
    # cadeia, embora ele esteja fora do `chain_order` de fabrica. Credencial
    # explicita ou participacao escolhida continuam sendo opt-in suficiente.
    escolhidos = set(account_config.cadeia() or config.chain_order)
    out: Dict[str, Any] = {}
    for key, spec in config.providers.items():
        if spec.get("opt_in") and key not in escolhidos:
            tem_credencial = _source_value(
                settings,
                str(spec.get("api_key_env") or ""),
                str(spec.get("api_key_fallback_env") or ""),
            )
            if not tem_credencial:
                continue
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
    """Monta Reforçado/Dedicado usando as contas efetivamente escolhidas.

    A resolução ocorre por request. Assim trocar uma chave ou apontar o tier
    para outra conta no painel passa a valer sem reiniciar o processo.
    """
    from ..accounts import account_config
    from ..accounts import catalogo_efetivo

    _configure_runtime(config)
    tier_key = str(tier or "").strip().lower()
    if tier_key not in {"ultra", "ultra_max"}:
        raise ValueError("tier deve ser ultra (Reforçado) ou ultra_max (Dedicado)")

    catalogo = catalogo_efetivo(settings, config)
    modo = "reforcado" if tier_key == "ultra" else "dedicado"
    alvos = account_config.selecao_do_modo(modo)
    if not alvos:
        return UnavailableProvider(
            tier_key,
            f"{modo} não configurado: escolha provedor/conta e ao menos um modelo",
        )

    montados = []
    for alvo in alvos:
        conta = catalogo.obter(alvo["conta"])
        if conta is None:
            montados.append(UnavailableProvider(
                str(alvo["conta"]), f"conta '{alvo['conta']}' não existe",
            ))
            continue
        source_key = tier_key if conta.id == tier_key else conta.provider
        if source_key not in config.providers:
            raise ValueError(
                f"conta '{conta.id}' usa provedor '{source_key}' ausente no YAML Robin"
            )
        models = list(alvo.get("modelos") or [])
        runtime_name = conta.id
        provider = build_provider(
            config,
            source_key,
            settings,
            models=models,
            name=runtime_name,
            api_key=conta.resolver_chave(),
        )
        montados.append(provider or UnavailableProvider(
            runtime_name,
            f"conta '{conta.id}' não possui credencial ou modelos válidos",
        ))

    # O grupo apenas tenta os alvos escolhidos, em ordem. Quem decide se uma
    # falha volta ao Router é a seleção externa: Reforçado é híbrido;
    # Dedicado é estrito e portanto termina depois deste grupo.
    return ReinforcedProvider(montados, name=tier_key)


def describe_from_config(config: RobinConfig, settings: Any = None) -> List[Dict[str, Any]]:
    """Visão segura do catálogo YAML; nunca devolve segredo."""
    descriptions: List[Dict[str, Any]] = []
    for key, spec in config.providers.items():
        try:
            from ..accounts.account_config import overrides_de_modelos
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
            from ..accounts.account_config import overrides_de_tier
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
