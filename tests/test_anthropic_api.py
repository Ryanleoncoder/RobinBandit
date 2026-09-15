"""O protocolo da Anthropic, que e o que o Claude Code fala.

Ele nao chama `/v1/chat/completions`: chama `/v1/messages`, com `system` a
parte e `content` em blocos. Enquanto a rota nao existia, a configuracao que o
painel entregava respondia 404 — o formato aqui foi tirado do que o `claude`
2.1.269 realmente envia, nao da documentacao.
"""
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from robinbandit.api import anthropic_api  # noqa: E402
from robinbandit.routing.router import ProviderRouter  # noqa: E402
from robinbandit.server import create_app  # noqa: E402


class _Fake:
    def __init__(self, nome, resposta="ok"):
        self.name = nome
        self.resposta = resposta
        self.recebidas = None

    async def complete(self, messages, temperature=0.2):
        self.recebidas = messages
        return self.resposta


def _cliente(provedor=None):
    provedor = provedor or _Fake("groq")
    router = ProviderRouter({"groq": {"tier": 1, "quality": 0.8}}, seed=3)
    return TestClient(create_app([provedor], router)), provedor


# --- traducao ---------------------------------------------------------------

def test_system_vira_a_primeira_mensagem():
    """Na Anthropic `system` e campo separado; todo provedor do Robin espera
    ele como a primeira mensagem da lista."""
    saida = anthropic_api.para_mensagens(
        [{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
        system=[{"type": "text", "text": "voce e util"}],
    )
    assert saida == [
        {"role": "system", "content": "voce e util"},
        {"role": "user", "content": "oi"},
    ]


def test_content_em_blocos_vira_texto():
    """O Claude Code manda `content` como lista de blocos, nunca como string."""
    saida = anthropic_api.para_mensagens(
        [{"role": "user", "content": [
            {"type": "text", "text": "primeira"},
            {"type": "text", "text": "segunda"},
        ]}]
    )
    assert saida == [{"role": "user", "content": "primeira\nsegunda"}]


def test_bloco_sem_texto_e_descartado_sem_derrubar():
    """Imagem e resultado de ferramenta nao tem como seguir para um provedor de
    texto. Descartar e honesto; inventar transcricao seria pior."""
    saida = anthropic_api.para_mensagens(
        [
            {"role": "user", "content": [{"type": "image", "source": {}}]},
            {"role": "user", "content": [{"type": "text", "text": "sobrou"}]},
        ]
    )
    assert saida == [{"role": "user", "content": "sobrou"}]


def test_system_como_string_tambem_vale():
    """As duas formas sao validas na API; o Claude Code usa lista, outros
    clientes usam string."""
    saida = anthropic_api.para_mensagens([{"role": "user", "content": "oi"}], system="regra")
    assert saida[0] == {"role": "system", "content": "regra"}


# --- a rota -----------------------------------------------------------------

def test_claude_code_recebe_resposta_no_formato_dele():
    cliente, _ = _cliente(_Fake("groq", "funcionou"))
    r = cliente.post("/v1/messages", json={
        "model": "codigo",
        "max_tokens": 32000,
        "system": [{"type": "text", "text": "seja breve"}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
    })
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["type"] == "message"
    assert corpo["role"] == "assistant"
    assert corpo["content"] == [{"type": "text", "text": "funcionou"}]
    assert corpo["stop_reason"] == "end_turn"
    # O SDK le usage.input_tokens direto: faltar o campo quebra o cliente.
    assert corpo["usage"]["input_tokens"] == 0
    assert corpo["id"].startswith("msg_")


def test_o_system_chega_no_provedor():
    cliente, provedor = _cliente()
    cliente.post("/v1/messages", json={
        "model": "codigo",
        "system": [{"type": "text", "text": "regra do sistema"}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
    })
    assert provedor.recebidas[0] == {"role": "system", "content": "regra do sistema"}


def test_stream_vira_sse_com_a_sequencia_inteira():
    """O cliente pede `stream: true` e so sabe ler esse formato. Faltar um
    evento trava ele esperando o resto."""
    cliente, _ = _cliente(_Fake("groq", "em pedacos"))
    r = cliente.post("/v1/messages", json={
        "model": "codigo",
        "stream": True,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    nomes = [l[len("event: "):] for l in r.text.splitlines() if l.startswith("event: ")]
    assert nomes == [
        "message_start", "content_block_start", "content_block_delta",
        "content_block_stop", "message_delta", "message_stop",
    ]
    # o texto sai inteiro no delta unico
    deltas = [json.loads(l[len("data: "):]) for l in r.text.splitlines() if l.startswith("data: ")]
    texto = "".join(
        d["delta"]["text"] for d in deltas
        if d.get("type") == "content_block_delta"
    )
    assert texto == "em pedacos"


def test_pedido_sem_texto_nenhum_e_recusado():
    cliente, _ = _cliente()
    r = cliente.post("/v1/messages", json={
        "model": "codigo",
        "messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}],
    })
    assert r.status_code == 400


def test_model_vira_contexto_do_bandit():
    """`ANTHROPIC_MODEL=codigo` tem que aprender na celula `codigo`, igual ao
    endpoint OpenAI.

    A prova esta no dump, nao no `/state`: o snapshot agrega as celulas e nao
    devolve o nome de nenhuma.
    """
    router = ProviderRouter({"groq": {"tier": 1, "quality": 0.8}}, seed=3)
    cliente = TestClient(create_app([_Fake("groq")], router))
    cliente.post("/v1/messages", json={
        "model": "revisao",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
    })
    aprendido = router.dump()["groq"]
    assert "revisao" in aprendido["health"]
    assert "revisao" in aprendido["quality"]


def test_falha_volta_no_envelope_da_anthropic():
    """O cliente le `error.message`; fora desse formato ele mostra 'unknown
    error' e esconde qual provedor caiu."""
    class Quebrado:
        name = "groq"

        async def complete(self, messages, temperature=0.2):
            raise RuntimeError("todos os provedores falharam")

    router = ProviderRouter({"groq": {"tier": 1}}, seed=3)
    cliente = TestClient(create_app([Quebrado()], router), raise_server_exceptions=False)
    r = cliente.post("/v1/messages", json={
        "model": "codigo",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
    })
    assert r.status_code == 502
    corpo = r.json()
    assert corpo["type"] == "error"
    assert "falharam" in corpo["error"]["message"]
