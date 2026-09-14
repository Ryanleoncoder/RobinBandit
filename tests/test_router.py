"""ProviderRouter: cooldown, ordenação por score, bandit e persistência."""
from robinbandit import ProviderRouter
from robinbandit import RouteSelection
from robinbandit.router import _Stat

PRIORS = {
    "groq": {"tier": 1, "quality": 0.75},
    "gemini": {"tier": 1, "quality": 0.80},
    "github": {"tier": 1, "quality": 0.90},
    "cohere": {"tier": 2, "quality": 0.68},
    "demo": {"tier": 9, "quality": 0.05},
}


class _FakeProvider:
    def __init__(self, name):
        self.name = name


def test_cooldown_apos_429():
    r = ProviderRouter(PRIORS)
    r.record_failure("groq", "rate_limit")
    primeiro = r.cooldown_remaining("groq")
    assert primeiro > 0
    r.record_failure("groq", "rate_limit")
    assert r.cooldown_remaining("groq") >= primeiro  # reincidência escala
    r.record_success("groq", 200.0)
    assert r.cooldown_remaining("groq") == 0  # sucesso limpa


def test_order_poe_cooled_e_last_resort_no_fim():
    r = ProviderRouter(PRIORS, last_resort="demo")
    provs = [_FakeProvider("groq"), _FakeProvider("gemini"), _FakeProvider("demo")]
    r.record_failure("groq", "rate_limit")
    ordered = [p.name for p in r.order(provs)]
    assert ordered[-1] == "demo"
    assert ordered.index("gemini") < ordered.index("groq")  # saudável antes do cooled


def test_sem_last_resort_nenhum_provedor_e_forcado_pro_fim():
    r = ProviderRouter(PRIORS)
    provs = [_FakeProvider("demo"), _FakeProvider("github")]
    for _ in range(30):
        r.record_success("demo", 100.0)
        r.record_failure("github", "other")
    assert [p.name for p in r.order(provs)][0] == "demo"


def test_bandit_aprende_qualidade():
    r = ProviderRouter(PRIORS)
    for _ in range(20):
        r.record_success("github", 300.0, context="CRITICAL")
        r.record_failure("cohere", "other", context="CRITICAL")
    snap = r.snapshot()
    assert snap["github"]["quality_mean"] is None
    assert snap["cohere"]["quality_mean"] is None
    assert snap["github"]["health_mean"] > snap["cohere"]["health_mean"]


def test_reward_quality_move_o_bandit():
    r = ProviderRouter(PRIORS)
    for _ in range(5):
        r.reward_quality("github", "CRITICAL", good=True)
        r.reward_quality("cohere", "CRITICAL", good=False)
    snap = r.snapshot()
    assert snap["github"]["quality_mean"] > snap["cohere"]["quality_mean"]
    assert snap["github"]["health_mean"] is None
    assert snap["cohere"]["health_mean"] is None


def test_last_resort_nao_acumula_qualidade():
    # A resposta do provedor de último recurso é um aviso fixo; avaliá-la criaria
    # evidência sem sentido e sujaria snapshot e dump.
    r = ProviderRouter(PRIORS, last_resort="demo")
    r.reward_quality("demo", "CRITICAL", good=True)
    assert "demo" not in r.snapshot()
    assert "demo" not in r.dump()


def test_decay_readapta_provedor():
    # provedor vira ruim (falhas) e depois melhora (sucessos): com decay, a
    # qualidade se recupera — não fica engessada no passado ruim.
    r = ProviderRouter(PRIORS)
    for _ in range(30):
        r.record_failure("groq", "other", context="STANDARD")
    ruim = r.snapshot()["groq"]["health_mean"]
    for _ in range(60):
        r.record_success("groq", 150.0, context="STANDARD")
    assert r.snapshot()["groq"]["health_mean"] > ruim + 0.2


def test_quota_penalty_evita_quase_esgotado():
    assert ProviderRouter._quota_penalty(_Stat(rpm_remaining=0)) > ProviderRouter._quota_penalty(_Stat(rpm_remaining=100))
    assert ProviderRouter._quota_penalty(_Stat()) == 0.0             # sem info = neutro
    assert ProviderRouter._quota_penalty(_Stat(rpm_remaining=100)) == 0.0  # folgado = neutro


def test_dump_load_roundtrip():
    r = ProviderRouter(PRIORS)
    r.record_success("groq", 180.0, context="SIMPLE")
    r2 = ProviderRouter(PRIORS)
    r2.load(r.dump())
    assert r2.snapshot()["groq"]["ok"] == 1
    assert r2.dump() == r.dump()


def test_context_e_opaco():
    # Nada de vocabulario emprestado: qualquer string vira celula propria, sem
    # normalizacao, e None cai numa celula default.
    r = ProviderRouter(PRIORS)
    r.record_success("groq", 100.0, context="triagem-de-ticket")
    r.record_success("groq", 100.0, context="Triagem-De-Ticket")
    r.record_success("groq", 100.0)
    assert set(r.dump()["groq"]["health"]) == {
        "triagem-de-ticket", "Triagem-De-Ticket", "default"}


