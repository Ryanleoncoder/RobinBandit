"""Descobrir que a cota voltou sem esperar um turno real falhar.

O roteador já evita quem está perto do limite: o header de rate-limit alimenta
o `_quota_penalty`, e cada falha põe o provedor em cooldown com prazo. Isso
resolve o caminho normal.

O que não resolve: enquanto o provedor está fora, ninguém fala com ele. O
cooldown expira por tempo, não por evidência — se a cota voltou antes, o
roteador continua ignorando; se não voltou, o primeiro turno real depois do
prazo é que descobre, e quem paga é o usuário que estava esperando.

O ping é uma requisição mínima feita de propósito, fora de um turno, só para
saber. Custa cota para medir cota, e por isso **vem desligado**: só faz sentido
para quem tem provedor de assinatura com janela longa (5h, diária), onde
acertar o momento da volta vale mais que o punhado de tokens gasto.

Ligar em `routing.quota_ping.ativo: true`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

# Uma mensagem curta o suficiente para não custar nada relevante, e explícita
# sobre o que é — se aparecer num log de auditoria, tem que estar claro que não
# foi o usuário quem pediu.
_MENSAGEM = [{"role": "user", "content": "ping"}]

_CONFIG: Dict[str, Any] = {"ativo": False, "intervalo_s": 300.0, "so_em_cooldown": True}


def configurar(bruto: Optional[Mapping[str, Any]]) -> None:
    """Aplica `routing.quota_ping` do YAML."""
    global _CONFIG
    base = {"ativo": False, "intervalo_s": 300.0, "so_em_cooldown": True}
    if isinstance(bruto, Mapping):
        base["ativo"] = bool(bruto.get("ativo"))
        try:
            # Piso de um minuto: pingar mais rápido que isso gasta mais cota do
            # que a informação vale.
            base["intervalo_s"] = max(60.0, float(bruto.get("intervalo_s") or 300.0))
        except (TypeError, ValueError):
            pass
        if "so_em_cooldown" in bruto:
            base["so_em_cooldown"] = bool(bruto.get("so_em_cooldown"))
    _CONFIG = base


def ativo() -> bool:
    return bool(_CONFIG.get("ativo"))


def configuracao() -> Dict[str, Any]:
    return dict(_CONFIG)


def alvos(router: Any, provedores: List[Any]) -> List[Any]:
    """Quem vale pingar agora.

    Por padrão, só quem está em cooldown: pingar quem está saudável não
    descobre nada que o próximo turno real não descubra de graça.
    """
    if not _CONFIG.get("so_em_cooldown"):
        return list(provedores)
    escolhidos = []
    for provedor in provedores:
        nome = getattr(provedor, "name", None)
        if not nome:
            continue
        try:
            if router.cooldown_remaining(nome) > 0:
                escolhidos.append(provedor)
        except Exception:
            continue
    return escolhidos


async def pingar(router: Any, provedor: Any) -> Dict[str, Any]:
    """Uma chamada mínima. O resultado alimenta o roteador como qualquer outra.

    Um ping que passa NÃO tira o provedor do cooldown por conta própria: ele
    registra o sucesso e deixa o roteador decidir. Cancelar o castigo aqui
    seria dar à sonda um poder que a medição real não tem.
    """
    nome = getattr(provedor, "name", "?")
    inicio = time.time()
    try:
        await provedor.complete(_MENSAGEM, temperature=0.0)
    except Exception as exc:
        from .erros import classificar

        tipo = classificar(exc)
        router.record_failure(nome, tipo, detail="quota_ping")
        return {"provedor": nome, "ok": False, "tipo": tipo}

    ms = int((time.time() - inicio) * 1000)
    router.record_success(nome, ms, model=getattr(provedor, "last_model", None))
    quota = getattr(provedor, "last_quota", None)
    if isinstance(quota, dict):
        router.record_quota(nome, quota.get("rpm"), quota.get("rpd"))
    return {"provedor": nome, "ok": True, "ms": ms}


async def rodada(router: Any, provedores: List[Any]) -> List[Dict[str, Any]]:
    """Uma passada por todos os alvos. Sem alvo, não gasta nada."""
    if not ativo():
        return []
    escolhidos = alvos(router, provedores)
    if not escolhidos:
        return []
    return [await pingar(router, provedor) for provedor in escolhidos]


async def laco(router: Any, provedores: List[Any]) -> None:
    """Roda até ser cancelado. Quem liga é o host, no arranque."""
    intervalo = float(_CONFIG.get("intervalo_s") or 300.0)
    logger.info("RobinBandit: quota ping ligado (a cada %.0fs)", intervalo)
    while True:
        try:
            await asyncio.sleep(intervalo)
            resultado = await rodada(router, provedores)
            if resultado:
                logger.debug("RobinBandit: quota ping -> %s", resultado)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("RobinBandit: falha no quota ping: %s", exc)


__all__ = ["ativo", "configuracao", "configurar", "laco", "pingar", "rodada", "alvos"]
