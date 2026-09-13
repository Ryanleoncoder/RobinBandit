"""A janela de uso das assinaturas — quanto falta para ela virar.

Provedor de API cobra por token e o limite é por minuto: o roteador já lida com
isso pelo header de rate-limit e pelo cooldown. Assinatura funciona de outro
jeito. Claude Code e Codex dão um bloco de uso que dura algumas horas e depois
recomeça do zero. Quando o bloco acaba, o provedor não fica "lento": ele para,
e volta numa hora que dá para saber.

Nada disso aparecia. O painel mostrava o provedor em cooldown com um prazo que
o roteador chutou a partir do último erro, e a pergunta que a pessoa realmente
faz — *quando eu posso usar o Opus de novo?* — não tinha resposta em lugar
nenhum.

Aqui a janela é contada a partir da primeira chamada dela. É o que o próprio
CLI faz, e não exige ler credencial nem chamar endpoint de cota: a primeira
chamada depois de um vazio abre um bloco novo, e o bloco fecha `horas` depois.
O relógio pode andar alguns minutos à frente do relógio deles; para decidir
"espero ou troco de provedor" isso basta, e é melhor do que não ter número.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ARQUIVO = "janelas.json"

# O bloco padrão das assinaturas de código hoje. Fica no YAML de quem quiser
# outro: `janela_horas` no provedor.
HORAS_PADRAO = 5.0

_LOCK = threading.RLock()


def caminho() -> Path:
    casa = os.environ.get("ROBINBANDIT_HOME") or str(Path.home() / ".robinbandit")
    return Path(casa) / ARQUIVO


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
        # Perder a contagem da janela é chato; derrubar o turno por causa dela
        # seria pior.
        logger.debug("Nao consegui gravar a janela: %s", exc)


def registrar(provedor: str, *, horas: float = HORAS_PADRAO, ok: bool = True,
              bloqueado: bool = False) -> None:
    """Conta uma chamada na janela corrente, abrindo uma nova se a anterior
    venceu."""
    chave = str(provedor or "").strip().lower()
    if not chave:
        return
    duracao = max(0.25, float(horas or HORAS_PADRAO)) * 3600.0
    agora = time.time()
    with _LOCK:
        dados = _ler()
        atual = dados.get(chave) or {}
        inicio = float(atual.get("inicio") or 0.0)
        if not inicio or agora - inicio >= duracao:
            # Bloco novo. O anterior não interessa mais: ele zerou de verdade.
            atual = {"inicio": agora, "chamadas": 0, "erros": 0, "bloqueios": 0}
        atual["horas"] = duracao / 3600.0
        atual["chamadas"] = int(atual.get("chamadas", 0)) + 1
        if not ok:
            atual["erros"] = int(atual.get("erros", 0)) + 1
        if bloqueado:
            # O que de fato significa "acabou a janela": parou por limite, não
            # por um erro qualquer.
            atual["bloqueios"] = int(atual.get("bloqueios", 0)) + 1
            atual["ultimo_bloqueio"] = agora
        dados[chave] = atual
        _gravar(dados)


def estado(provedor: str) -> Dict[str, Any]:
    """Onde a janela deste provedor está agora."""
    chave = str(provedor or "").strip().lower()
    atual = _ler().get(chave) or {}
    inicio = float(atual.get("inicio") or 0.0)
    horas = float(atual.get("horas") or HORAS_PADRAO)
    if not inicio:
        return {
            "provedor": chave, "aberta": False, "horas": horas,
            "chamadas": 0, "erros": 0, "bloqueios": 0,
            "falta_s": 0, "usado_s": 0, "fracao": 0.0, "vira_em": "",
        }
    agora = time.time()
    duracao = horas * 3600.0
    usado = agora - inicio
    if usado >= duracao:
        # Venceu e ninguém chamou desde então: a próxima chamada abre outra.
        return {
            "provedor": chave, "aberta": False, "horas": horas,
            "chamadas": 0, "erros": 0, "bloqueios": 0,
            "falta_s": 0, "usado_s": 0, "fracao": 0.0, "vira_em": "",
        }
    falta = duracao - usado
    return {
        "provedor": chave,
        "aberta": True,
        "horas": horas,
        "chamadas": int(atual.get("chamadas", 0)),
        "erros": int(atual.get("erros", 0)),
        "bloqueios": int(atual.get("bloqueios", 0)),
        "falta_s": int(falta),
        "usado_s": int(usado),
        "fracao": round(usado / duracao, 4),
        "vira_em": _relogio(falta),
    }


def _relogio(segundos: float) -> str:
    """"2h13" lê-se mais rápido que "8035 segundos"."""
    total = max(0, int(segundos))
    horas, resto = divmod(total, 3600)
    minutos = resto // 60
    if horas:
        return f"{horas}h{minutos:02d}"
    return f"{minutos} min" if minutos else "menos de 1 min"


def de_assinatura(config: Any) -> Dict[str, float]:
    """Quais provedores têm janela, e de quantas horas.

    Quem autentica pelo CLI oficial é assinatura por definição: não há chave
    para cobrar por token. `janela_horas` no YAML muda a duração de um deles.
    """
    saida: Dict[str, float] = {}
    for chave, spec in (getattr(config, "providers", {}) or {}).items():
        auth = str(spec.get("auth_type") or "").strip().lower()
        horas = spec.get("janela_horas")
        if auth.endswith("_cli") or horas:
            try:
                saida[chave] = float(horas or HORAS_PADRAO)
            except (TypeError, ValueError):
                saida[chave] = HORAS_PADRAO
    return saida


def resumo(config: Any) -> List[Dict[str, Any]]:
    """A janela de cada assinatura, da que vira antes para a que vira depois."""
    linhas = []
    for chave, horas in de_assinatura(config).items():
        linha = estado(chave)
        linha["horas"] = horas
        linhas.append(linha)
    # Quem está prestes a virar interessa mais: é a decisão de esperar ou não.
    linhas.sort(key=lambda item: (not item["aberta"], item["falta_s"]))
    return linhas


def esquecer() -> bool:
    with _LOCK:
        try:
            caminho().unlink()
            return True
        except OSError:
            return False


__all__ = ["HORAS_PADRAO", "caminho", "de_assinatura", "esquecer", "estado", "registrar", "resumo"]
