"""Quem está falando com o RobinBandit, e quando falou pela última vez.

A tela Conectar entrega a configuração pronta e para por aí: quem copiou não
descobre se colou no lugar certo até tentar usar o agente e ver dar errado. O
`User-Agent` de cada chamada já dizia quem era — só não estava sendo lido.

Isto é memória de processo, como cooldown e ocupação: reiniciou, esqueceu. Não
vale gravar em disco, porque a pergunta que a tela responde é "está conectado
**agora**", e não "já conectou algum dia".
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# Cada ferramenta assina o que envia. Os padrões vêm do que cada cliente põe no
# User-Agent; a ordem importa, porque o SDK da OpenAI aparece dentro do
# User-Agent de ferramentas que o embutem — o mais específico casa primeiro.
#
# Errar um padrão aqui não esconde ninguém: quem não casa aparece como "outro"
# com o User-Agent cru do lado, e a tela continua útil.
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

# Passado disto, a tela para de dizer "conectado". Meia hora é generoso para um
# agente aberto e ocioso, e curto o bastante para não afirmar que está de pé
# uma ferramenta que foi fechada hoje de manhã.
JANELA_ATIVA = 1800.0

# Teto de clientes distintos guardados. Um User-Agent por versão de ferramenta
# multiplica as entradas, e isto aqui não é para virar inventário.
_MAX = 40


def detectar(user_agent: str) -> str:
    """O apelido da ferramenta, a partir do User-Agent.

    Devolve o mesmo `id` que `cli_tools` usa, para a tela casar as duas coisas
    sem tabela de tradução no meio.
    """
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
                    # Sai quem falou há mais tempo: o registro é sobre agora.
                    antigo = min(self._vistos, key=lambda k: self._vistos[k]["visto_em"])
                    self._vistos.pop(antigo, None)
                atual = {"chamadas": 0, "contextos": []}
                self._vistos[nome] = atual

            atual["chamadas"] += 1
            atual["visto_em"] = self._agora()
            atual["user_agent"] = (user_agent or "")[:120]
            if contexto and contexto not in atual["contextos"]:
                # Os apelidos de trabalho que essa ferramenta usou, para a tela
                # mostrar que `model` virou contexto de verdade.
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
