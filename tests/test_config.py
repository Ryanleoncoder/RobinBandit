from pathlib import Path

import pytest

from robinbandit import RobinConfig, RobinGateway, RouteSelection
from robinbandit.providers import (
    UnavailableProvider,
    build_provider,
    build_provider_set,
    build_tier_provider,
    describe_from_config,
)


ROOT = Path(__file__).resolve().parents[1]


def test_openrouter_usa_atribuicao_do_host_sem_render_antigo():
    config = RobinConfig.from_mapping({
        "providers": {
            "openrouter": {
                "adapter": "openrouter",
                "models": ["openrouter/free"],
                "extra_headers": {"X-OpenRouter-Title": "Meu host"},
            },
        },
    })

    provider = build_provider(config, "openrouter", api_key="segredo")

    assert provider.extra_headers == {"X-OpenRouter-Title": "Meu host"}
    assert "onrender.com" not in repr(provider.extra_headers)


def test_carrega_yaml_sentury_e_preserva_catalogo():
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    assert config.agent_mode == "sentury"
    assert config.last_resort == "fallback"
    assert config.providers["groq"]["cost_class"] == "free_preferred"
    assert config.weights["analysis:CRITICAL"] == (0.60, 0.15, 0.25)
    assert config.strategy == "adaptive"
    assert config.chain_order[-1] == "fallback"
    assert config.providers["groq"]["adapter"] == "groq"
    assert config.provider_models("groq", "planner")[0] == "openai/gpt-oss-120b"
    assert config.providers["deepinfra"]["base_url"].startswith("https://")
    assert config.profiles["coding"][2] == {
        "provider": "openrouter", "model": "openrouter/free"
    }
    assert config.profiles["chat"] == [
        {"provider": "groq", "model": "openai/gpt-oss-20b"},
        {"provider": "gemini", "model": "gemini-2.5-flash-lite"},
    ]
    assert config.providers["chatgpt_codex"]["auth_type"] == "codex_cli"
    assert config.providers["chatgpt_codex"]["icon"] == "openai"


def test_gateway_sentury_compoe_profile_e_complexity():
    gateway = RobinGateway(RobinConfig.from_mapping({
        "agent_mode": "sentury",
        "providers": {"groq": {"quality": 0.75}},
    }))
    assert gateway.context("critical", "analysis") == "analysis:CRITICAL"
    assert gateway.context("simple") == "SIMPLE"


def test_gateway_universal_preserva_contexto_do_agente():
    gateway = RobinGateway(RobinConfig.from_mapping({"agent_mode": "universal"}))
    assert gateway.context(context="tenant-a:codigo") == "tenant-a:codigo"


def test_nomes_sentury_mapeiam_para_politicas_universais():
    gateway = RobinGateway(RobinConfig.from_mapping({"agent_mode": "sentury"}))
    assert gateway.selection("router") == RouteSelection.router()
    assert gateway.selection("router").mode == "router"
    # Alias técnico antigo não muda o nome canônico exposto pelo Robin.
    assert gateway.selection("auto").mode == "router"
    assert gateway.selection("reforçado", "groq:m").mode == "hybrid"
    assert gateway.selection("dedicado", "groq:m").mode == "strict"


def test_yaml_rejeita_quality_invalida():
    with pytest.raises(ValueError, match="quality"):
        RobinConfig.from_mapping({
            "providers": {"x": {"quality": 2}},
        })


def test_factory_monta_provider_por_referencia_sem_expor_segredo():
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")

    class Settings:
        GROQ_API_KEY = "segredo-nao-pode-sair"
        GROQ_MODELS = "modelo-a,modelo-b"

    provider = build_provider(config, "groq", Settings())
    assert provider.name == "groq"
    assert provider.models == ["modelo-a", "modelo-b"]
    serialized = str(describe_from_config(config, Settings()))
    assert "segredo-nao-pode-sair" not in serialized


