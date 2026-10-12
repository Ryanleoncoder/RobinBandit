"""A conexão direta usa Responses sem executar ferramenta no provedor."""
import json

import httpx
import pytest

from robinbandit.providers import chatgpt_provider as modulo
from robinbandit.accounts.openai_oauth import LoginInvalido


def _stream(final):
    return 'event: response.completed\ndata: ' + json.dumps({"type": "response.completed", "response": final}) + '\n\n'


@pytest.fixture
def transporte(monkeypatch):
    vistos = []
    final = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "resposta"}]}],
             "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "input_tokens_details": {"cached_tokens": 4}}}
    resposta = {"status": 200, "corpo": _stream(final)}
    def atender(req):
        vistos.append(req)
        return httpx.Response(resposta["status"], text=resposta["corpo"], headers={"Content-Type": "text/event-stream"})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(atender), **kw))
    monkeypatch.setattr(modulo, "access_token", lambda: "credencial-ficticia")
    return vistos, resposta, final


@pytest.mark.asyncio
async def test_inferencia_direta_nao_usa_cli_ou_campos_nao_suportados(transporte):
    vistos, _, _ = transporte
    provider = modulo.ChatGPTProvider(["modelo-teste"])
    texto = await provider.generate([{"role": "system", "content": "Instrução"}, {"role": "user", "content": "Pedido"}], temperature=0.7, reasoning_effort="low")
    assert texto == "resposta"
    payload = json.loads(vistos[0].content)
    assert str(vistos[0].url) == "https://api.openai.com/v1/responses"
    assert payload["store"] is False and payload["stream"] is True
    assert payload["input"][0]["role"] == "developer"
    assert "temperature" not in payload and "max_output_tokens" not in payload
    assert "previous_response_id" not in payload
    assert provider.last_usage == {"entrada": 10, "saida": 2, "total": 12, "cacheado": 4}
    assert provider.last_model == "chatgpt:modelo-teste"


@pytest.mark.asyncio
async def test_ferramentas_tem_namespace_e_historico_continua(transporte):
    vistos, resposta, final = transporte
    final["output"] = [{"type": "function_call", "namespace": "robinbandit", "name": "consultar", "call_id": "call_1", "arguments": '{"alvo":"teste"}'}]
    resposta["corpo"] = _stream(final)
    tools = [{"type": "function", "function": {"name": "consultar", "parameters": {"type": "object", "properties": {}}}}]
    provider = modulo.ChatGPTProvider(["modelo-teste"])
    assert await provider.generate([{"role": "user", "content": "consulte"}], tools=tools) == ""
    calls = provider.last_tool_calls
    assert calls[0]["function"]["name"] == "consultar"
    assert json.loads(vistos[0].content)["tools"][0]["type"] == "namespace"
    assert await provider.generate([{"role": "assistant", "tool_calls": calls},
                                     {"role": "tool", "tool_call_id": "call_1", "content": "resultado"}], tools=tools) == ""
    entrada = json.loads(vistos[1].content)["input"]
    assert entrada[0]["namespace"] == "robinbandit" and entrada[1]["type"] == "function_call_output"


@pytest.mark.asyncio
async def test_ferramenta_nao_declarada_e_recusada(transporte):
    _, resposta, final = transporte
    final["output"] = [{"type": "function_call", "name": "fora", "call_id": "x", "arguments": "{}"}]
    resposta["corpo"] = _stream(final)
    provider = modulo.ChatGPTProvider(["modelo-teste"])
    with pytest.raises(LoginInvalido, match="fora da chamada"):
        await provider.generate([{"role": "user", "content": "oi"}])
    assert provider.last_usage is None and provider.last_tool_calls is None


@pytest.mark.asyncio
async def test_stream_interrompido_nao_vira_resposta(transporte):
    _, resposta, _ = transporte
    resposta["corpo"] = 'data: {"type":"response.output_text.delta","delta":"começou"}\n\n'
    provider = modulo.ChatGPTProvider(["modelo-teste"])
    with pytest.raises(LoginInvalido, match="antes da resposta final"):
        await provider.generate([{"role": "user", "content": "oi"}])


@pytest.mark.asyncio
async def test_erro_nao_expoe_corpo_do_provedor_e_limpa_medicao(transporte):
    _, resposta, _ = transporte
    provider = modulo.ChatGPTProvider(["modelo-teste"])
    await provider.generate([{"role": "user", "content": "oi"}])
    resposta.update(status=401, corpo="valor-que-nao-pode-sair")
    with pytest.raises(LoginInvalido) as erro:
        await provider.generate([{"role": "user", "content": "oi"}])
    assert "valor-que-nao-pode-sair" not in str(erro.value)
    assert provider.last_usage is None


@pytest.mark.asyncio
async def test_catalogo_e_da_conta_ativa(monkeypatch):
    monkeypatch.setattr(modulo, "access_token", lambda: "ficticio")
    original = httpx.AsyncClient
    def atender(req):
        assert str(req.url) == "https://api.openai.com/v1/models"
        return httpx.Response(200, json={"models": [{"slug": "visivel", "display_name": "Visível", "visibility": "list"}, {"slug": "oculto", "visibility": "hide"}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(atender), **kw))
    assert await modulo.listar_modelos() == [{"id": "visivel", "name": "Visível"}]
