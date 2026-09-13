"""ChainProvider: num 429, espera+retenta o mesmo provedor antes de cascatear."""
import pytest

from robinbandit import ChainProvider, ProviderRouter, classify_error


def test_classify_error():
    assert classify_error(Exception("Client error '429 Too Many Requests'")) == "rate_limit"
    assert classify_error(Exception("rate limit exceeded")) == "rate_limit"
    assert classify_error(Exception("401 Unauthorized: invalid api key")) == "auth"
    assert classify_error(Exception("Connection timed out")) == "network"
    assert classify_error(Exception("402 payment required")) == "credit"
    assert classify_error(Exception("qualquer outra coisa")) == "other"


class _Prov:
    def __init__(self, roteiro, name="fake"):
        self.roteiro = list(roteiro)
        self.calls = 0
        self.name = name
        self.last_model = name

    async def complete(self, messages, temperature=0.2, context=None):
        self.calls += 1
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def sem_espera(monkeypatch):
    import robinbandit.chain as chain

    async def _no_sleep(s):
        pass

    monkeypatch.setattr(chain.asyncio, "sleep", _no_sleep)


async def test_retenta_no_mesmo_provider_em_429(sem_espera):
    p = _Prov([Exception("429 Too Many Requests"), "resposta boa"])
    ch = ChainProvider([p], ProviderRouter())
    out = await ch.complete([{"role": "user", "content": "oi"}])
    assert out == "resposta boa"
    assert p.calls == 2  # 429 -> retry -> sucesso, sem cascatear


async def test_auth_nao_retenta_o_mesmo_provider(sem_espera):
    # auth (401) NÃO faz retry no mesmo provedor (diferente do 429). Com 1
    # provedor só, a cadeia esgota e levanta — mas o provedor foi chamado 1x só.
    ruim = _Prov([Exception("401 unauthorized"), "nunca chega"], name="ruim")
    ch = ChainProvider([ruim], ProviderRouter())
    with pytest.raises(RuntimeError):
        await ch.complete([{"role": "user", "content": "oi"}])
    assert ruim.calls == 1


async def test_cascateia_para_outro_provider(sem_espera):
    # Se um provedor falha, a cadeia entrega via outro (a ordem varia por causa
    # do roteamento adaptativo; o que importa é que UM entrega).
    ruim = _Prov([Exception("500 server error")], name="ruim")
    bom = _Prov(["fallback ok"], name="bom")
    ch = ChainProvider([ruim, bom], ProviderRouter())
    out = await ch.complete([{"role": "user", "content": "oi"}])
    assert out == "fallback ok"
    assert ruim.calls <= 1  # nunca retentado


async def test_falha_alimenta_o_router(sem_espera):
    # Um provedor só: com mais de um, a ordem é estocástica (Thompson) e o
    # provedor que falha pode nunca ser tentado.
    router = ProviderRouter()
    ruim = _Prov([Exception("429 Too Many Requests"), Exception("429 de novo")], name="ruim")
    ch = ChainProvider([ruim], router)
    with pytest.raises(RuntimeError):
        await ch.complete([{"role": "user", "content": "oi"}])
    assert router.cooldown_remaining("ruim") > 0


async def test_sucesso_alimenta_o_router(sem_espera):
    router = ProviderRouter()
    ch = ChainProvider([_Prov(["ok"], name="bom")], router)
    await ch.complete([{"role": "user", "content": "oi"}])
    assert router.snapshot()["bom"]["ok"] == 1
    assert router.cooldown_remaining("bom") == 0


class _ProvSemContext:
    """Provedor de terceiro que nao conhece o parametro context."""
    name = "alheio"
    last_model = "alheio"

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, temperature=0.2):
        self.calls += 1
        return "ok"


class _ProvQueLevantaTypeError:
    name = "quebrado"
    last_model = "quebrado"

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, temperature=0.2, context=None):
        self.calls += 1
        raise TypeError("bug interno do provedor")


