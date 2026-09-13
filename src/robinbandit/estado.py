"""Onde o que o roteador aprendeu sobrevive ao restart.

Três coisas diferentes moram em três lugares, e confundi-las custa caro:

- **Priors** (`quality`, `tier`, `cost_class`) vão no YAML versionado. São um
  palpite inicial razoável, iguais para todo mundo.
- **Preferências** desta instalação vão em `~/.robinbandit/config.yaml`, lido
  por cima do YAML do repo.
- **O aprendizado** — qual provedor de fato rende aqui — mora aqui, e não vai
  para o repositório de jeito nenhum. Ele foi medido com ESTAS chaves, neste
  plano, nesta região. Entregar isso pronto a outra pessoa seria entregar um
  viés que ela nunca mediu.

Antes disso, quem salvava era o host, num Redis. Sem Redis configurado — o
caso normal numa instalação local — o bandit reaprendia do zero a cada
restart, e a exploração inicial era paga de novo toda vez.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Aprendizado velho demais descreve um mundo que mudou: modelo aposentado,
# plano trocado, chave nova. Depois disso é melhor medir de novo do que
# confiar no que ficou.
VALIDADE_S = 30 * 24 * 3600


def caminho() -> Path:
    """Arquivo do aprendizado. `ROBINBANDIT_HOME` aponta para outro lugar."""
    home = os.environ.get("ROBINBANDIT_HOME") or str(Path.home() / ".robinbandit")
    return Path(home) / "ranking.json"


def salvar(dados: Dict[str, Any]) -> bool:
    """Grava o que o roteador aprendeu. Falha aqui nunca derruba o turno."""
    if not isinstance(dados, dict) or not dados:
        return False
    alvo = caminho()
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"gravado_em": time.time(), "ranking": dados}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(alvo)
        return True
    except OSError as exc:
        logger.warning("RobinBandit: nao consegui gravar o aprendizado (%s): %s", alvo, exc)
        return False


def carregar() -> Optional[Dict[str, Any]]:
    """O que foi aprendido antes, se ainda vale."""
    alvo = caminho()
    if not alvo.exists():
        return None
    try:
        bruto = json.loads(alvo.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("RobinBandit: aprendizado ilegivel (%s): %s", alvo, exc)
        return None

    ranking = bruto.get("ranking")
    if not isinstance(ranking, dict):
        return None
    idade = time.time() - float(bruto.get("gravado_em") or 0)
    if idade > VALIDADE_S:
        logger.info(
            "RobinBandit: aprendizado de %.0f dias descartado; medindo de novo.",
            idade / 86400,
        )
        return None
    return ranking


def esquecer() -> bool:
    """Apaga o aprendizado. Para quando as chaves ou os planos mudaram e o que
    foi medido antes passou a descrever outro mundo."""
    try:
        caminho().unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("RobinBandit: nao consegui apagar o aprendizado: %s", exc)
        return False


__all__ = ["caminho", "carregar", "esquecer", "salvar", "VALIDADE_S"]