def test_sucesso_nao_contamina_qualidade_e_feedback_nao_contamina_saude():
    r = ProviderRouter(PRIORS)
    r.order([_FakeProvider("groq")], context="ctx")
    antes = r.snapshot()["groq"]
    quality_antes = antes["quality_mean"]
    health_antes = antes["health_mean"]

    for _ in range(10):
        r.record_success("groq", 100.0, context="ctx")
    apos_sucesso = r.snapshot()["groq"]
    assert apos_sucesso["quality_mean"] == quality_antes
    assert apos_sucesso["health_mean"] > health_antes

    health_antes_feedback = apos_sucesso["health_mean"]
    r.reward_quality("groq", "ctx", good=False)
    depois = r.snapshot()["groq"]
    assert depois["quality_mean"] < quality_antes
    assert depois["health_mean"] == health_antes_feedback


def test_load_formato_antigo_migra_cells_para_health():
    antigo = {"groq": {"ok": 3, "err": 1, "latency_ms": 200,
                        "cells": {"ctx": [7.0, 2.0]}}}
    r = ProviderRouter(PRIORS)
    r.load(antigo)
    dump = r.dump()["groq"]
    assert dump["health"] == {"ctx": [7.0, 2.0]}
    assert dump["quality"] == {}


def test_weights_do_chamador_valem():
    # Contexto que privilegia velocidade prefere o rapido; o que privilegia
    # qualidade prefere quem tem prior alto. Mesma evidencia nos dois casos.
    pesos = {"rapido": (0.0, 1.0, 0.0), "bom": (1.0, 0.0, 0.0)}
    r = ProviderRouter({"veloz": {"tier": 2, "quality": 0.10},
                        "lento": {"tier": 2, "quality": 0.99}}, weights=pesos)
    for _ in range(30):
        r.record_success("veloz", 160.0)
        r.record_success("lento", 7000.0)
    provs = [_FakeProvider("veloz"), _FakeProvider("lento")]
    assert [p.name for p in r.order(provs, "rapido")][0] == "veloz"
    assert [p.name for p in r.order(provs, "bom")][0] == "lento"


def test_context_sem_peso_definido_usa_equilibrado():
    from robinbandit.router import _DEFAULT_WEIGHTS
    r = ProviderRouter(PRIORS, weights={"critico": (0.6, 0.15, 0.25)})
    assert r._weights("nao-mapeado") == _DEFAULT_WEIGHTS
    assert r._weights(None) == _DEFAULT_WEIGHTS
    assert r._weights("critico") == (0.6, 0.15, 0.25)


def test_prior_desconhecido_usa_default():
    r = ProviderRouter(PRIORS)
    r.order([_FakeProvider("nunca-visto")])
    assert r.snapshot()["nunca-visto"]["quality_mean"] == 0.6


def test_peak_ewma_reage_a_pico_na_hora():
    # Degradar tem que custar caro imediatamente; melhorar precisa se provar.
    r = ProviderRouter(PRIORS)
    for _ in range(10):
        r.record_success("groq", 200.0)
    assert r.snapshot()["groq"]["latency_ms"] == 200

    r.record_success("groq", 6000.0)
    assert r.snapshot()["groq"]["latency_ms"] == 6000  # pico entra inteiro

    r.record_success("groq", 200.0)
    depois = r.snapshot()["groq"]["latency_ms"]
    assert 200 < depois < 6000  # recuperacao e gradual, nao instantanea


def test_peak_ewma_converge_na_descida():
    r = ProviderRouter(PRIORS)
    r.record_success("groq", 6000.0)
    for _ in range(30):
        r.record_success("groq", 200.0)
    assert r.snapshot()["groq"]["latency_ms"] < 250


def test_inflight_penaliza_provedor_ocupado():
    pesos = {"ctx": (0.0, 0.0, 1.0)}  # so taxa de sucesso
    # Com semente: os dois estao empatados, e o sorteio do Thompson no contexto
    # as vezes vencia a penalidade de ocupacao. Um teste que passa quase sempre
    # nao prova nada — so adia a pergunta.
    r = ProviderRouter({"a": {"tier": 2, "quality": 0.5},
                        "b": {"tier": 2, "quality": 0.5}}, weights=pesos, seed=7)
    for _ in range(20):
        r.record_success("a", 100.0, context="ctx")
        r.record_success("b", 100.0, context="ctx")
    provs = [_FakeProvider("a"), _FakeProvider("b")]

    for _ in range(5):
        r.begin("a")
    assert [p.name for p in r.order(provs, "ctx")][0] == "b"
    assert r.inflight("a") == 5


def test_inflight_e_limitado_e_zera():
    r = ProviderRouter(PRIORS)
    assert r._inflight_penalty("groq") == 0.0
    for _ in range(1000):
        r.begin("groq")
    assert r._inflight_penalty("groq") < 0.15  # satura, nao explode
    for _ in range(1000):
        r.end("groq")
    assert r.inflight("groq") == 0
    assert r._inflight_penalty("groq") == 0.0