async def test_provedor_sem_context_e_chamado_sem_o_kwarg(sem_espera):
    p = _ProvSemContext()
    ch = ChainProvider([p], ProviderRouter())
    assert await ch.complete([{"role": "user", "content": "oi"}], context="qualquer") == "ok"
    assert p.calls == 1


async def test_typeerror_interno_nao_repete_a_chamada(sem_espera):
    # O provedor aceita context, entao um TypeError vindo de dentro dele e uma
    # falha real — nao pode virar uma segunda chamada e gastar cota de novo.
    p = _ProvQueLevantaTypeError()
    ch = ChainProvider([p], ProviderRouter())
    with pytest.raises(RuntimeError):
        await ch.complete([{"role": "user", "content": "oi"}])
    assert p.calls == 1


async def test_chain_vazia_falha_claro():
    with pytest.raises(ValueError):
        ChainProvider([], ProviderRouter())


async def test_inflight_e_liberado_no_sucesso_e_na_falha(sem_espera):
    # begin sem end penalizaria o provedor para sempre: o finally e o que
    # impede o vazamento.
    router = ProviderRouter()
    ch = ChainProvider([_Prov(["ok"], name="bom")], router)
    await ch.complete([{"role": "user", "content": "oi"}])
    assert router.inflight("bom") == 0

    ruim = _Prov([Exception("500 boom")], name="ruim")
    with pytest.raises(RuntimeError):
        await ChainProvider([ruim], router).complete([{"role": "user", "content": "oi"}])
    assert router.inflight("ruim") == 0


async def test_inflight_liberado_quando_o_provedor_levanta_typeerror(sem_espera):
    router = ProviderRouter()
    with pytest.raises(RuntimeError):
        await ChainProvider([_ProvQueLevantaTypeError()], router).complete(
            [{"role": "user", "content": "oi"}])
    assert router.inflight("quebrado") == 0


async def test_hybrid_cai_para_router_quando_escolhido_falha(sem_espera):
    escolhido = _Prov([Exception("500 boom")], name="escolhido")
    fallback = _Prov(["ok pelo router"], name="fallback")
    chain = ChainProvider([fallback, escolhido], ProviderRouter())
    out = await chain.complete(
        [{"role": "user", "content": "oi"}],
        selection={"mode": "hybrid", "provider": "escolhido"},
    )
    assert out == "ok pelo router"
    assert escolhido.calls == 1


async def test_strict_nao_cai_para_outro_provedor(sem_espera):
    escolhido = _Prov([Exception("500 boom")], name="escolhido")
    outro = _Prov(["não deve chamar"], name="outro")
    chain = ChainProvider([outro, escolhido], ProviderRouter())
    with pytest.raises(RuntimeError):
        await chain.complete(
            [{"role": "user", "content": "oi"}],
            selection={"mode": "strict", "provider": "escolhido"},
        )
    assert escolhido.calls == 1
    assert outro.calls == 0


async def test_falha_de_modelo_antes_do_sucesso_nao_contamina_provedor():
    class MultiModel:
        name = "openrouter"
        models = ["ruim", "bom"]
        last_model = "openrouter:bom"
        last_quota = None

        async def complete(self, messages, temperature=0.2, **kwargs):
            self.model_failures = ["openrouter:ruim"]
            self.last_model = "openrouter:bom"
            return "ok"

    router = ProviderRouter({"openrouter": {"models": ["ruim", "bom"]}})
    chain = ChainProvider([MultiModel()], router)
    assert await chain.complete([{"role": "user", "content": "oi"}]) == "ok"
    snapshot = router.snapshot()["openrouter"]
    assert snapshot["ok"] == 1 and snapshot["err"] == 0
    assert snapshot["models"]["ruim"]["err"] == 1
    assert snapshot["models"]["bom"]["ok"] == 1
