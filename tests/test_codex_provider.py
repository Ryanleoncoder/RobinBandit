from __future__ import annotations

import pytest

from robinbandit.providers.codex_provider import (
    CodexAppServerClient,
    CodexAuthStatus,
    CodexProvider,
    _history_items,
    _split_messages,
)


def test_app_server_nao_herda_o_robinbandit_como_provedor():
    """O Codex pode entrar e sair da mesma instalação sem chamar a si mesmo."""
    command = CodexAppServerClient()._command("codex")

    assert command[:4] == ["codex", "app-server", "--listen", "stdio://"]
    assert 'model_provider="openai"' in command


def _instalar(pasta, *nomes):
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in nomes:
        (pasta / nome).write_bytes(b"")
    return pasta


def test_code_mode_so_fica_ligado_com_o_host_ao_lado(tmp_path):
    """Com o host, o code mode é o caminho da ferramenta do hospedeiro; sem ele,
    ligado, o turno morre tentando abrir um executável que não existe."""
    com_host = _instalar(tmp_path / "app", "codex.exe", "codex-code-mode-host.exe") / "codex.exe"
    sem_host = _instalar(tmp_path / "solto", "codex.exe") / "codex.exe"

    assert "code_mode_host" not in CodexAppServerClient()._command(str(com_host))
    comando = CodexAppServerClient()._command(str(sem_host))
    assert comando[comando.index("code_mode_host") - 1] == "--disable"
    assert "shell_tool" in CodexAppServerClient()._command(str(com_host))


def test_instalacao_com_host_vence_a_que_esta_no_path(tmp_path, monkeypatch):
    """Um CLI antigo no PATH não chama a ferramenta do Sentury; o do app, com o
    host, chama."""
    from robinbandit.providers import codex_provider

    no_path = _instalar(tmp_path / "path", "codex.exe") / "codex.exe"
    _instalar(tmp_path / "app" / "v1", "codex.exe", "codex-code-mode-host.exe")
    monkeypatch.setattr(codex_provider.shutil, "which", lambda _: str(no_path))
    monkeypatch.setattr(codex_provider, "_LOCAIS_CONHECIDOS", ((str(tmp_path), "app", "*"),))

    assert codex_provider.resolve_codex_binary("codex") == str(tmp_path / "app" / "v1" / "codex.exe")


def test_sem_host_em_lugar_nenhum_fica_o_do_path(tmp_path, monkeypatch):
    from robinbandit.providers import codex_provider

    no_path = _instalar(tmp_path / "path", "codex.exe") / "codex.exe"
    monkeypatch.setattr(codex_provider.shutil, "which", lambda _: str(no_path))
    monkeypatch.setattr(codex_provider, "_LOCAIS_CONHECIDOS", ((str(tmp_path), "nada", "*"),))

    assert codex_provider.resolve_codex_binary("codex") == str(no_path)


def test_split_messages_preserva_instrucoes_e_historico():
    instructions, history, turn = _split_messages([
        {"role": "system", "content": "Regra A"},
        {"role": "developer", "content": "Regra B"},
        {"role": "user", "content": "primeira"},
        {"role": "assistant", "content": "resposta"},
        {"role": "user", "content": "segunda"},
    ])

    assert instructions == "Regra A\n\nRegra B"
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert turn == "segunda"


def test_history_items_converte_tool_calls_sem_perder_ids():
    items = _history_items([
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "buscar", "arguments": {"q": "x"}},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "resultado"},
    ])

    assert items[1] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "buscar",
        "arguments": '{"q": "x"}',
    }
    assert items[2]["type"] == "function_call_output"
    assert items[2]["call_id"] == "call_1"


@pytest.mark.asyncio
async def test_codex_provider_usa_auth_do_cli_e_faz_failover_de_modelo(monkeypatch):
    monkeypatch.setattr(
        "robinbandit.providers.codex_provider.codex_auth_status",
        lambda binary: CodexAuthStatus(True, "codex_cli", "autenticado"),
    )
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def complete(self, messages, *, model, reasoning_effort=None):
            calls.append((model, reasoning_effort, messages))
            if model == "modelo-a":
                raise RuntimeError("modelo indisponível")
            return "ok", "resumo"

    provider = CodexProvider(
        ["modelo-a", "modelo-b"], client_factory=FakeClient,
    )
    answer = await provider.complete(
        [{"role": "user", "content": "oi"}], reasoning_effort="high",
    )

    assert answer == "ok"
    assert [call[0] for call in calls] == ["modelo-a", "modelo-b"]
    assert provider.last_model == "chatgpt_codex:modelo-b"
    assert provider.last_reasoning_summary == "resumo"
    assert provider.model_failures == ["modelo-a"]


@pytest.mark.asyncio
async def test_codex_provider_recusa_quando_cli_nao_esta_autenticado(monkeypatch):
    monkeypatch.setattr(
        "robinbandit.providers.codex_provider.codex_auth_status",
        lambda binary: CodexAuthStatus(False, "codex_cli", "execute: codex login"),
    )
    provider = CodexProvider(["modelo-a"])

    with pytest.raises(RuntimeError, match="codex login"):
        await provider.complete([{"role": "user", "content": "oi"}])


def test_servidores_mcp_lidos_sem_tomllib(tmp_path, monkeypatch):
    import sys

    from robinbandit.providers.codex_provider import _servidores_mcp_do_usuario

    (tmp_path / "config.toml").write_text(
        '[mcp_servers.node_repl]\ncommand = "x"\n[mcp_servers."tato"]\n[mcp_servers.node_repl.env]\n',
        encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setitem(sys.modules, "tomllib", None)
    assert _servidores_mcp_do_usuario() == ["node_repl", "tato"]
