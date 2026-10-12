"""A escolha de ferramenta volta ao hospedeiro sem execução dentro do CLI."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from robinbandit.providers.codex_provider import CodexAppServerClient
from robinbandit.providers.codex_ferramentas import declarar, capturar


FERRAMENTAS = [{"type": "function", "function": {"name": "ler_arquivo",
    "description": "Lê um arquivo", "parameters": {"type": "object", "properties": {"caminho": {"type": "string"}}}}}]


async def _rodar(monkeypatch, pedidos, historico=None):
    enviados = []

    class Entrada:
        def write(self, bruto):
            enviados.append(json.loads(bruto))

        async def drain(self):
            pass

        def close(self):
            pass

    leitor = asyncio.StreamReader()
    mensagens = [{"id": 1, "result": {}}, {"id": 2, "result": {"thread": {"id": "t1"}}}]
    if historico:
        mensagens.append({"id": 3, "result": {}})
    mensagens.append({"id": 4 if historico else 3, "result": {}})
    mensagens.extend(pedidos)
    mensagens.append({"method": "turn/completed", "params": {"turn": {"status": "interrupted"}}})
    for mensagem in mensagens:
        leitor.feed_data((json.dumps(mensagem) + "\n").encode())
    leitor.feed_eof()
    process = SimpleNamespace(stdin=Entrada(), stdout=leitor, stderr=None, returncode=0)

    async def criar(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", criar)
    monkeypatch.setattr("robinbandit.providers.codex_provider.resolve_codex_binary", lambda _: "codex")
    cliente = CodexAppServerClient()
    monkeypatch.setattr(cliente, "_command", lambda _: ["codex"])
    resposta = await cliente.complete((historico or []) + [{"role": "user", "content": "leia"}],
                                      model="teste", tools=FERRAMENTAS)
    return cliente, resposta, enviados


def _pedido(ident="c1", ferramenta="rb_ler_arquivo"):
    return {"method": "item/tool/call", "id": 80, "params": {"threadId": "t1", "turnId": "v1",
        "callId": ident, "tool": ferramenta, "arguments": {"caminho": "exemplo.txt"}}}


async def test_chamada_nativa_declara_intercepta_e_interrompe(monkeypatch):
    cliente, resposta, enviados = await _rodar(monkeypatch, [_pedido()])
    assert resposta == ("", None)
    assert cliente.last_tool_calls == [{"id": "c1", "type": "function", "function": {
        "name": "ler_arquivo", "arguments": '{"caminho": "exemplo.txt"}'}}]
    assert enviados[0]["params"]["capabilities"]["experimentalApi"] is True
    declaradas = enviados[2]["params"]["dynamicTools"]
    assert declaradas[0]["name"] == "rb_ler_arquivo"
    assert declaradas[0]["inputSchema"] == FERRAMENTAS[0]["function"]["parameters"]
    assert enviados[-1]["method"] == "turn/interrupt"
    assert not any("result" in envio for envio in enviados)


async def test_chamadas_paralelas_preservam_ids_sem_duplicar(monkeypatch):
    cliente, _, _ = await _rodar(monkeypatch, [_pedido(), _pedido("c2"), _pedido()])
    assert [c["id"] for c in cliente.last_tool_calls] == ["c1", "c2"]


async def test_resultado_real_do_hospedeiro_entra_no_historico(monkeypatch):
    historico = [{"role": "assistant", "content": "", "tool_calls": [{"id": "antigo",
        "function": {"name": "ler_arquivo", "arguments": {"caminho": "antes"}}}]},
        {"role": "tool", "tool_call_id": "antigo", "content": "resultado real"}]
    _, _, enviados = await _rodar(monkeypatch, [_pedido()], historico)
    injecao = next(e for e in enviados if e.get("method") == "thread/inject_items")["params"]["items"]
    assert next(i for i in injecao if i["type"] == "function_call")["name"] == "rb_ler_arquivo"
    assert next(i for i in injecao if i["type"] == "function_call_output")["output"] == "resultado real"


def test_nome_invalido_e_duplicado_nao_sao_declarados():
    with pytest.raises(ValueError):
        declarar(FERRAMENTAS * 2)
    with pytest.raises(ValueError):
        declarar([{"function": {"name": "nome com espaço"}}])


def test_chamada_fora_da_declaracao_ou_da_thread_nao_e_aceita():
    _, nomes = declarar(FERRAMENTAS)
    params = _pedido()["params"]
    assert capturar({**params, "threadId": "outra"}, nomes, "t1") is None
    assert capturar({**params, "tool": "shell"}, nomes, "t1") is None
    with pytest.raises(ValueError):
        capturar({**params, "arguments": []}, nomes, "t1")
