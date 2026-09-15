"""Bater a janela de uma assinatura nao e o provedor piorando.

Assinatura nao tem cota por token: tem bloco de horas. Quando ele acaba, o
provedor para e volta inteiro na virada — nada disso diz que ele responde mal.
Penalizar a saude nesse momento ensinava o bandit a desconfiar de quem so
estava esperando a hora, e a desconfianca sobrevivia a virada, porque o
posterior Beta nao esquece sozinho.

A distincao vale *so* para quem tem janela declarada: num provedor por chave,
`429` recorrente e informacao verdadeira sobre disponibilidade.
"""
import time

from robinbandit.routing.router import ProviderRouter


def _saude(router, key, contexto=None):
    return router.dump()[key]["health"].get(contexto or "default")


def test_assinatura_que_bate_o_limite_nao_perde_saude(monkeypatch):
    router = ProviderRouter({"claude_code": {"tier": 1}}, seed=1)
    router.declarar_janelas({"claude_code": 5.0})

    # A janela esta aberta e falta uma hora para virar.
    monkeypatch.setattr(
        "robinbandit.state.janela.estado",
        lambda p: {"aberta": True, "falta_s": 3600, "provedor": p},
    )

    router.record_success("claude_code", 300.0, context="codigo")
    antes = _saude(router, "claude_code", "codigo")

    router.record_failure("claude_code", "rate_limit", context="codigo")
    depois = _saude(router, "claude_code", "codigo")

    # beta (o lado do fracasso) nao pode ter crescido
    assert depois[1] <= antes[1] + 1e-9, "a janela estourada penalizou a saude"


def test_mas_continua_em_espera_ate_a_virada(monkeypatch):
    """Nao penalizar nao significa continuar tentando: insistir antes da hora
    gasta chamada para ouvir o mesmo 429."""
    router = ProviderRouter({"claude_code": {"tier": 1}}, seed=1)
    router.declarar_janelas({"claude_code": 5.0})
    monkeypatch.setattr(
        "robinbandit.state.janela.estado",
        lambda p: {"aberta": True, "falta_s": 3600, "provedor": p},
    )

    router.record_failure("claude_code", "rate_limit", context="codigo")

    restante = router.cooldown_remaining("claude_code")
    # espera ate a virada, nao o exponencial curto de rate limit
    assert 3500 < restante <= 3600


def test_provedor_por_chave_continua_sendo_penalizado():
    """Sem janela declarada, `429` e informacao real sobre disponibilidade —
    apagar isso cegaria o bandit."""
    router = ProviderRouter({"groq": {"tier": 1}}, seed=1)
    # nenhuma janela declarada para groq

    router.record_success("groq", 300.0, context="codigo")
    antes = _saude(router, "groq", "codigo")

    router.record_failure("groq", "rate_limit", context="codigo")
    depois = _saude(router, "groq", "codigo")

    assert depois[1] > antes[1], "429 de provedor por chave tem que contar"


def test_erro_de_verdade_na_assinatura_ainda_conta(monkeypatch):
    """A isencao e so para o bloco acabando. Se o `claude` quebrou por outro
    motivo, isso e sobre ele e tem que pesar."""
    router = ProviderRouter({"claude_code": {"tier": 1}}, seed=1)
    router.declarar_janelas({"claude_code": 5.0})
    monkeypatch.setattr(
        "robinbandit.state.janela.estado",
        lambda p: {"aberta": True, "falta_s": 3600, "provedor": p},
    )

    router.record_success("claude_code", 300.0, context="codigo")
    antes = _saude(router, "claude_code", "codigo")

    router.record_failure("claude_code", "error", context="codigo", detail="timeout")
    depois = _saude(router, "claude_code", "codigo")

    assert depois[1] > antes[1], "erro real na assinatura tem que contar"


def test_janela_fechada_cai_no_comportamento_normal(monkeypatch):
    """Sem janela aberta nao ha virada para esperar: vale o cooldown de
    sempre, e a falha conta."""
    router = ProviderRouter({"claude_code": {"tier": 1}}, seed=1)
    router.declarar_janelas({"claude_code": 5.0})
    monkeypatch.setattr(
        "robinbandit.state.janela.estado",
        lambda p: {"aberta": False, "falta_s": 0, "provedor": p},
    )

    router.record_success("claude_code", 300.0, context="codigo")
    antes = _saude(router, "claude_code", "codigo")

    router.record_failure("claude_code", "rate_limit", context="codigo")
    depois = _saude(router, "claude_code", "codigo")

    assert depois[1] > antes[1]


def test_a_assinatura_volta_ao_topo_depois_da_virada(monkeypatch):
    """O efeito que tudo isso existe para produzir: passada a janela, ela
    disputa a primeira posicao como antes, sem carregar cicatriz."""
    router = ProviderRouter(
        {"claude_code": {"tier": 1, "quality": 0.95}, "groq": {"tier": 1, "quality": 0.75}},
        seed=7,
    )
    router.declarar_janelas({"claude_code": 5.0})

    for _ in range(10):
        router.record_success("claude_code", 200.0, context="codigo")
        router.record_success("groq", 400.0, context="codigo")

    monkeypatch.setattr(
        "robinbandit.state.janela.estado",
        lambda p: {"aberta": True, "falta_s": 60, "provedor": p},
    )
    router.record_failure("claude_code", "rate_limit", context="codigo")

    # durante a espera, sai da frente
    ordem = router.order(["claude_code", "groq"], context="codigo")
    assert ordem[0] == "groq"

    # passada a janela, volta a competir
    with router._lock:
        router._stat("claude_code").cooldown_until = time.time() - 1
    vitorias = sum(
        1 for _ in range(60)
        if router.order(["claude_code", "groq"], context="codigo")[0] == "claude_code"
    )
    assert vitorias > 25, f"nao voltou a competir: venceu {vitorias}/60"
