"""Como o roteador reage ao erro de um provedor — a tabela, nao o algoritmo.

Estava em Python: `classify_error` com if/elif e cinco constantes de cooldown.
Mas isto e politica, nao algoritmo. O que conta como "sem credito" muda quando
um provedor troca a redacao da mensagem, e o tempo certo de espera muda por
instalacao e por plano contratado. Nenhuma das duas coisas deveria exigir uma
versao nova.

A tabela vem do YAML do proprio Robin (`routing.erros`). Sem ela, valem os
padroes daqui — o roteador nunca fica sem saber o que fazer com um erro.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

# A ORDEM importa: "sem credito" precisa ser visto antes de "cota", porque a
# mensagem de credito esgotado as vezes tambem cita quota — e tratar dinheiro
# acabado como rate limit faz o roteador insistir em quem nao vai voltar.
REGRAS_PADRAO: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("credit", ("402", "insufficient", "payment required", "billing", "out of credit",
                "credits", "exceeded your current quota", "not enough balance", "spend limit")),
    ("rate_limit", ("429", "too many requests", "rate limit", "rate_limit", "quota",
                    "overloaded", "capacity")),
    ("auth", ("401", "403", "invalid api key", "unauthorized", "permission")),
    ("network", ("timeout", "timed out", "connect", "network")),
)

COOLDOWN_PADRAO: Dict[str, Any] = {
    "rate_limit": (60.0, 120.0, 300.0),   # escala com 429 consecutivos
    "credit": 1800.0,                      # credito esgotado ($) - so volta no billing
    "auth": 3600.0,                        # chave ruim nao melhora sozinha
    "network": 30.0,
    "other": 45.0,
}

_REGRAS = REGRAS_PADRAO
_COOLDOWNS = dict(COOLDOWN_PADRAO)


def configurar(bruto: Optional[Mapping[str, Any]]) -> None:
    """Aplica a secao `routing.erros` do YAML. Sem ela, ficam os padroes."""
    global _REGRAS, _COOLDOWNS
    if not isinstance(bruto, Mapping):
        _REGRAS, _COOLDOWNS = REGRAS_PADRAO, dict(COOLDOWN_PADRAO)
        return

    regras = []
    for item in bruto.get("regras") or []:
        if not isinstance(item, Mapping):
            continue
        termos = tuple(str(t).lower() for t in (item.get("quando_texto") or []))
        if termos:
            regras.append((str(item.get("tipo") or "other"), termos))
    _REGRAS = tuple(regras) or REGRAS_PADRAO

    cooldowns = dict(COOLDOWN_PADRAO)
    for tipo, valor in (bruto.get("cooldown_s") or {}).items():
        if isinstance(valor, Mapping) and valor.get("escala"):
            cooldowns[str(tipo)] = tuple(float(v) for v in valor["escala"])
        elif isinstance(valor, (int, float)):
            cooldowns[str(tipo)] = float(valor)
    _COOLDOWNS = cooldowns


def classificar(exc: Exception) -> str:
    """Tipo do erro. A tabela e lida de cima para baixo; a primeira que casa
    decide, e cada tipo tem consequencia diferente no cooldown."""
    texto = str(exc).lower()
    for tipo, termos in _REGRAS:
        if any(termo in texto for termo in termos):
            return tipo
    return "other"


def cooldown_de(tipo: str, repeticoes: int = 1) -> float:
    """Segundos de espera para este tipo de falha.

    Falha repetida avanca um degrau da escala e o ultimo se mantem: insistir
    no mesmo intervalo depois do terceiro 429 seguido so gera mais 429.
    """
    valor = _COOLDOWNS.get(tipo, COOLDOWN_PADRAO["other"])
    if isinstance(valor, tuple):
        return valor[min(max(repeticoes, 1) - 1, len(valor) - 1)]
    return float(valor)


__all__ = ["classificar", "configurar", "cooldown_de", "COOLDOWN_PADRAO", "REGRAS_PADRAO"]
