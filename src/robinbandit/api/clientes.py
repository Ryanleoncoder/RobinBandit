"""Registro em memória de clientes que chamaram o RobinBandit."""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# Padrões de User-Agent; os mais específicos vêm primeiro.
ASSINATURAS: Tuple[Tuple[str, str], ...] = (
    ("claude-code", r"claude-cli|claude-code|anthropic-sdk"),
    # Sem `\b` no fim: o binário se apresenta como `codex_cli_rs`, e `_` conta
    # como caractere de palavra — a fronteira nunca casaria.
    ("codex", r"\bcodex"),
    ("cline", r"\bcline\b"),
    ("opencode", r"opencode"),
    ("curl", r"^curl/"),
    ("openai-sdk", r"openai|httpx|python-requests|node-fetch|axios"),
)

_COMPILADAS = tuple((nome, re.compile(padrao, re.I)) for nome, padrao in ASSINATURAS)

# Janela em que uma ferramenta ainda aparece como conectada.
JANELA_ATIVA = 1800.0

# Teto de clientes distintos guardados.
_MAX = 40


def detectar(user_agent: str) -> str:
    """Detecta o apelido da ferramenta a partir do User-Agent."""
    texto = (user_agent or "").strip()
    if not texto:
        return "outro"
    for nome, padrao in _COMPILADAS:
        if padrao.search(texto):
            return nome
    return "outro"


class Clientes:
    """Registro de quem chamou, por ferramenta."""

    def __init__(self, agora=time.time) -> None:
        self._agora = agora
        self._lock = threading.Lock()
        self._vistos: Dict[str, Dict[str, Any]] = {}

    def anotar(self, user_agent: str, contexto: Optional[str] = None) -> str:
        """Registra uma chamada. Devolve a ferramenta detectada."""
        nome = detectar(user_agent)
        with self._lock:
            atual = self._vistos.get(nome)
            if atual is None:
                if len(self._vistos) >= _MAX:
                    # Mantém os clientes mais recentes.
                    antigo = min(self._vistos, key=lambda k: self._vistos[k]["visto_em"])
                    self._vistos.pop(antigo, None)
                atual = {"chamadas": 0, "contextos": []}
                self._vistos[nome] = atual

            atual["chamadas"] += 1
            atual["visto_em"] = self._agora()
            atual["user_agent"] = (user_agent or "")[:120]
            if contexto and contexto not in atual["contextos"]:
                atual["contextos"] = (atual["contextos"] + [contexto])[-5:]
        return nome

    def status(self) -> List[Dict[str, Any]]:
        """O que a tela Conectar mostra, do mais recente para o mais antigo."""
        agora = self._agora()
        with self._lock:
            itens = [
                {
                    "id": nome,
                    "chamadas": dados["chamadas"],
                    "ha_segundos": round(agora - dados["visto_em"], 1),
                    "ativo": (agora - dados["visto_em"]) <= JANELA_ATIVA,
                    "contextos": list(dados["contextos"]),
                    "user_agent": dados["user_agent"],
                }
                for nome, dados in self._vistos.items()
            ]
        return sorted(itens, key=lambda i: i["ha_segundos"])

    def de(self, ferramenta: str) -> Optional[Dict[str, Any]]:
        for item in self.status():
            if item["id"] == ferramenta:
                return item
        return None


__all__ = ["ASSINATURAS", "Clientes", "JANELA_ATIVA", "detectar"]
