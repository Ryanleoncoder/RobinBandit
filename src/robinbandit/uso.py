"""Uso de tokens e custo informado, por dia e por provedor.

Cada provedor já devolve ``last_usage`` e a cadeia soma o turno inteiro. O
número existia, era usado para decidir dentro do turno e depois era descartado.
Agora ele fica disponível no painel. O custo também é preservado quando a
resposta do provedor o informa; caso contrário, aparece como desconhecido.

Um dia é uma linha por provedor. Um ano cabe em alguns KB, e o arquivo é do
dono da máquina: o gasto dele não viaja no clone.

Não mantemos uma tabela local de preços. Preço muda por modelo, região e
promoção, e um valor calculado com tabela velha daria precisão falsa.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ARQUIVO = "uso.json"

# Um ano, que é o recorte do gráfico de contribuições e o horizonte em que a
# pergunta "gastei mais este ano?" faz sentido.
DIAS_GUARDADOS = 365

_LOCK = threading.RLock()


def caminho() -> Path:
    casa = os.environ.get("ROBINBANDIT_HOME") or str(Path.home() / ".robinbandit")
    return Path(casa) / ARQUIVO


def _hoje() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ler() -> Dict[str, Any]:
    try:
        dados = json.loads(caminho().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar(dados: Dict[str, Any]) -> None:
    alvo = caminho()
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(alvo)
    except OSError as exc:
        logger.debug("Nao consegui gravar o uso: %s", exc)


def registrar(provedor: str, uso: Optional[Dict[str, Any]]) -> None:
    """Soma o gasto de uma chamada ao dia de hoje."""
    chave = str(provedor or "").strip().lower()
    if not chave or not isinstance(uso, dict):
        return
    entrada = int(uso.get("entrada") or 0)
    saida = int(uso.get("saida") or 0)
    total = int(uso.get("total") or 0) or (entrada + saida)
    if not total:
        # Provedor que não informa uso não vira uma linha de zeros: isso faria
        # parecer que ele foi usado de graça.
        return
    cacheado = int(uso.get("cacheado") or 0)
    custo_bruto = uso.get("custo_usd")
    try:
        custo_usd = float(custo_bruto) if custo_bruto is not None else None
    except (TypeError, ValueError):
        custo_usd = None
    dia = _hoje()

    with _LOCK:
        dados = _ler()
        por_dia = dados.setdefault(dia, {})
        linha = por_dia.setdefault(chave, {
            "entrada": 0, "saida": 0, "total": 0, "cacheado": 0,
            "chamadas": 0, "custo_usd": 0.0, "chamadas_com_custo": 0,
        })
        linha["entrada"] += entrada
        linha["saida"] += saida
        linha["total"] += total
        linha["cacheado"] += cacheado
        linha["chamadas"] += 1
        if custo_usd is not None and custo_usd >= 0:
            linha["custo_usd"] = float(linha.get("custo_usd") or 0) + custo_usd
            linha["chamadas_com_custo"] = int(linha.get("chamadas_com_custo") or 0) + 1

        # Poda aqui: sem isto o arquivo cresce para sempre, um dia por vez.
        if len(dados) > DIAS_GUARDADOS:
            for velho in sorted(dados)[:-DIAS_GUARDADOS]:
                dados.pop(velho, None)
        _gravar(dados)


def _dias(quantos: int) -> List[str]:
    hoje = datetime.now(timezone.utc)
    return [
        datetime.fromtimestamp(hoje.timestamp() - recuo * 86400, timezone.utc).strftime("%Y-%m-%d")
        for recuo in range(quantos - 1, -1, -1)
    ]


def calendario(dias: int = DIAS_GUARDADOS, provedor: str = "") -> List[Dict[str, Any]]:
    """Um quadrado por dia, do mais antigo para o mais novo.

    Dia sem chamada entra com zero em vez de sumir: um calendário com buracos
    não se lê como calendário.
    """
    dados = _ler()
    alvo = str(provedor or "").strip().lower()
    saida = []
    for dia in _dias(max(1, min(int(dias or DIAS_GUARDADOS), DIAS_GUARDADOS))):
        linhas = dados.get(dia) or {}
        if alvo:
            linhas = {alvo: linhas[alvo]} if alvo in linhas else {}
        total = sum(int(l.get("total", 0)) for l in linhas.values())
        chamadas = sum(int(l.get("chamadas", 0)) for l in linhas.values())
        saida.append({"dia": dia, "total": total, "chamadas": chamadas})
    return saida


def por_provedor(dias: int = 30) -> List[Dict[str, Any]]:
    """Quem consumiu mais no período, do maior para o menor."""
    dados = _ler()
    acumulado: Dict[str, Dict[str, Any]] = {}
    for dia in _dias(max(1, min(int(dias or 30), DIAS_GUARDADOS))):
        for nome, linha in (dados.get(dia) or {}).items():
            alvo = acumulado.setdefault(
                nome, {
                    "entrada": 0, "saida": 0, "total": 0, "cacheado": 0,
                    "chamadas": 0, "custo_usd": 0.0, "chamadas_com_custo": 0,
                }
            )
            for campo in ("entrada", "saida", "total", "cacheado", "chamadas", "chamadas_com_custo"):
                alvo[campo] += int(linha.get(campo, 0))
            alvo["custo_usd"] += float(linha.get("custo_usd", 0) or 0)
    saida = [{"provedor": nome, **valores} for nome, valores in acumulado.items()]
    saida.sort(key=lambda item: -item["total"])
    return saida


def total(dias: int = 30) -> Dict[str, Any]:
    linhas = por_provedor(dias)
    return {
        "entrada": sum(l["entrada"] for l in linhas),
        "saida": sum(l["saida"] for l in linhas),
        "total": sum(l["total"] for l in linhas),
        "cacheado": sum(l["cacheado"] for l in linhas),
        "chamadas": sum(l["chamadas"] for l in linhas),
        "provedores": len(linhas),
        "custo_usd": round(sum(float(l["custo_usd"]) for l in linhas), 6),
        "chamadas_com_custo": sum(l["chamadas_com_custo"] for l in linhas),
    }


def esquecer() -> bool:
    with _LOCK:
        try:
            caminho().unlink()
            return True
        except OSError:
            return False


__all__ = [
    "DIAS_GUARDADOS", "calendario", "caminho", "esquecer",
    "por_provedor", "registrar", "total",
]
