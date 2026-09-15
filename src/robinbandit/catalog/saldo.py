"""Quanto ainda há para gastar em cada credencial.

Isto é assunto de provedor, e portanto do Robin. Estava no host: uma lista com
onze nomes de variável escritos à mão, o teste de qual delas era OpenRouter, e
a chamada à API de saldo. Declarar um provedor novo no YAML não bastava — era
preciso lembrar de editar o host também, e esquecer significava a chave nova
simplesmente não aparecer no painel.

Aqui as credenciais saem da própria declaração (`api_key_env` de cada
provedor), então um provedor novo aparece por existir.

Nada aqui devolve o valor de uma chave. O que atravessa é o NOME da variável,
um índice opaco e o saldo — nem prefixo, nem sufixo, nem contagem de
caracteres.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Consultar saldo é uma chamada de rede por chave. Numa tela que atualiza
# sozinha isso vira tráfego constante para um número que muda devagar.
CACHE_S = 30.0
_CACHE: Dict[str, Any] = {"em": 0.0, "valor": {}}

# Provedores que publicam saldo. Quem não está aqui não é "sem saldo": é
# "não informa", e a diferença importa na tela.
CONSULTA_DE_SALDO = {
    "openrouter": "https://openrouter.ai/api/v1/auth/key",
}


def _valor_do_ambiente(settings: Any, *nomes: str) -> str:
    import os

    for nome in nomes:
        if not nome:
            continue
        valor = getattr(settings, nome, None) if settings is not None else None
        if not valor:
            valor = os.environ.get(nome)
        if valor:
            return str(valor)
    return ""


def credenciais(config: Any, settings: Any = None) -> List[Dict[str, Any]]:
    """Uma entrada por chave configurada, descoberta da declaração.

    Multi-chave (CSV) vira várias entradas: quem separou por vírgula tem duas
    cotas, e mostrá-las como uma esconde metade do que ele tem.
    """
    vistas: set = set()
    saida: List[Dict[str, Any]] = []
    for chave_provedor, spec in (getattr(config, "providers", {}) or {}).items():
        if spec.get("enabled") is False:
            continue
        nome_var = str(spec.get("api_key_env") or "")
        bruto = _valor_do_ambiente(
            settings, nome_var, str(spec.get("api_key_fallback_env") or "")
        )
        if not bruto:
            continue
        for parte in str(bruto).split(","):
            parte = parte.strip()
            if not parte or parte in vistas:
                continue
            vistas.add(parte)
            saida.append({
                "provedor": chave_provedor,
                "rotulo": str(spec.get("label") or chave_provedor),
                "variavel": nome_var,
                "_chave": parte,          # nunca sai deste módulo
            })
    return saida


async def _saldo_openrouter(cliente: Any, chave: str, url: str) -> Dict[str, Any]:
    try:
        resposta = await cliente.get(
            url, headers={"Authorization": f"Bearer {chave}"}, timeout=2.5
        )
    except Exception as exc:
        return {"status": "error", "detalhe": f"{type(exc).__name__}"}
    if resposta.status_code != 200:
        return {"status": "error", "detalhe": f"HTTP {resposta.status_code}"}
    dados = resposta.json().get("data", {}) or {}
    limite = dados.get("limit")
    usado = dados.get("usage", 0.0) or 0.0
    return {
        "status": "active",
        "limite": limite,
        "usado": usado,
        "saldo": (limite - usado) if limite is not None else None,
    }


async def consultar(config: Any, settings: Any = None) -> List[Dict[str, Any]]:
    """Estado de cada credencial, para o painel."""
    itens = credenciais(config, settings)
    if not itens:
        return []

    agora = time.time()
    consultaveis = [i for i in itens if i["provedor"] in CONSULTA_DE_SALDO]
    if consultaveis and (agora - float(_CACHE["em"])) >= CACHE_S:
        import httpx

        medidos: Dict[str, Any] = {}
        async with httpx.AsyncClient() as cliente:
            for item in consultaveis:
                medidos[item["_chave"]] = await _saldo_openrouter(
                    cliente, item["_chave"], CONSULTA_DE_SALDO[item["provedor"]]
                )
        _CACHE.update(em=agora, valor=medidos)

    medidos = dict(_CACHE["valor"] or {})
    saida = []
    for indice, item in enumerate(itens):
        entrada = {
            "provedor": item["provedor"],
            "rotulo": item["rotulo"],
            "variavel": item["variavel"],
            "indice": indice,
        }
        medida = medidos.get(item["_chave"])
        if medida is None:
            # Não informa saldo não é o mesmo que não ter saldo.
            entrada.update({"status": "sem_medicao", "usado": None, "saldo": None})
        else:
            entrada.update(medida)
        saida.append(entrada)
    return saida


def limpar_cache() -> None:
    _CACHE.update(em=0.0, valor={})


__all__ = ["CACHE_S", "CONSULTA_DE_SALDO", "consultar", "credenciais", "limpar_cache"]
