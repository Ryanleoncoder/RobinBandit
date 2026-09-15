"""Contratos de importacao anteriores a reorganizacao da versao 0.5."""

from importlib import import_module

import pytest


ALIASES = {
    "account_config": "accounts.account_config",
    "account_health": "accounts.account_health",
    "credentials": "accounts.credentials",
    "secrets": "accounts.secrets",
    "anthropic_api": "api.anthropic_api",
    "clientes": "api.clientes",
    "responses_api": "api.responses_api",
    "model_catalog": "catalog.model_catalog",
    "profiles": "catalog.profiles",
    "quota_ping": "catalog.quota_ping",
    "reasoning": "catalog.reasoning",
    "saldo": "catalog.saldo",
    "token_budget": "catalog.token_budget",
    "claude_code_provider": "providers.claude_code_provider",
    "claude_provider": "providers.claude_provider",
    "codex_provider": "providers.codex_provider",
    "gemini_provider": "providers.gemini_provider",
    "groq_provider": "providers.groq_provider",
    "openai_compat": "providers.openai_compat",
    "openrouter_provider": "providers.openrouter_provider",
    "chain": "routing.chain",
    "erros": "routing.erros",
    "router": "routing.router",
    "selection": "routing.selection",
    "sentury": "routing.sentury",
    "estado": "state.estado",
    "historico": "state.historico",
    "janela": "state.janela",
    "uso": "state.uso",
    "_banner": "ui._banner",
    "cli_tools": "ui.cli_tools",
    "idioma": "ui.idioma",
}


@pytest.mark.parametrize("antigo,novo", ALIASES.items())
def test_import_legado_aponta_para_modulo_novo(antigo, novo):
    modulo_antigo = import_module(f"robinbandit.{antigo}")
    modulo_novo = import_module(f"robinbandit.{novo}")

    assert modulo_antigo is modulo_novo
