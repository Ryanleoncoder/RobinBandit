"""Uso de tokens e custo informado, por dia e por provedor."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from .trava import bloquear

logger = logging.getLogger(__name__)

ARQUIVO = "uso.json"

# Horizonte do calendário de uso.
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
        tmp = alvo.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(alvo)
    except OSError as exc:
        logger.debug("Nao consegui gravar o uso: %s", exc)


def registrar(provedor: str, uso: Optional[Dict[str, Any]]) -> None:
    """Soma o gasto de uma chamada ao dia de hoje."""
    chave = str(provedor or "").strip().lower()
    if not chave:
        return
    informado = isinstance(uso, dict) and any(k in uso for k in ("entrada", "saida", "total"))
    uso = uso if isinstance(uso, dict) else {}
    entrada = int(uso.get("entrada") or 0)
    saida = int(uso.get("saida") or 0)
    raciocinio = max(0, int(uso.get("raciocinio") or 0))
    total = int(uso.get("total") or 0) or (entrada + saida + raciocinio)
    cacheado = int(uso.get("cacheado") or 0)
    custo_bruto = uso.get("custo_usd")
    try:
        custo_usd = float(custo_bruto) if custo_bruto is not None else None
    except (TypeError, ValueError):
        custo_usd = None
    dia = _hoje()

    with _LOCK, bloquear(caminho()):
        dados = _ler()
        por_dia = dados.setdefault(dia, {})
        linha = por_dia.setdefault(chave, {
            "entrada": 0, "saida": 0, "total": 0, "cacheado": 0,
            "chamadas": 0, "custo_usd": 0.0, "chamadas_com_custo": 0,
            "chamadas_com_uso": 0, "chamadas_sem_uso": 0,
        })
        anteriores = int(linha.get("chamadas", 0))
        linha["chamadas_com_uso"] = int(linha.get("chamadas_com_uso", anteriores)) + int(informado)
        linha["chamadas_sem_uso"] = int(linha.get("chamadas_sem_uso", 0)) + int(not informado)
        linha["entrada"] += entrada
        linha["saida"] += saida
        linha["raciocinio"] = int(linha.get("raciocinio", 0)) + raciocinio
        linha["chamadas_com_raciocinio"] = int(linha.get("chamadas_com_raciocinio", 0)) + int("raciocinio" in uso)
        linha["total"] += total
        linha["cacheado"] += cacheado
        linha["chamadas"] += 1
        if custo_usd is not None and custo_usd >= 0:
            linha["custo_usd"] = float(linha.get("custo_usd") or 0) + custo_usd
            linha["chamadas_com_custo"] = int(linha.get("chamadas_com_custo") or 0) + 1

        # Mantém o arquivo limitado ao horizonte configurado.
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


def _detalhamento(linha):
    raciocinio = int(linha.get("raciocinio", 0))
    return {"raciocinio": raciocinio,
            "chamadas_com_raciocinio": int(linha.get("chamadas_com_raciocinio", 0)),
            "nao_detalhados": max(0, int(linha.get("total", 0)) - int(linha.get("entrada", 0))
                                   - int(linha.get("saida", 0)) - raciocinio)}


def calendario(dias: int = DIAS_GUARDADOS, provedor: str = "") -> List[Dict[str, Any]]:
    """Um ponto por dia, do mais antigo para o mais novo."""
    dados = _ler()
    alvo = str(provedor or "").strip().lower()
    saida = []
    for dia in _dias(max(1, min(int(dias or DIAS_GUARDADOS), DIAS_GUARDADOS))):
        linhas = dados.get(dia) or {}
        if alvo:
            linhas = {alvo: linhas[alvo]} if alvo in linhas else {}
        entrada = sum(int(l.get("entrada", 0)) for l in linhas.values())
        saida_tokens = sum(int(l.get("saida", 0)) for l in linhas.values())
        total = sum(int(l.get("total", 0)) for l in linhas.values())
        cacheado = sum(int(l.get("cacheado", 0)) for l in linhas.values())
        chamadas = sum(int(l.get("chamadas", 0)) for l in linhas.values())
        chamadas_com_custo = sum(
            int(l.get("chamadas_com_custo", 0)) for l in linhas.values()
        )
        chamadas_com_uso = sum(int(l.get("chamadas_com_uso", l.get("chamadas", 0))) for l in linhas.values())
        chamadas_sem_uso = sum(int(l.get("chamadas_sem_uso", 0)) for l in linhas.values())
        custo_usd = round(
            sum(float(l.get("custo_usd", 0) or 0) for l in linhas.values()), 6
        )
        saida.append({
            "dia": dia,
            **{k: sum(_detalhamento(l)[k] for l in linhas.values())
               for k in ("raciocinio", "chamadas_com_raciocinio", "nao_detalhados")},
            "entrada": entrada,
            "saida": saida_tokens,
            "total": total,
            "cacheado": cacheado,
            "chamadas": chamadas,
            "custo_usd": custo_usd,
            "chamadas_com_custo": chamadas_com_custo,
            "chamadas_com_uso": chamadas_com_uso,
            "chamadas_sem_uso": chamadas_sem_uso,
        })
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
                    "chamadas_com_uso": 0, "chamadas_sem_uso": 0,
                }
            )
            for campo in ("entrada", "saida", "total", "cacheado", "chamadas", "chamadas_com_custo"):
                alvo[campo] += int(linha.get(campo, 0))
            for campo, valor in _detalhamento(linha).items():
                alvo[campo] = alvo.get(campo, 0) + valor
            alvo["custo_usd"] += float(linha.get("custo_usd", 0) or 0)
            alvo["chamadas_com_uso"] += int(linha.get("chamadas_com_uso", linha.get("chamadas", 0)))
            alvo["chamadas_sem_uso"] += int(linha.get("chamadas_sem_uso", 0))
    saida = [{"provedor": nome, **valores} for nome, valores in acumulado.items()]
    saida.sort(key=lambda item: -item["total"])
    return saida


def total(dias: int = 30) -> Dict[str, Any]:
    linhas = por_provedor(dias)
    return {
        **{k: sum(l.get(k, 0) for l in linhas) for k in ("raciocinio", "chamadas_com_raciocinio", "nao_detalhados")},
        "entrada": sum(l["entrada"] for l in linhas),
        "saida": sum(l["saida"] for l in linhas),
        "total": sum(l["total"] for l in linhas),
        "cacheado": sum(l["cacheado"] for l in linhas),
        "chamadas": sum(l["chamadas"] for l in linhas),
        "provedores": len(linhas),
        "custo_usd": round(sum(float(l["custo_usd"]) for l in linhas), 6),
        "chamadas_com_custo": sum(l["chamadas_com_custo"] for l in linhas),
        "chamadas_com_uso": sum(l["chamadas_com_uso"] for l in linhas),
        "chamadas_sem_uso": sum(l["chamadas_sem_uso"] for l in linhas),
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