def test_endpoint_anonimo_exige_escolha_explicita(monkeypatch, tmp_path):
    """Nao ter chave nao autoriza ligar um servico remoto automaticamente."""
    from robinbandit.accounts import account_config
    from robinbandit import providers as provider_factory

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "contas.json"))
    config = RobinConfig.from_mapping({
        "providers": {
            "normal": {"models": ["modelo"]},
            "anonimo": {"models": ["modelo"], "opt_in": True},
        },
        "routing": {"chain_order": ["normal"]},
    })
    monkeypatch.setattr(
        provider_factory, "build_provider", lambda _config, key, _settings=None: key
    )

    assert provider_factory.build_provider_set(config) == {"normal": "normal"}

    account_config.definir_cadeia(["anonimo"], list(config.providers))
    assert provider_factory.build_provider_set(config)["anonimo"] == "anonimo"


def test_factory_filtra_modelos_aposentados_do_override_e_desliga_github():
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")

    class Settings:
        GROQ_API_KEY = "segredo-nao-pode-sair"
        GROQ_MODELS = "llama-3.3-70b-versatile,openai/gpt-oss-120b"
        GITHUB_MODELS_API_KEY = "token-aposentado"

    groq = build_provider(config, "groq", Settings())
    assert groq.models == ["openai/gpt-oss-120b"]
    assert build_provider(config, "github", Settings()) is None
    github = next(
        item for item in describe_from_config(config, Settings())
        if item["key"] == "github"
    )
    assert github["configured"] is False
    assert github["enabled"] is False


def test_factory_nao_cria_provider_remoto_sem_chave(monkeypatch):
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    assert build_provider(config, "cerebras", object()) is None


def test_factory_codex_depende_do_login_sem_expor_token(monkeypatch):
    from robinbandit.providers.codex_provider import CodexAuthStatus, CodexProvider

    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    monkeypatch.setattr(
        "robinbandit.providers.codex_provider.codex_auth_status",
        lambda binary: CodexAuthStatus(True, "codex_cli", "autenticado"),
    )

    provider = build_provider(config, "chatgpt_codex", object())
    assert isinstance(provider, CodexProvider)
    assert provider.models[0] == "gpt-5.6-sol"
    description = next(
        item for item in describe_from_config(config, object())
        if item["key"] == "chatgpt_codex"
    )
    assert description["configured"] is True
    assert description["auth_type"] == "codex_cli"
    assert "access_token" not in str(description).lower()


def test_yaml_codex_exige_auth_do_cli():
    with pytest.raises(ValueError, match="auth_type: codex_cli"):
        RobinConfig.from_mapping({
            "providers": {"codex": {"adapter": "codex_app_server", "models": ["m"]}},
        })


def test_yaml_recusa_segredo_literal():
    with pytest.raises(ValueError, match="segredo literal"):
        RobinConfig.from_mapping({
            "providers": {"x": {"api_key": "nao-versionar"}},
        })


def test_conta_escolhida_muda_o_dedicado_em_runtime(tmp_path, monkeypatch):
    from robinbandit.accounts import account_config, secrets

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "accounts.json"))
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "vault.json"))
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    build_provider_set(config, object())  # vincula catálogo e caminhos do YAML
    account_config.salvar_conta({
        "id": "conta-paga",
        "provider": "openrouter",
        "key_env": "OPENROUTER_PAID_KEY",
        "models": ["modelo-dedicado"],
        "paga": True,
    })
    secrets.guardar(
        "OPENROUTER_PAID_KEY", "segredo-comprido-1234",
        permitidos=["OPENROUTER_PAID_KEY"],
    )
    account_config.definir_selecao_do_modo(
        "dedicado",
        [{"conta": "conta-paga", "modelos": ["modelo-dedicado"]}],
        ids_validos=["conta-paga"],
    )

    provider = build_tier_provider(config, "ultra_max", object())
    assert provider.name == "ultra_max"
    assert provider.providers[0].models == ["modelo-dedicado"]
    assert "segredo-comprido" not in repr(provider)


