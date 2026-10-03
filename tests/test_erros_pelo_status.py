"""O tipo do erro sai do codigo HTTP; o corpo so refina.

O provedor tenta cada modelo, guarda o ultimo erro e levanta um `RuntimeError`
com o texto dele. Duas coisas se perdiam no caminho:

- o codigo: sem `raise ... from`, o `HTTPStatusError` original sumia;
- o corpo: o `str()` do erro do httpx diz so "Client error '400 Bad Request'",
  e o "context_length_exceeded" mora no corpo da resposta.
"""
import httpx
import pytest

from robinbandit import classify_error
from robinbandit.routing.erros import status_http

URL = "https://api.exemplo.com/v1/chat/completions"


def _erro_http(status, corpo=""):
    """Como o provedor entrega: o erro do httpx dentro de um RuntimeError."""
    pedido = httpx.Request("POST", URL)
    resposta = httpx.Response(status, text=corpo, request=pedido)
    try:
        resposta.raise_for_status()
    except httpx.HTTPStatusError as original:
        try:
            raise RuntimeError(f"Todos os modelos falharam: {original}") from original
        except RuntimeError as embrulhado:
            return embrulhado
    raise AssertionError("status sem erro")


class TestPeloStatus:
    @pytest.mark.parametrize("status,corpo,tipo", [
        (413, "", "request_too_large"),
        # O 413 da Groq traz rate_limit_exceeded no corpo; o codigo decide.
        (413, '{"error":{"code":"rate_limit_exceeded","message":"Request too large"}}',
         "request_too_large"),
        (402, "", "credit"),
        (429, '{"error":{"type":"tokens"}}', "rate_limit"),
        (429, '{"error":{"code":"insufficient_quota"}}', "credit"),
        (401, "", "auth"),
        (403, "", "auth"),
        (403, '{"error":"blocked by safety settings"}', "content_policy"),
        (404, '{"error":"model does not exist"}', "not_found"),
        (408, "", "network"),
        (500, "", "transient"),
        (503, "", "transient"),
        (529, '{"type":"overloaded_error"}', "rate_limit"),
    ])
    def test_codigo_decide(self, status, corpo, tipo):
        assert classify_error(_erro_http(status, corpo)) == tipo

    @pytest.mark.parametrize("corpo,tipo", [
        ('{"error":{"code":"context_length_exceeded"}}', "context_length"),
        ('{"error":{"code":"content_filter"}}', "content_policy"),
        ('{"error":"campo invalido"}', "other"),
    ])
    def test_400_e_o_corpo_que_diz(self, corpo, tipo):
        erro = _erro_http(400, corpo)
        assert "context_length" not in str(erro), "o texto do erro nao traz o corpo"
        assert classify_error(erro) == tipo

    def test_o_codigo_vem_de_dentro_da_cadeia(self):
        assert status_http(_erro_http(503)) == 503

    def test_sem_codigo_continua_pelo_texto(self):
        assert status_http(RuntimeError("Connection timed out")) is None
        assert classify_error(RuntimeError("Connection timed out")) == "network"
        assert classify_error(RuntimeError("used 10413 tokens")) == "other"


class TestOProvedorGuardaACadeia:
    async def test_groq_levanta_com_o_erro_original_dentro(self, monkeypatch):
        """Sem `from last_error`, o codigo HTTP nao chegava a cadeia."""
        from robinbandit.providers import groq_provider

        def responde(pedido):
            return httpx.Response(400, json={"error": {"code": "context_length_exceeded"}})

        original = httpx.AsyncClient
        monkeypatch.setattr(
            groq_provider.httpx, "AsyncClient",
            lambda *a, **k: original(transport=httpx.MockTransport(responde)),
        )
        provedor = groq_provider.GroqProvider("gsk_teste", ["modelo-a"])
        with pytest.raises(RuntimeError) as falha:
            await provedor.complete([{"role": "user", "content": "oi"}])

        assert status_http(falha.value) == 400
        assert classify_error(falha.value) == "context_length"
