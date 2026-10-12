"""Classificação restrita não herda geração longa nem altera respostas normais."""
import copy
import json

import pytest

from robinbandit.providers.gemini_provider import GeminiProvider, _usage_gemini
from robinbandit.routing.classificacao import contrato


def simular(monkeypatch, texto='"STANDARD"', usage=None):
    pedidos = []

    class Resposta:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": texto}]}}],
                    "usageMetadata": usage or {"promptTokenCount": 100, "candidatesTokenCount": 2, "totalTokenCount": 102}}

    class Cliente:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            pedidos.append(copy.deepcopy(kwargs["json"]))
            return Resposta()

    monkeypatch.setattr("robinbandit.providers.gemini_provider.httpx.AsyncClient", Cliente)
    return pedidos


@pytest.mark.asyncio
@pytest.mark.parametrize("modelo", ["gemini-2.5-flash", "gemini-2.5-flash-lite"])
async def test_flash_classifica_sem_thinking_com_enum_e_teto_curto(monkeypatch, modelo):
    pedidos = simular(monkeypatch)
    provedor = GeminiProvider("chave-de-teste", [modelo])
    assert await provedor.complete([{"role": "user", "content": "pedido"}], complexity="CLASSIFY",
                                   classification_labels=contrato()["rotulos"]) == "STANDARD"
    cfg = pedidos[0]["generationConfig"]
    assert cfg["thinkingConfig"] == {"includeThoughts": False, "thinkingBudget": 0}
    assert cfg["maxOutputTokens"] == 16
    assert cfg["responseJsonSchema"] == {"type": "string", "enum": contrato()["rotulos"]}
    assert cfg["responseMimeType"] == "application/json"
    assert "tools" not in pedidos[0]
    assert provedor.last_usage == {"entrada": 100, "saida": 2, "total": 102, "raciocinio": 0}


@pytest.mark.asyncio
async def test_resposta_normal_nao_recebe_enum_nem_budget_zero(monkeypatch):
    pedidos = simular(monkeypatch, texto="Resposta normal")
    p = GeminiProvider("chave-de-teste", ["gemini-2.5-flash"])
    assert await p.complete([{"role": "user", "content": "pedido"}]) == "Resposta normal"
    cfg = pedidos[0]["generationConfig"]
    assert cfg["maxOutputTokens"] >= 4096
    assert "thinkingBudget" not in cfg["thinkingConfig"]
    assert cfg["thinkingConfig"]["includeThoughts"]
    assert "responseJsonSchema" not in cfg


@pytest.mark.asyncio
async def test_modelo_sem_suporte_a_desligar_pensamento_preserva_limite(monkeypatch):
    pedidos = simular(monkeypatch)
    p = GeminiProvider("chave-de-teste", ["gemini-2.5-pro"])
    assert await p.complete([{"role": "user", "content": "pedido"}], complexity="CLASSIFY",
                            classification_labels=contrato()["rotulos"]) == "STANDARD"
    assert "thinkingBudget" not in pedidos[0]["generationConfig"]["thinkingConfig"]
    assert pedidos[0]["generationConfig"]["maxOutputTokens"] == 512


@pytest.mark.asyncio
@pytest.mark.parametrize("texto", ['{"nivel":"STANDARD"}', '"STANDARD porque sim"', '"fora"', 'STANDARD'])
async def test_nao_aceita_formato_ou_rotulo_fora_do_enum(monkeypatch, texto):
    simular(monkeypatch, texto)
    p = GeminiProvider("chave-de-teste", ["gemini-2.5-flash"])
    with pytest.raises(RuntimeError):
        await p.complete([{"role": "user", "content": "pedido"}], complexity="CLASSIFY",
                         classification_labels=contrato()["rotulos"])


def test_uso_separa_raciocinio_sem_estimar_o_campo_ausente():
    assert _usage_gemini({"usageMetadata": {"promptTokenCount": 359, "candidatesTokenCount": 2,
                                           "thoughtsTokenCount": 490, "totalTokenCount": 851}}) == {
        "entrada": 359, "saida": 2, "raciocinio": 490, "total": 851,
    }
    assert "raciocinio" not in _usage_gemini({"usageMetadata": {
        "promptTokenCount": 359, "candidatesTokenCount": 2, "totalTokenCount": 851}})
