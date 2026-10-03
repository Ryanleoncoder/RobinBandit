"""Tabela de classificação de erros e cooldowns."""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple

# A ordem importa: a primeira regra que casar decide.
#
# Erros do pedido vêm antes dos de cota: uma requisição grande demais
# não deve ser repetida nem reduzir a saúde do provedor.
#
# Credito vem antes de cota porque crédito esgotado pode citar quota.
REGRAS_PADRAO: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("request_too_large", ("413", "request too large", "payload too large",
                           "request entity too large")),
    ("context_length", ("context_length_exceeded", "maximum context length", "context window",
                        "prompt is too long", "input token count", "exceeds the maximum number of tokens",
                        # Nao "too many tokens": o Bedrock diz isso para COTA
                        # ("please wait before trying again").
                        "reduce the length")),
    ("content_policy", ("content_filter", "content policy", "content management policy",
                        "responsible ai", "flagged by", "blocked by safety", "finish_reason: safety",
                        "safety settings")),
    ("credit", ("402", "insufficient", "payment required", "billing", "out of credit",
                "credits", "exceeded your current quota", "not enough balance", "spend limit")),
    ("rate_limit", ("429", "too many requests", "rate limit", "rate_limit", "quota",
                    "overloaded", "capacity", "throttl")),
    ("auth", ("401", "403", "invalid api key", "unauthorized", "permission")),
    ("not_found", ("404", "model_not_found", "model not found", "no such model",
                   "does not exist", "unknown model")),
    # A regra transitória precede a de rede porque ambas casam com "gateway timeout".
    ("transient", ("500", "502", "503", "504", "service unavailable", "temporarily unavailable",
                   "bad gateway", "gateway timeout", "internal server error")),
    ("network", ("timeout", "timed out", "connect", "network")),
)

# O defeito e do PEDIDO, nao do provedor: outro provedor (janela maior, outra
# politica, outro limite de tamanho) pode aceitar. Nao entra na saude nem no
# cooldown — o provedor continua otimo para o proximo pedido de tamanho normal.
DA_REQUISICAO = frozenset({"request_too_large", "context_length", "content_policy"})

# Falhas transitórias permitem nova tentativa no provedor atual.
TRANSITORIOS = frozenset({"rate_limit", "transient"})

COOLDOWN_PADRAO: Dict[str, Any] = {
    "rate_limit": (60.0, 120.0, 300.0),   # escala com 429 consecutivos
    "credit": 1800.0,                      # credito esgotado ($) - so volta no billing
    "auth": 3600.0,                        # chave ruim nao melhora sozinha
    "not_found": 600.0,                    # modelo sumiu ou nome errado: configuracao
    "transient": 20.0,                     # 5xx: o servidor volta rapido ou nao volta
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


def _casa(termo: str, texto: str) -> bool:
    """Codigo HTTP casa como palavra; o resto, como trecho.

    Como trecho, "413" casava em "Requested 10413 tokens" e "500" em
    "limit 1500": o numero de tokens da mensagem decidia o tipo do erro.
    """
    if termo.isdigit():
        return re.search(rf"(?<!\d){termo}(?!\d)", texto) is not None
    return termo in texto


def _na_cadeia(exc: BaseException, limite: int = 6):
    """O erro e os que ele carrega (`raise ... from`), do mais externo ao original.

    O provedor tenta cada modelo, guarda o ultimo erro e levanta um
    `RuntimeError` com o texto dele: o `httpx.HTTPStatusError` original, que
    tem o codigo e o corpo da resposta, so sobrevive dentro da cadeia.
    """
    vistos = set()
    atual: Optional[BaseException] = exc
    while atual is not None and id(atual) not in vistos and len(vistos) < limite:
        vistos.add(id(atual))
        yield atual
        atual = atual.__cause__ or atual.__context__


def status_http(exc: BaseException) -> Optional[int]:
    """O codigo HTTP da falha, se algum erro da cadeia o traz."""
    for erro in _na_cadeia(exc):
        for fonte in (erro, getattr(erro, "response", None)):
            valor = getattr(fonte, "status_code", None) or getattr(fonte, "status", None)
            if isinstance(valor, int) and 100 <= valor <= 599:
                return valor
    return None


def _texto(exc: BaseException) -> str:
    """Mensagem de cada erro da cadeia MAIS o corpo da resposta.

    O `str()` de um erro do httpx diz so "Client error '400 Bad Request'": o
    "context_length_exceeded" e o "content_filter" estao no corpo. Sem ler o
    corpo, contexto estourado e politica de conteudo viravam `other`.
    """
    partes = []
    for erro in _na_cadeia(exc):
        partes.append(str(erro))
        resposta = getattr(erro, "response", None)
        try:
            corpo = getattr(resposta, "text", None)
        except Exception:  # resposta em streaming ainda nao lida
            corpo = None
        if isinstance(corpo, str) and corpo:
            partes.append(corpo[:4000])
    return "\n".join(partes).lower()


def _pelo_texto(texto: str, so: Optional[Tuple[str, ...]] = None) -> Optional[str]:
    for tipo, termos in _REGRAS:
        if so is not None and tipo not in so:
            continue
        if any(_casa(termo, texto) for termo in termos):
            return tipo
    return None


def _pelo_status(status: int, texto: str) -> Optional[str]:
    """O codigo decide; o corpo so refina onde o codigo e ambiguo.

    `None` devolve a decisao ao texto: 400 e 422 sao "o pedido esta errado",
    e so o corpo diz se foi contexto, politica ou outra coisa.
    """
    if status == 413:
        return "request_too_large"
    if status == 402:
        return "credit"
    if status == 429:
        # A OpenAI responde 429 tambem para "insufficient_quota": dinheiro
        # acabado, que nao volta esperando.
        return _pelo_texto(texto, ("credit",)) or "rate_limit"
    if status in (401, 403):
        return _pelo_texto(texto, ("content_policy",)) or "auth"
    if status == 404:
        return "not_found"
    if status == 408:
        return "network"
    if status == 529:  # Anthropic: "overloaded"
        return "rate_limit"
    if 500 <= status <= 599:
        return "transient"
    return None


def classificar(exc: Exception) -> str:
    """Tipo do erro: pelo codigo HTTP quando ha um, pelo texto quando nao.

    O texto sozinho errava onde importa: o 413 da Groq traz
    `rate_limit_exceeded` no corpo, e contexto estourado vem como 400 com a
    explicacao so no corpo.
    """
    texto = _texto(exc)
    status = status_http(exc)
    if status is not None:
        tipo = _pelo_status(status, texto)
        if tipo:
            return tipo
    return _pelo_texto(texto) or "other"


def da_requisicao(tipo: str) -> bool:
    """Se o defeito e do pedido — e portanto nao conta contra o provedor."""
    return tipo in DA_REQUISICAO


def transitorio(tipo: str) -> bool:
    """Se vale esperar e tentar de novo no mesmo provedor."""
    return tipo in TRANSITORIOS


def cooldown_de(tipo: str, repeticoes: int = 1) -> float:
    """Segundos de espera para este tipo de falha."""
    valor = _COOLDOWNS.get(tipo, COOLDOWN_PADRAO["other"])
    if isinstance(valor, tuple):
        return valor[min(max(repeticoes, 1) - 1, len(valor) - 1)]
    return float(valor)


__all__ = [
    "COOLDOWN_PADRAO", "DA_REQUISICAO", "REGRAS_PADRAO", "TRANSITORIOS",
    "classificar", "configurar", "cooldown_de", "da_requisicao", "status_http", "transitorio",
]
