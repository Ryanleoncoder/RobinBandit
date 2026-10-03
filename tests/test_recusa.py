"""Recusa por política de conteúdo que chega como resposta: vira erro, a cadeia
passa ao próximo provedor sem castigar este, e o turno fica sabendo."""
import pytest

from robinbandit import ChainProvider, ProviderRouter, classify_error
from robinbandit.chain import FalhaDaCadeia, iniciar_contagem, recusas_do_turno
from robinbandit.providers import ReinforcedProvider
from robinbandit.providers.recusa import (
    RecusaDoModelo, recusa_anthropic, recusa_gemini, recusa_openai,
)


class _Prov:
    def __init__(self, roteiro, name):
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


def _cadeia(provedores):
    cadeia = ChainProvider(provedores, ProviderRouter())
    cadeia.router.order = lambda candidatos, *a, **k: list(candidatos)
    return cadeia


def test_sinais_de_recusa_de_cada_formato():
    assert recusa_openai({"message": {"refusal": "não posso"}}) == "não posso"
    assert recusa_openai({"finish_reason": "content_filter", "message": {"content": ""}}) == ""
    assert recusa_openai({"finish_reason": "stop", "message": {"content": "oi"}}) is None
    assert recusa_anthropic({"stop_reason": "refusal"}, "não vou") == "não vou"
    assert recusa_anthropic({"stop_reason": "end_turn"}) is None
    assert "SAFETY" in recusa_gemini({"candidates": [{"finishReason": "SAFETY"}]})
    assert "OTHER" in recusa_gemini({"promptFeedback": {"blockReason": "OTHER"}})
    assert recusa_gemini({"candidates": [{"finishReason": "STOP"}]}) is None
    assert recusa_gemini({"candidates": [{"finishReason": "MAX_TOKENS"}]}) is None


def test_recusa_e_classificada_como_politica_de_conteudo():
    assert classify_error(RecusaDoModelo("openai:gpt-x", "não posso")) == "content_policy"


async def test_cadeia_troca_de_provedor_sem_castigar_e_anota_a_recusa():
    iniciar_contagem()
    recusa = _Prov([RecusaDoModelo("rigido:m1", "não posso")], name="rigido")
    bom = _Prov(["resposta"], name="bom")
    cadeia = _cadeia([recusa, bom])
    castigos = []
    cadeia.router.record_failure = lambda *a, **k: castigos.append(a)

    assert await cadeia.complete([{"role": "user", "content": "oi"}]) == "resposta"
    assert recusa.calls == 1
    assert castigos == []
    assert recusas_do_turno() == [{"provedor": "rigido", "modelo": "rigido:m1"}]


async def test_todos_recusam_e_a_falha_diz_que_foi_politica():
    iniciar_contagem()
    cadeia = _cadeia([_Prov([RecusaDoModelo("a:m", "")], name="a"),
                      _Prov([RecusaDoModelo("b:m", "")], name="b")])
    with pytest.raises(FalhaDaCadeia) as falha:
        await cadeia.complete([{"role": "user", "content": "oi"}])
    assert falha.value.tipos == ["content_policy", "content_policy"]
    assert len(recusas_do_turno()) == 2


async def test_reforcado_devolve_a_recusa_quando_todas_as_contas_recusam():
    contas = [_Prov([RecusaDoModelo("c1:m", "")], name="c1"),
              _Prov([RecusaDoModelo("c2:m", "")], name="c2")]
    with pytest.raises(RecusaDoModelo):
        await ReinforcedProvider(contas).complete([{"role": "user", "content": "oi"}])
