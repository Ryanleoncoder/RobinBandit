from __future__ import annotations

from robinbandit.state.atividade import Atividade


def test_atividade_guarda_so_metadados_operacionais():
    relogio = iter((100.0, 102.5))
    atividade = Atividade(agora=lambda: next(relogio))

    evento = atividade.abrir("groq", "classificacao", modo="hybrid")
    atividade.concluir(
        evento,
        status="sucesso",
        modelo="groq/llama",
        duracao_ms=82.4,
        uso={"entrada": 120, "saida": 30, "prompt": "segredo", "resposta": "segredo"},
    )

    item = atividade.resumo()[0]
    assert item["provedor"] == "groq"
    assert item["modelo"] == "groq/llama"
    assert item["duracao_ms"] == 82
    assert item["ha_segundos"] == 2.5
    assert item["uso"] == {"entrada": 120, "saida": 30}
    assert "prompt" not in repr(item)
    assert "resposta" not in repr(item)


def test_atividade_e_limitada_e_mostra_chamada_em_andamento():
    atividade = Atividade(limite=2, agora=lambda: 50.0)
    primeiro = atividade.abrir("groq")
    atividade.abrir("gemini")
    atividade.abrir("cerebras")

    itens = atividade.resumo(limite=10)
    assert [item["provedor"] for item in itens] == ["cerebras", "gemini"]
    assert all(item["status"] == "em_andamento" for item in itens)

    # Concluir um item já expulso é uma operação inofensiva.
    atividade.concluir(primeiro, status="falha", motivo="timeout")


def test_app_aceita_atividade_injetada_no_painel():
    from fastapi.testclient import TestClient

    from robinbandit.routing.router import ProviderRouter
    from robinbandit.server import create_app

    class Provedor:
        name = "groq"

    atividade = Atividade(agora=lambda: 10.0)
    atividade.abrir("groq", "codigo")
    app = create_app([Provedor()], ProviderRouter(), activity=atividade)

    dados = TestClient(app).get("/painel/dados").json()
    assert dados["atividade"][0]["provedor"] == "groq"
    assert app.state.atividade is atividade
