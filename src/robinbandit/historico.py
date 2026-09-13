"""Um contador por provedor e por dia: ok, erro e o pior motivo do dia.

O bandit decide com o que aconteceu agora, e isso é o certo para rotear. Mas
não responde à pergunta que se faz olhando a conta do mês: *quem passou mais
tempo no vermelho?* Um provedor que caiu um dia inteiro e voltou tem o mesmo
"erro" de um que falha toda semana — até você ver os dois lado a lado.

Um dia é uma linha. Sessenta dias cabem em 4 KB, e o arquivo é do dono da
máquina: o histórico dele não viaja no clone.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ARQUIVO = "historico.json"
# Dois meses: o bastante para ver um padrão e pouco o bastante para o arquivo
# não virar um banco que ninguém pediu.
DIAS_GUARDADOS = 60

_LOCK = threading.RLock()


def caminho() -> Path:
    casa = os.environ.get("ROBINBANDIT_HOME") or os.environ.get("SENTURY_HOME")
    base = Path(casa).expanduser() if casa else (Path.home() / ".robinbandit")
    return base / ARQUIVO


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
        # Perder o histórico é chato; derrubar o turno por causa dele é pior.
        logger.debug("Nao consegui gravar o historico: %s", exc)


def registrar(provedor: str, *, ok: bool, motivo: str = "") -> None:
    """Soma uma chamada ao dia de hoje."""
    chave = str(provedor or "").strip().lower()
    if not chave:
        return
    dia = _hoje()
    with _LOCK:
        dados = _ler()
        por_provedor = dados.setdefault(chave, {})
        linha = por_provedor.setdefault(dia, {"ok": 0, "err": 0, "motivo": ""})
        linha["ok" if ok else "err"] += 1
        if not ok and motivo:
            linha["motivo"] = str(motivo)[:80]

        # Poda aqui: sem isto o arquivo cresce para sempre, um dia por vez.
        if len(por_provedor) > DIAS_GUARDADOS:
            for velho in sorted(por_provedor)[:-DIAS_GUARDADOS]:
                por_provedor.pop(velho, None)
        _gravar(dados)


def _saude_do_dia(linha: Dict[str, Any]) -> str:
    """Verde, amarelo ou vermelho — a leitura que uma página de status faz."""
    ok, err = int(linha.get("ok", 0)), int(linha.get("err", 0))
    total = ok + err
    if not total:
        return "vazio"
    proporcao = ok / total
    if proporcao >= 0.99:
        return "ok"
    if proporcao >= 0.9:
        return "atencao"
    return "ruim"


def faixa(provedor: str, dias: int = DIAS_GUARDADOS) -> List[Dict[str, Any]]:
    """Os últimos `dias` de um provedor, do mais antigo para o mais novo.

    Dia sem chamada nenhuma entra como vazio: ausência não é falha, e pintar
    de vermelho o dia em que ninguém usou seria inventar um incidente.
    """
    por_provedor = _ler().get(str(provedor or "").strip().lower()) or {}
    hoje = datetime.now(timezone.utc)
    saida: List[Dict[str, Any]] = []
    for recuo in range(dias - 1, -1, -1):
        dia = datetime.fromtimestamp(hoje.timestamp() - recuo * 86400, timezone.utc).strftime("%Y-%m-%d")
        linha = por_provedor.get(dia) or {}
        saida.append({
            "dia": dia,
            "ok": int(linha.get("ok", 0)),
            "err": int(linha.get("err", 0)),
            "motivo": str(linha.get("motivo") or ""),
            "saude": _saude_do_dia(linha),
        })
    return saida


def resumo(provedores: Optional[List[str]] = None, dias: int = 30) -> List[Dict[str, Any]]:
    """Quem passou mais tempo no vermelho, e há quanto tempo foi.

    A ordem é por dias ruins, porque é essa a pergunta: um provedor bom que
    caiu um dia aparece com `dias_ruins: 1` e uptime alto — o bastante para
    você não julgá-lo pelo pior dia dele.
    """
    dados = _ler()
    alvos = [str(p).strip().lower() for p in (provedores or dados.keys())]
    saida: List[Dict[str, Any]] = []
    for nome in alvos:
        linhas = [linha for linha in faixa(nome, dias) if linha["saude"] != "vazio"]
        if not linhas:
            continue
        ok = sum(linha["ok"] for linha in linhas)
        err = sum(linha["err"] for linha in linhas)
        ruins = [linha for linha in linhas if linha["saude"] == "ruim"]
        saida.append({
            "provedor": nome,
            "dias_com_uso": len(linhas),
            "dias_ruins": len(ruins),
            "dias_de_atencao": sum(1 for linha in linhas if linha["saude"] == "atencao"),
            "uptime": round(ok / (ok + err) * 100, 2) if (ok + err) else None,
            "pior_dia": ruins[-1]["dia"] if ruins else "",
            "pior_motivo": ruins[-1]["motivo"] if ruins else "",
        })
    saida.sort(key=lambda item: (-item["dias_ruins"], item["uptime"] or 100))
    return saida


def esquecer() -> bool:
    with _LOCK:
        try:
            caminho().unlink()
            return True
        except OSError:
            return False


__all__ = ["DIAS_GUARDADOS", "caminho", "esquecer", "faixa", "registrar", "resumo"]
