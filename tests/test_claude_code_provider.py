"""Claude Code como provedor, pela assinatura.

O RobinBandit nao le, copia ou renova credencial: `~/.claude/.credentials.json`
e do CLI. Aqui ele e so mais um provedor de modelo — o loop de ferramentas
continua sendo do agente hospedeiro.
"""
import json
from pathlib import Path

import pytest

from robinbandit import RobinConfig
from robinbandit.claude_code_provider import (
    ClaudeCodeError,
    ClaudeCodeProvider,
    _texto_das_mensagens,
)
from robinbandit.providers import build_provider

ROOT = Path(__file__).resolve().parents[1]


def test_provedor_esta_no_catalogo_com_auth_de_cli():
    cfg = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    spec = cfg.providers.get("claude_code")
    assert spec, "claude_code nao declarado"
    assert spec["adapter"] == "claude_code"
    assert spec["auth_type"] == "claude_cli"
    # Sem chave: quem autentica e o CLI. Exigir uma faria o provedor aparecer
    # como "falta configurar" para quem ja esta logado.
    assert spec.get("chave_opcional") is True
    assert not spec.get("api_key_env")


def test_historico_vira_prompt_com_os_papeis_marcados():
    sistema, prompt = _texto_das_mensagens([
        {"role": "system", "content": "Seja breve."},
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "ola"},
        {"role": "user", "content": "tudo bem?"},
    ])
    assert sistema == "Seja breve."
    assert prompt == "Usuário: oi\n\nAssistente: ola\n\nUsuário: tudo bem?"


def test_mensagem_vazia_nao_vira_linha_solta():
    _sistema, prompt = _texto_das_mensagens([
        {"role": "user", "content": "  "},
        {"role": "user", "content": "vale"},
    ])
    assert prompt == "Usuário: vale"


@pytest.mark.asyncio
async def test_sem_nada_para_perguntar_falha_cedo():
    provider = ClaudeCodeProvider()
    with pytest.raises(ClaudeCodeError):
        await provider.generate([{"role": "system", "content": "so contexto"}])


def test_ferramentas_do_cli_ficam_desligadas():
    """Dois loops de ferramenta no mesmo turno — o do CLI e o do agente —
    disputariam a mesma execucao."""
    provider = ClaudeCodeProvider()
    try:
        comando = provider._comando("oi", "", "")
    except ClaudeCodeError:
        pytest.skip("Claude Code CLI nao instalado nesta maquina")
    assert "--allowed-tools" in comando
    assert comando[comando.index("--allowed-tools") + 1] == ""
    assert "--output-format" in comando and "json" in comando


def test_fabrica_devolve_none_sem_cli(monkeypatch):
    """Sem o CLI ele fica fora da cadeia, em vez de falhar no meio do turno."""
    import robinbandit.claude_code_provider as ccp

    monkeypatch.setattr(ccp, "resolve_claude_binary", lambda binary="claude": None)
    ccp._STATUS_CACHE.clear()
    cfg = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    assert build_provider(cfg, "claude_code", None) is None


def test_erro_do_cli_nao_vira_resposta(monkeypatch):
    """Uma falha tem de parecer falha: devolver o texto do erro como resposta
    e o jeito mais silencioso de entregar lixo."""
    import subprocess

    import robinbandit.claude_code_provider as ccp

    class Saida:
        stdout = json.dumps({"is_error": True, "result": "limite atingido"})
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Saida())
    monkeypatch.setattr(ccp, "resolve_claude_binary", lambda binary="claude": "claude")

    import asyncio

    provider = ClaudeCodeProvider()
    with pytest.raises(ClaudeCodeError, match="limite atingido"):
        asyncio.run(provider.generate([{"role": "user", "content": "oi"}]))
