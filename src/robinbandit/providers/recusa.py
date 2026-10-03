"""A recusa do modelo por política de conteúdo, quando ela chega como resposta.

Alguns provedores recusam com HTTP 200: a resposta vem "certa", com um sinal
de recusa (`stop_reason="refusal"`, `finish_reason="content_filter"`,
`message.refusal`, `finishReason="SAFETY"`). Lida como resposta, o texto da
recusa viraria a resposta final. Como erro, a cadeia faz o que já faz com o
erro de moderação: passa ao próximo provedor, que pode aceitar, sem castigar
este.

A mensagem começa com `content_filter` para a classificação por texto dar
`content_policy`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class RecusaDoModelo(RuntimeError):
    def __init__(self, modelo: str, explicacao: str = "") -> None:
        self.modelo = modelo
        self.explicacao = str(explicacao or "").strip()[:500]
        detalhe = f": {self.explicacao}" if self.explicacao else ""
        super().__init__(f"content_filter: o modelo {modelo} recusou responder{detalhe}")


# Motivos do Gemini que são recusa de conteúdo. `RECITATION` e `MAX_TOKENS`
# ficam de fora: não são política.
_GEMINI_RECUSA = frozenset({"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"})


def recusa_openai(escolha: Dict[str, Any]) -> Optional[str]:
    """A explicação da recusa numa `choice` do formato OpenAI, ou None."""
    mensagem = escolha.get("message") or {}
    if mensagem.get("refusal"):
        return str(mensagem["refusal"])
    if escolha.get("finish_reason") == "content_filter":
        return str(mensagem.get("content") or "")
    return None


def recusa_anthropic(data: Dict[str, Any], texto: str = "") -> Optional[str]:
    if data.get("stop_reason") == "refusal":
        return texto
    return None


def recusa_gemini(data: Dict[str, Any]) -> Optional[str]:
    bloqueio = (data.get("promptFeedback") or {}).get("blockReason")
    if bloqueio:
        return f"pedido bloqueado ({bloqueio})"
    candidato = ((data.get("candidates") or [{}])[0] or {})
    motivo = candidato.get("finishReason")
    if motivo in _GEMINI_RECUSA:
        return f"resposta bloqueada ({motivo})"
    return None
