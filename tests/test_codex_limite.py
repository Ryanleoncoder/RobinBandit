"""A falha da assinatura não vira aviso sem motivo nem aciona outro modelo da mesma conta."""
import pytest

from robinbandit import ChainProvider, ProviderRouter, classify_error
from robinbandit.sentury import ChainProvider as CadeiaDoSentury
from robinbandit.providers.codex_provider import CodexAuthStatus, CodexProvider
from robinbandit.providers.codex_limite import LimiteDoCodex, erro_do_turno
from robinbandit.providers.groq_provider import FallbackProvider
from test_codex_usage import _cliente


async def test_erro_estruturado_chega_sem_link_de_compra():
    erro = {"codexErrorInfo": "usageLimitExceeded",
            "message": "You have hit your usage limit. Try again at 12:58 PM. Upgrade https://example.com/buy"}
    with pytest.raises(LimiteDoCodex) as capturado:
        await _cliente([{"method": "turn/completed", "params": {"turn": {"status": "failed", "error": erro}}}])
    assert capturado.value.retoma_em == "12:58 PM"
    assert "https" not in str(capturado.value)
    assert classify_error(capturado.value) == "credit"


def test_limite_sem_previsao_nao_inventa_horario():
    erro = erro_do_turno({"codexErrorInfo": "UsageLimitExceeded", "message": "limit reached"})
    assert erro.retoma_em == ""
    assert "não foi informado" in str(erro)
    assert erro_do_turno({"codexErrorInfo": "BadRequest", "message": "bad"}) is None
    estranho = RuntimeError("falha desconhecida")
    estranho.tipo = []
    assert classify_error(estranho) == "other"


async def test_nao_tenta_outro_modelo_quando_a_assinatura_acabou(monkeypatch):
    monkeypatch.setattr("robinbandit.providers.codex_provider.codex_auth_status",
                        lambda _: CodexAuthStatus(True, "codex_cli", "ok"))
    chamadas = []

    class Cliente:
        def __init__(self, **kwargs):
            pass

        async def complete(self, messages, model, **kwargs):
            chamadas.append(model)
            raise LimiteDoCodex("Try again at 12:58 PM")

    provider = CodexProvider(["um", "dois"], client_factory=Cliente)
    with pytest.raises(LimiteDoCodex):
        await provider.complete([{"role": "user", "content": "oi"}])
    assert len(chamadas) == 1


@pytest.mark.parametrize("runtime", [False, True])
async def test_fallback_informa_motivo_e_preserva_a_identidade(runtime):
    class Esgotado:
        name = "chatgpt_codex"

        async def complete(self, *args, **kwargs):
            raise LimiteDoCodex("Try again at 12:58 PM. https://example.com/buy")

    providers = [Esgotado(), FallbackProvider()]
    cadeia = CadeiaDoSentury(providers) if runtime else ChainProvider(providers, ProviderRouter())
    cadeia.router.order = lambda *args, **kwargs: providers
    mensagem = await cadeia.complete([{"role": "user", "content": "oi"}])
    assert "12:58 PM" in mensagem and "assinatura do Codex" in mensagem
    assert "http" not in mensagem
    assert cadeia.last_provider == "fallback"
    assert cadeia.ultimas_falhas["chatgpt_codex"]["tipo"] == "credit"


def test_contagem_preserva_cache_zero_medido():
    from robinbandit.chain import iniciar_contagem, contagem_do_turno, _somar

    iniciar_contagem()
    _somar({"entrada": 10, "saida": 1, "total": 11})
    assert "cacheado" not in contagem_do_turno()
    _somar({"entrada": 10, "saida": 1, "total": 11, "cacheado": 0})
    assert contagem_do_turno()["cacheado"] == 0
