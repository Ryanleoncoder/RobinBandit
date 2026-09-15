"""A janela de uso das assinaturas.

Provedor de API tem limite por minuto, e disso o cooldown ja cuida. Assinatura
para de vez quando o bloco acaba e volta numa hora que da para saber — e essa
hora nao aparecia em lugar nenhum do painel.
"""
import os
import tempfile
import time
from pathlib import Path

import pytest

from robinbandit import RobinConfig
from robinbandit.state import janela
from robinbandit.routing.router import ProviderRouter

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def casa_isolada(monkeypatch):
    monkeypatch.setenv("ROBINBANDIT_HOME", tempfile.mkdtemp(prefix="rb-janela-teste-"))
    yield


def _config():
    return RobinConfig.from_yaml(RAIZ / "config" / "sentury.yaml")


def test_so_assinatura_tem_janela():
    """Contar a janela de todo provedor gravaria 40 linhas para responder uma
    pergunta que so existe para quem paga por bloco, nao por token."""
    quem = janela.de_assinatura(_config())
    assert set(quem) == {"claude_code", "chatgpt_codex"}
    assert all(horas == janela.HORAS_PADRAO for horas in quem.values())


def test_bloco_conta_as_chamadas_e_diz_quando_vira():
    janela.registrar("claude_code", horas=5.0)
    janela.registrar("claude_code", horas=5.0)

    estado = janela.estado("claude_code")
    assert estado["aberta"] is True
    assert estado["chamadas"] == 2
    # 5h menos alguns milissegundos: o relogio mostra 4h59, nao "5h".
    assert estado["falta_s"] > 4 * 3600
    assert "h" in estado["vira_em"]


def test_bloco_vencido_nao_conta_como_aberto():
    """Venceu e ninguem chamou desde entao: a proxima chamada abre outro. Um
    bloco vencido mostrado como aberto diria que falta tempo que ja passou."""
    janela.registrar("claude_code", horas=5.0)
    dados = janela._ler()
    dados["claude_code"]["inicio"] = time.time() - 6 * 3600
    janela._gravar(dados)

    assert janela.estado("claude_code")["aberta"] is False


def test_chamada_depois_do_vencimento_abre_bloco_novo():
    """O bloco anterior zerou de verdade: somar nele diria que a pessoa gastou
    mais do que gastou."""
    for _ in range(9):
        janela.registrar("claude_code", horas=5.0)
    dados = janela._ler()
    dados["claude_code"]["inicio"] = time.time() - 6 * 3600
    janela._gravar(dados)

    janela.registrar("claude_code", horas=5.0)
    assert janela.estado("claude_code")["chamadas"] == 1


def test_rate_limit_na_assinatura_e_a_janela_acabando():
    """Numa assinatura, `rate_limit` nao e lentidao: e o bloco tendo acabado.
    Sem separar, ele ficava indistinguivel de um erro qualquer."""
    router = ProviderRouter(_config().providers)
    router.declarar_janelas(janela.de_assinatura(_config()))

    router.record_success("claude_code", 800.0)
    router.record_failure("claude_code", "rate_limit", detail="limite do bloco")
    router.record_failure("claude_code", "server_error", detail="502")

    estado = janela.estado("claude_code")
    assert estado["chamadas"] == 3
    assert estado["bloqueios"] == 1
    assert estado["erros"] == 2


def test_provedor_de_api_nao_gera_janela():
    router = ProviderRouter(_config().providers)
    router.declarar_janelas(janela.de_assinatura(_config()))

    router.record_success("groq", 200.0)

    assert janela.estado("groq")["aberta"] is False
    assert "groq" not in janela._ler()


def test_o_que_vira_antes_aparece_antes():
    """A decisao e "espero ou troco": quem esta prestes a virar interessa mais."""
    janela.registrar("chatgpt_codex", horas=5.0)
    dados = janela._ler()
    dados["chatgpt_codex"]["inicio"] = time.time() - 4.5 * 3600
    janela._gravar(dados)
    janela.registrar("claude_code", horas=5.0)

    nomes = [linha["provedor"] for linha in janela.resumo(_config())]
    assert nomes[0] == "chatgpt_codex"


def test_relogio_le_se_rapido():
    assert janela._relogio(8035) == "2h13"
    assert janela._relogio(300) == "5 min"
    assert janela._relogio(20) == "menos de 1 min"


def test_ping_liga_pelo_painel():
    """Vinha desligado e so mudava editando YAML — para uma opcao que quem tem
    assinatura quer ligar olhando a janela, nao reiniciando o processo."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from robinbandit.server import create_app

    config = _config()
    cliente = TestClient(create_app([], ProviderRouter(config.providers), config=config))

    assert cliente.get("/janelas").json()["ping"]["ativo"] is False
    resposta = cliente.put("/janelas/ping", json={"ativo": True, "intervalo_s": 600})
    assert resposta.json()["ativo"] is True
    assert resposta.json()["intervalo_s"] == 600
    assert cliente.get("/janelas").json()["ping"]["ativo"] is True


def test_ping_nao_desce_de_um_minuto():
    """Pingar mais rapido que isso gasta mais cota do que a informacao vale."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from robinbandit.server import create_app

    config = _config()
    cliente = TestClient(create_app([], ProviderRouter(config.providers), config=config))

    assert cliente.put("/janelas/ping", json={"intervalo_s": 5}).json()["intervalo_s"] == 60.0
