"""Diagnóstico da configuração de contas.

Ter várias chaves no mesmo provedor significa coisas diferentes conforme o
custo:

- Num provedor **grátis**, duas chaves multiplicam a cota. É o objetivo.
- Num provedor **misto ou pago**, duas chaves na MESMA variável são um
  problema silencioso: o rodízio não sabe qual delas é a paga, então não dá
  para reservar a paga para o tier caro nem para dizer qual conta gastou.

O aviso existe porque isso não aparece sozinho: tudo "funciona", só que o
roteamento por custo vira sorteio. A saída é uma conta nomeada por chave,
cada uma na sua variável.
"""
from __future__ import annotations

from typing import Any, Dict, List

CUSTOS_QUE_EXIGEM_SEPARACAO = {"mixed", "paid", "credits", "subscription"}


def _chaves(settings: Any, variavel: str) -> int:
    from .credentials import parse_keys

    return len(parse_keys(getattr(settings, variavel, "") or ""))


def diagnosticar(config: Any, settings: Any, contas: List[Dict[str, Any]] | None = None) -> List[Dict[str, str]]:
    """Avisos sobre a configuração atual. Lista vazia é boa notícia."""
    avisos: List[Dict[str, str]] = []
    declaradas = {str(c.get("key_env") or "").upper() for c in (contas or [])}
    # Só quem está na cadeia. O catálogo tem dezenas de provedores prontos para
    # plugar, e avisar "falta a chave" de cada um transforma o diagnóstico numa
    # lista de coisas que ninguém escolheu usar.
    na_cadeia = {str(nome).strip().lower() for nome in (getattr(config, "chain_order", None) or [])}

    for chave, spec in (getattr(config, "providers", {}) or {}).items():
        if na_cadeia and str(chave).strip().lower() not in na_cadeia:
            continue
        variavel = str(spec.get("api_key_env") or "").strip()
        if not variavel:
            continue
        quantas = _chaves(settings, variavel)
        custo = str(spec.get("cost_class") or "").strip().lower()
        # Alguns provedores declaram uma variavel de reserva (o Dedicado cai na
        # chave do Reforcado). Sem olhar isso, o diagnostico acusa falta de
        # chave onde o proprio YAML ja resolveu.
        reserva = str(spec.get("api_key_fallback_env") or "").strip()
        if quantas == 0 and reserva and _chaves(settings, reserva) > 0:
            avisos.append({
                "provedor": chave,
                "gravidade": "ok",
                "titulo": f"usa {reserva} como reserva",
                "detalhe": f"{variavel} nao existe, e o YAML declara {reserva} como reserva. Funciona por desenho.",
            })
            continue

        if quantas > 1 and custo in CUSTOS_QUE_EXIGEM_SEPARACAO:
            avisos.append({
                "provedor": chave,
                "gravidade": "atencao",
                "titulo": f"{quantas} chaves em {variavel}, e o custo é '{custo}'",
                "detalhe": (
                    "Com as chaves juntas na mesma variável, o rodízio não sabe qual é a paga: "
                    "não dá para reservar a paga para o tier caro nem saber qual conta gastou. "
                    f"Separe em uma conta nomeada por chave (ex.: {variavel}_PAGA) e marque qual é paga."
                ),
            })
        elif quantas > 1:
            avisos.append({
                "provedor": chave,
                "gravidade": "ok",
                "titulo": f"{quantas} chaves em {variavel}",
                "detalhe": "Provedor gratuito: chaves em rodízio multiplicam a cota. É o comportamento esperado.",
            })

        if quantas == 0 and variavel not in declaradas:
            avisos.append({
                "provedor": chave,
                "gravidade": "info",
                "titulo": f"{variavel} não está no ambiente",
                "detalhe": "O provedor fica fora da cadeia até a chave existir.",
            })

    for conta in contas or []:
        variavel = str(conta.get("key_env") or "").strip()
        if variavel and not conta.get("configurada") and conta.get("auth_type") != "codex_cli":
            avisos.append({
                "provedor": str(conta.get("provider") or ""),
                "gravidade": "atencao",
                "titulo": f"conta '{conta.get('id')}' declarada sem chave",
                "detalhe": f"A conta aponta para {variavel}, que ainda não tem valor no ambiente nem no cofre.",
            })

    return avisos
