"""Endpoint OpenAI-compatible e o loop de feedback."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from robinbandit import ProviderRouter
from robinbandit.server import create_app


class _Prov:
    def __init__(self, resposta="oi", name="alpha"):
        self.name = name
        self.last_model = f"{name}:modelo-x"
        self.resposta = resposta

    async def complete(self, messages, temperature=0.2, context=None):
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


class _ProvComUso(_Prov):
    def __init__(self):
        super().__init__()
        self.last_usage = {"entrada": 120, "saida": 30, "total": 150}


class _ProvComFerramenta(_Prov):
    def __init__(self):
        super().__init__("", name="ferramentas")
        self.recebidas = None
        self.esforco = None
        self.last_tool_calls = None

    async def complete(
        self, messages, temperature=0.2, context=None, tools=None,
        reasoning_effort=None,
    ):
        self.recebidas = tools
        self.esforco = reasoning_effort
        self.last_tool_calls = [{
            "id": "call_shell_1",
            "type": "function",
            "function": {"name": "shell", "arguments": '{"input":"echo oi"}'},
        }]
        return ""


def _cliente(providers, router):
    return TestClient(create_app(providers, router))


def test_resposta_no_formato_openai():
    c = _cliente([_Prov("bom dia")], ProviderRouter())
    r = c.post("/v1/chat/completions",
               json={"messages": [{"role": "user", "content": "oi"}]})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["object"] == "chat.completion"
    assert corpo["id"].startswith("chatcmpl-")
    assert corpo["choices"][0]["message"] == {"role": "assistant", "content": "bom dia"}
    assert corpo["choices"][0]["finish_reason"] == "stop"
    # usage e omitido de proposito: nao contamos tokens e zero seria mentira
    assert "usage" not in corpo


def test_resposta_openai_repassa_tokens_quando_provedor_informa():
    c = _cliente([_ProvComUso()], ProviderRouter())
    corpo = c.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "oi"}]}).json()
    assert corpo["usage"] == {
        "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
    }


def test_responses_api_devolve_texto_e_tokens():
    c = _cliente([_ProvComUso()], ProviderRouter())
    corpo = c.post("/v1/responses", json={
        "model": "codigo",
        "input": [{
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "oi"}],
        }],
    }).json()
    assert corpo["object"] == "response"
    assert corpo["id"].startswith("resp_")
    assert corpo["output"][0]["content"][0]["text"] == "oi"
    assert corpo["usage"]["input_tokens"] == 120
    assert corpo["usage"]["output_tokens"] == 30


def test_responses_api_traduz_ferramenta_personalizada():
    provedor = _ProvComFerramenta()
    c = _cliente([provedor], ProviderRouter())
    corpo = c.post("/v1/responses", json={
        "input": "use a ferramenta",
        "tools": [{
            "type": "custom", "name": "shell", "description": "Terminal",
            "format": {"type": "grammar", "syntax": "lark", "definition": "start: /.+/"},
        }],
        "reasoning": {"effort": "high"},
    }).json()
    assert provedor.recebidas[0]["function"]["name"] == "shell"
    assert provedor.esforco == "high"
    assert corpo["output"] == [{
        "id": "ctc_call_shell_1",
        "type": "custom_tool_call",
        "status": "completed",
        "call_id": "call_shell_1",
        "name": "shell",
        "input": "echo oi",
    }]


def test_responses_api_stream_emite_a_sequencia_do_codex():
    c = _cliente([_Prov("bom dia")], ProviderRouter())
    resposta = c.post("/v1/responses", json={"input": "oi", "stream": True})
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/event-stream")
    eventos = resposta.text
    assert "event: response.created" in eventos
    assert "event: response.output_text.delta" in eventos
    assert "event: response.completed" in eventos
    assert "[DONE]" not in eventos


def test_responses_api_reconstroi_historico_de_ferramenta():
    from robinbandit.api.responses_api import para_mensagens

    mensagens = para_mensagens([
        {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "liste"},
        ]},
        {"type": "function_call", "call_id": "call_1", "name": "listar",
         "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "a.txt"},
    ], "Responda curto")
    assert mensagens[0] == {"role": "system", "content": "Responda curto"}
    assert mensagens[2]["tool_calls"][0]["id"] == "call_1"
    assert mensagens[3] == {"role": "tool", "tool_call_id": "call_1", "content": "a.txt"}


def test_modo_reforcado_esta_disponivel_para_cliente_http(monkeypatch):
    from robinbandit import RobinConfig
    import robinbandit.providers as fabrica

    reforcado = _Prov("veio do reforçado", name="ultra")
    monkeypatch.setattr(fabrica, "build_tier_provider", lambda *args: reforcado)
    config = RobinConfig.from_mapping({"providers": {"normal": {}}})
    cliente = TestClient(create_app(
        [_Prov("veio da rota normal", name="normal")], ProviderRouter(), config=config,
    ))
    resposta = cliente.post(
        "/v1/chat/completions",
        headers={"X-RobinBandit-Mode": "reinforced"},
        json={"messages": [{"role": "user", "content": "oi"}]},
    )
    assert resposta.status_code == 200
    assert resposta.json()["choices"][0]["message"]["content"] == "veio do reforçado"


def test_modo_normal_pode_ser_pedido_explicitamente():
    from robinbandit import RobinConfig

    config = RobinConfig.from_mapping({"providers": {"normal": {}}})
    cliente = TestClient(create_app(
        [_Prov("veio da rota normal", name="normal")], ProviderRouter(), config=config,
    ))
    resposta = cliente.post(
        "/v1/chat/completions",
        headers={"X-RobinBandit-Mode": "normal"},
        json={"messages": [{"role": "user", "content": "oi"}]},
    )
    assert resposta.status_code == 200
    assert resposta.json()["choices"][0]["message"]["content"] == "veio da rota normal"


def test_dedicado_nao_vira_modo_http_generico():
    from robinbandit import RobinConfig

    config = RobinConfig.from_mapping({"providers": {"normal": {}}})
    cliente = TestClient(create_app([_Prov(name="normal")], ProviderRouter(), config=config))
    resposta = cliente.post(
        "/v1/chat/completions",
        headers={"X-RobinBandit-Mode": "dedicated"},
        json={"messages": [{"role": "user", "content": "oi"}]},
    )
    assert resposta.status_code == 400
    assert "Sentury" in resposta.json()["detail"]


def test_feedback_credita_o_provedor_que_respondeu():
    router = ProviderRouter()
    c = _cliente([_Prov(name="alpha")], router)
    rid = c.post("/v1/chat/completions",
                 json={"messages": [{"role": "user", "content": "oi"}],
                       "model": "auditoria"}).json()["id"]

    antes = router.snapshot()["alpha"]["quality_mean"]
    assert c.post("/feedback", json={"id": rid, "good": True}).json()["provider"] == "alpha"
    assert router.snapshot()["alpha"]["quality_mean"] > antes


def test_feedback_negativo_derruba_a_qualidade():
    router = ProviderRouter()
    c = _cliente([_Prov(name="alpha")], router)
    rid = c.post("/v1/chat/completions",
                 json={"messages": [{"role": "user", "content": "oi"}]}).json()["id"]
    antes = router.snapshot()["alpha"]["quality_mean"]
    c.post("/feedback", json={"id": rid, "good": False})
    assert router.snapshot()["alpha"]["quality_mean"] < antes


def test_model_do_pedido_vira_o_contexto():
    # E o unico campo que todo cliente OpenAI envia, entao da para escolher
    # contexto sem cliente modificado.
    router = ProviderRouter()
    c = _cliente([_Prov(name="alpha")], router)
    for ctx in ("auditoria", "triagem"):
        c.post("/v1/chat/completions",
               json={"messages": [{"role": "user", "content": "oi"}], "model": ctx})
    c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "oi"}]})
    estado = router.dump()["alpha"]
    assert set(estado["health"]) == {"auditoria", "triagem", "default"}
    assert set(estado["quality"]) == {"auditoria", "triagem", "default"}


def test_id_desconhecido_ou_reavaliado_da_404():
    c = _cliente([_Prov()], ProviderRouter())
    assert c.post("/feedback", json={"id": "chatcmpl-nao-existe", "good": True}).status_code == 404
    rid = c.post("/v1/chat/completions",
                 json={"messages": [{"role": "user", "content": "oi"}]}).json()["id"]
    assert c.post("/feedback", json={"id": rid, "good": True}).status_code == 200
    assert c.post("/feedback", json={"id": rid, "good": True}).status_code == 404


def test_streaming_falha_explicito():
    # Melhor recusar do que devolver nao-streamado e quebrar o parser do cliente.
    c = _cliente([_Prov()], ProviderRouter())
    r = c.post("/v1/chat/completions",
               json={"messages": [{"role": "user", "content": "oi"}], "stream": True})
    assert r.status_code == 400


def test_todos_os_provedores_falharem_da_502():
    c = _cliente([_Prov(Exception("500 boom"))], ProviderRouter())
    r = c.post("/v1/chat/completions",
               json={"messages": [{"role": "user", "content": "oi"}]})
    assert r.status_code == 502


def test_models_lista_os_provedores():
    c = _cliente([_Prov(name="alpha"), _Prov(name="beta")], ProviderRouter())
    dados = c.get("/v1/models").json()["data"]
    assert [m["id"] for m in dados] == ["alpha", "beta"]


def test_state_expoe_snapshot_e_pendencias():
    router = ProviderRouter()
    c = _cliente([_Prov(name="alpha")], router)
    c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "oi"}]})
    corpo = c.get("/state").json()
    assert corpo["providers"]["alpha"]["ok"] == 1
    assert corpo["pending_feedback"] == 1
