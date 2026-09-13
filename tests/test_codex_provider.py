from __future__ import annotations

import pytest

from robinbandit.codex_provider import (
    CodexAuthStatus,
    CodexProvider,
    _history_items,
    _split_messages,
)


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
        "robinbandit.codex_provider.codex_auth_status",
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
        "robinbandit.codex_provider.codex_auth_status",
        lambda binary: CodexAuthStatus(False, "codex_cli", "execute: codex login"),
    )
    provider = CodexProvider(["modelo-a"])

    with pytest.raises(RuntimeError, match="codex login"):
        await provider.complete([{"role": "user", "content": "oi"}])