def test_modos_exigem_modelos_e_aceitam_varios_provedores(tmp_path, monkeypatch):
    """Preço é só metadado; a seleção explícita manda em conta e modelos."""
    from robinbandit.accounts import account_config

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "accounts.json"))
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "vault.json"))
    monkeypatch.setenv("API_KEY_ULTRA", "uma-chave-compartilhada")
    monkeypatch.setenv("GROQ_API_KEY", "outra-chave")
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    build_provider_set(config, object())

    account_config.definir_selecao_do_modo(
        "reforcado",
        [
            {"conta": "openrouter-paga", "modelos": ["modelo-or-a", "modelo-or-b"]},
            {"conta": "groq", "modelos": ["modelo-groq"]},
        ],
        ids_validos=["openrouter-paga", "groq"],
    )
    account_config.definir_selecao_do_modo(
        "dedicado",
        [{"conta": "groq", "modelos": ["modelo-dedicado"]}],
        ids_validos=["openrouter-paga", "groq"],
    )

    reinforced = build_tier_provider(config, "ultra", object())
    dedicated = build_tier_provider(config, "ultra_max", object())

    assert [p.models for p in reinforced.providers] == [
        ["modelo-or-a", "modelo-or-b"], ["modelo-groq"],
    ]
    assert [p.models for p in dedicated.providers] == [["modelo-dedicado"]]


def test_modo_recusa_conta_sem_modelo(tmp_path, monkeypatch):
    from robinbandit.accounts import account_config

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "accounts.json"))
    with pytest.raises(ValueError, match="ao menos um modelo"):
        account_config.definir_selecao_do_modo(
            "dedicado", [{"conta": "groq", "modelos": []}], ids_validos=["groq"],
        )


def test_dedicado_sem_credencial_nao_vira_router(monkeypatch, tmp_path):
    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "accounts.json"))
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "vault.json"))
    for name in ("API_KEY_ULTRA", "API_KEY_ULTRA_MAX"):
        monkeypatch.delenv(name, raising=False)
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    build_provider_set(config, object())
    provider = build_tier_provider(config, "ultra_max", object())
    assert isinstance(provider, UnavailableProvider)
    assert provider.name == "ultra_max"


@pytest.mark.asyncio
async def test_dedicado_indisponivel_termina_sem_chamar_fallback(monkeypatch, tmp_path):
    from robinbandit.providers.groq_provider import FallbackProvider
    from robinbandit.routing.sentury import ChainProvider, clear_ultra_provider, use_ultra_provider

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "accounts.json"))
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "vault.json"))
    for name in ("API_KEY_ULTRA", "API_KEY_ULTRA_MAX"):
        monkeypatch.delenv(name, raising=False)
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    gateway = RobinGateway(config)
    dedicated = build_tier_provider(config, "ultra_max", object())
    fallback = FallbackProvider()
    fallback.name = "fallback"
    chain = ChainProvider([fallback], gateway)
    token = use_ultra_provider(dedicated)
    try:
        with pytest.raises(RuntimeError, match="Todos os provedores"):
            await chain.complete([{"role": "user", "content": "oi"}])
    finally:
        clear_ultra_provider(token)
    assert chain.last_provider is None


@pytest.mark.asyncio
async def test_reforcado_indisponivel_cai_para_router(monkeypatch, tmp_path):
    from robinbandit.providers.groq_provider import FallbackProvider
    from robinbandit.routing.sentury import ChainProvider, clear_ultra_provider, use_ultra_provider

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "accounts.json"))
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "vault.json"))
    monkeypatch.delenv("API_KEY_ULTRA", raising=False)
    config = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    gateway = RobinGateway(config)
    reinforced = build_tier_provider(config, "ultra", object())
    fallback = FallbackProvider()
    fallback.name = "fallback"
    chain = ChainProvider([fallback], gateway)
    token = use_ultra_provider(reinforced)
    try:
        result = await chain.complete([{"role": "user", "content": "oi"}])
    finally:
        clear_ultra_provider(token)
    assert result
    assert chain.last_provider == "fallback"
