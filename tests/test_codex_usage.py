"""A telemetria distingue uso informado de ausência de medição."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from robinbandit.providers.codex_provider import CodexAppServerClient, CodexAuthStatus, CodexProvider


async def _cliente(eventos):
    class Entrada:
        def write(self, mensagem):
            pass

        async def drain(self):
            pass

    leitor = asyncio.StreamReader()
    mensagens = [
        {"id": 1, "result": {}},
        {"id": 2, "result": {"thread": {"id": "t1"}}},
        {"id": 3, "result": {}},
        *eventos,
        {"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": "ok"}}},
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ]
    for mensagem in mensagens:
        leitor.feed_data((json.dumps(mensagem) + "\n").encode())
    leitor.feed_eof()
    cliente = CodexAppServerClient()
    assert await cliente._drive(SimpleNamespace(stdin=Entrada(), stdout=leitor),
                                [{"role": "user", "content": "oi"}], "teste", "low") == ("ok", None)
    return cliente


def _evento(total, ultimo=None, thread="t1"):
    return {"method": "thread/tokenUsage/updated", "params": {
        "threadId": thread, "tokenUsage": {"total": total, "last": ultimo or total},
    }}


async def test_eventos_sao_fotografias_nao_incrementos():
    cliente = await _cliente([
        _evento({"inputTokens": 10, "outputTokens": 2, "totalTokens": 12}),
        _evento({"inputTokens": 30, "cachedInputTokens": 15, "outputTokens": 6, "totalTokens": 36},
                {"inputTokens": 20, "outputTokens": 4, "totalTokens": 24}),
    ])
    assert cliente.last_usage == {"entrada": 30, "saida": 6, "total": 36, "cacheado": 15}


async def test_sem_evento_nao_inventa_zero():
    assert (await _cliente([])).last_usage is None


async def test_cache_zero_informado_e_diferente_de_cache_ausente():
    medido = await _cliente([_evento({"inputTokens": 8, "outputTokens": 2, "cachedInputTokens": 0})])
    ausente = await _cliente([_evento({"inputTokens": 8, "outputTokens": 2})])
    assert medido.last_usage == {"entrada": 8, "saida": 2, "total": 10, "cacheado": 0}
    assert ausente.last_usage == {"entrada": 8, "saida": 2, "total": 10}


async def test_evento_de_outra_conversa_e_contagem_invalida_nao_sobrescrevem():
    cliente = await _cliente([
        _evento({"inputTokens": 8, "outputTokens": 2}),
        _evento({"inputTokens": 100, "outputTokens": 10}, thread="outra"),
        _evento({"inputTokens": -1, "outputTokens": 2}),
        _evento({"inputTokens": "quebrado", "outputTokens": 2}),
    ])
    assert cliente.last_usage == {"entrada": 8, "saida": 2, "total": 10}


async def test_provedor_publica_o_uso_sem_reaproveitar_chamada_anterior(monkeypatch):
    monkeypatch.setattr("robinbandit.providers.codex_provider.codex_auth_status",
                        lambda _: CodexAuthStatus(True, "codex_cli", "ok"))
    chamadas = []

    class Cliente:
        last_usage = {"entrada": 20, "saida": 3, "total": 23, "cacheado": 10}

        def __init__(self, **kwargs):
            chamadas.append(self)

        async def complete(self, *args, **kwargs):
            if len(chamadas) > 1:
                raise RuntimeError("falha")
            return "ok", None

    provedor = CodexProvider(["teste"], client_factory=Cliente)
    assert await provedor.complete([{"role": "user", "content": "oi"}]) == "ok"
    assert provedor.last_usage == Cliente.last_usage
    with pytest.raises(RuntimeError, match="falha"):
        await provedor.complete([{"role": "user", "content": "de novo"}])
    assert provedor.last_usage is None


async def test_duas_chamadas_concorrentes_nao_trocam_telemetria(monkeypatch):
    monkeypatch.setattr("robinbandit.providers.codex_provider.codex_auth_status",
                        lambda _: CodexAuthStatus(True, "codex_cli", "ok"))

    class Cliente:
        def __init__(self, **kwargs):
            self.last_usage = None

        async def complete(self, messages, **kwargs):
            valor = int(messages[0]["content"])
            self.last_usage = {"entrada": valor, "saida": 1, "total": valor + 1}
            await asyncio.sleep(0)
            return "ok", None

    provedor = CodexProvider(["teste"], client_factory=Cliente)

    async def chamar(valor):
        await provedor.complete([{"role": "user", "content": str(valor)}])
        await asyncio.sleep(0)
        return provedor.last_usage

    assert await asyncio.gather(chamar(10), chamar(20)) == [
        {"entrada": 10, "saida": 1, "total": 11},
        {"entrada": 20, "saida": 1, "total": 21},
    ]


async def test_cadeia_do_runtime_soma_uso_e_cache_do_codex(monkeypatch):
    from robinbandit.chain import iniciar_contagem, contagem_do_turno
    from robinbandit.sentury import ChainProvider

    monkeypatch.setattr("robinbandit.providers.codex_provider.codex_auth_status",
                        lambda _: CodexAuthStatus(True, "codex_cli", "ok"))

    class Cliente:
        last_usage = {"entrada": 20, "saida": 3, "total": 23, "cacheado": 10}

        def __init__(self, **kwargs):
            pass

        async def complete(self, *args, **kwargs):
            return "ok", None

    cadeia = ChainProvider([CodexProvider(["teste"], client_factory=Cliente)])
    iniciar_contagem()
    for _ in range(2):
        assert await cadeia.complete([{"role": "user", "content": "oi"}]) == "ok"
    assert cadeia.last_usage == Cliente.last_usage
    uso = contagem_do_turno()
    assert {nome: uso[nome] for nome in ("entrada", "saida", "total", "cacheado", "chamadas")} == {
        "entrada": 40, "saida": 6, "total": 46, "cacheado": 20, "chamadas": 2,
    }
