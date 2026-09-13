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