def test_end_a_mais_nao_fica_negativo():
    r = ProviderRouter(PRIORS)
    r.end("groq")
    r.end("groq")
    assert r.inflight("groq") == 0


def test_modelos_do_mesmo_provedor_aprendem_separados():
    class _MeanRng:
        @staticmethod
        def betavariate(alpha, beta):
            return alpha / (alpha + beta)

    r = ProviderRouter({
        "openrouter": {
            "quality": 0.5,
            "models": {
                "bom": {"quality": 0.5, "priority": 2},
                "ruim": {"quality": 0.5, "priority": 1},
            },
        }
    })
    r._rng = _MeanRng()
    for _ in range(8):
        r.reward_quality("openrouter", "coding", True, model="openrouter:bom")
        r.reward_quality("openrouter", "coding", False, model="openrouter:ruim")
    assert r.order_models("openrouter", ["ruim", "bom"], "coding")[0] == "bom"
    snap = r.snapshot()["openrouter"]["models"]
    assert snap["bom"]["quality_mean"] > snap["ruim"]["quality_mean"]


def test_custo_e_prioridade_influenciam_score_adaptativo():
    class _FixedRng:
        @staticmethod
        def betavariate(alpha, beta):
            return 0.5

    r = ProviderRouter(
        providers={
            "free": {"tier": 2, "quality": 0.5, "priority": 1, "cost_class": "free"},
            "paid": {"tier": 2, "quality": 0.5, "priority": 9, "cost_class": "paid"},
        },
        cost_penalties={"paid": 0.1, "free": 0.0},
    )
    r._rng = _FixedRng()
    providers = [_FakeProvider("paid"), _FakeProvider("free")]
    assert r.order(providers)[0].name == "free"


def test_strategy_tier_e_barreira_economica_com_fallback():
    r = ProviderRouter(
        providers={"free": {"tier": 1}, "paid": {"tier": 3}},
        strategy="tier",
    )
    providers = [_FakeProvider("paid"), _FakeProvider("free")]
    assert r.order(providers)[0].name == "free"
    r.record_failure("free", "rate_limit")
    assert r.order(providers)[0].name == "paid"


def test_strategy_fixed_respeita_a_ordem_e_cooldown():
    r = ProviderRouter(
        providers={"primeiro": {}, "segundo": {}},
        strategy="fixed",
    )
    providers = [_FakeProvider("segundo"), _FakeProvider("primeiro")]
    assert [p.name for p in r.order(providers)] == ["segundo", "primeiro"]
    r.record_failure("segundo", "rate_limit")
    assert [p.name for p in r.order(providers)] == ["primeiro", "segundo"]


def test_strategy_round_robin_so_avanca_com_tentativa_real():
    r = ProviderRouter(
        providers={"a": {}, "b": {}, "c": {}},
        strategy="round_robin",
    )
    providers = [_FakeProvider("a"), _FakeProvider("b"), _FakeProvider("c")]
    assert [p.name for p in r.order(providers)] == ["a", "b", "c"]
    # Consultar de novo (como faz o painel) não move o anel.
    assert [p.name for p in r.order(providers)] == ["a", "b", "c"]
    r.record_success("a", 100)
    assert [p.name for p in r.order(providers)] == ["b", "c", "a"]
    r.record_failure("b", "error")
    assert [p.name for p in r.order(providers)] == ["c", "a", "b"]


def test_selecao_hybrid_poe_escolhido_na_frente_e_preserva_fallback():
    r = ProviderRouter(PRIORS, last_resort="demo")
    provs = [_FakeProvider("groq"), _FakeProvider("gemini"), _FakeProvider("demo")]
    ordered = r.order(provs, selection=RouteSelection.hybrid("gemini:model-x"))
    assert [p.name for p in ordered] == ["gemini", "groq", "demo"]


def test_selecao_strict_remove_todos_os_outros_provedores():
    r = ProviderRouter(PRIORS, last_resort="demo")
    provs = [_FakeProvider("groq"), _FakeProvider("gemini"), _FakeProvider("demo")]
    ordered = r.order(provs, selection=RouteSelection.strict("gemini:model-x"))
    assert [p.name for p in ordered] == ["gemini"]


def test_aliases_sentury_reforcado_e_dedicado():
    assert RouteSelection("reinforced", "groq").mode == "hybrid"
    assert RouteSelection("dedicated", "groq").mode == "strict"


def test_override_de_tier_do_painel_muda_o_roteamento(monkeypatch):
    from robinbandit import account_config

    monkeypatch.setattr(account_config, "overrides_de_tier", lambda: {"paid": 1, "free": 3})
    r = ProviderRouter(
        providers={"free": {"tier": 1}, "paid": {"tier": 3}},
        strategy="tier",
    )
    providers = [_FakeProvider("free"), _FakeProvider("paid")]
    assert r.order(providers)[0].name == "paid"
