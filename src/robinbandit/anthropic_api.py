"""Fala o protocolo da Anthropic, para o Claude Code apontar para cá.

O painel entregava `ANTHROPIC_BASE_URL` e a configuração não funcionava: o
Claude Code não fala o formato da OpenAI, ele chama `POST /v1/messages` com o
formato da Anthropic. Sem esta tradução, a única resposta que ele recebia era
404 — a aba Conectar prometia uma coisa que nunca aconteceu.

As diferenças que importam, medidas no que o `claude` realmente envia:

* `system` é campo separado, e vem como **lista de blocos**, não string;
* `content` de cada mensagem também é lista de blocos (`{"type": "text", ...}`);
* `max_tokens` é obrigatório lá, e aqui não significa nada — o Robin não conta
  token, quem corta é o provedor de destino;
* a resposta devolve `content` em blocos, com `stop_reason` e `usage`.

O que não é texto — `tools`, `thinking`, `output_config` — é ignorado de
propósito: aqui o RobinBandit é provedor de modelo, e o laço de ferramentas
continua sendo do agente que hospeda. Aceitar `tools` sem executá-las seria
prometer de novo o que não se cumpre.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Union

# O que o cliente manda em `content` e em `system`: ou uma string, ou uma lista
# de blocos. As duas formas são válidas na API da Anthropic, e o Claude Code
# usa a segunda.
Blocos = Union[str, List[Dict[str, Any]], None]


def texto_de(valor: Blocos) -> str:
    """Achata blocos em texto puro.

    Blocos que não são texto (imagem, uso de ferramenta, resultado de
    ferramenta) são descartados: não há como mandá-los adiante para um provedor
    que só aceita texto, e inventar uma transcrição seria pior que omitir.
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    partes = []
    for bloco in valor:
        if isinstance(bloco, str):
            partes.append(bloco)
        elif isinstance(bloco, dict) and bloco.get("type") == "text":
            partes.append(str(bloco.get("text") or ""))
    return "\n".join(p for p in partes if p)


def para_mensagens(
    messages: List[Dict[str, Any]],
    system: Blocos = None,
) -> List[Dict[str, str]]:
    """Formato Anthropic -> a lista simples que os provedores do Robin aceitam.

    O `system` da Anthropic é um campo à parte; aqui ele vira a primeira
    mensagem, que é como todo provedor OpenAI-compatible espera receber.
    """
    saida: List[Dict[str, str]] = []

    instrucao = texto_de(system)
    if instrucao:
        saida.append({"role": "system", "content": instrucao})

    for m in messages or []:
        conteudo = texto_de(m.get("content"))
        if not conteudo:
            # Turno só com ferramenta ou imagem: sem texto, não há o que rotear.
            continue
        papel = m.get("role") or "user"
        saida.append({"role": papel, "content": conteudo})

    return saida


def resposta(texto: str, modelo: Optional[str] = None,
             uso: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A resposta no formato que o cliente Anthropic espera.

    O campo não é opcional: o SDK da Anthropic lê `usage.input_tokens`
    diretamente. Quando o provedor não informa, mantemos zeros; quando informa,
    devolvemos a contagem real que também abastece o painel.
    """
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": modelo or "robinbandit",
        "content": [{"type": "text", "text": texto}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": int((uso or {}).get("entrada") or 0),
            "output_tokens": int((uso or {}).get("saida") or 0),
        },
        "created": int(time.time()),
    }


def eventos(corpo: Dict[str, Any]) -> Iterator[str]:
    """A resposta pronta, vestida de SSE.

    O Claude Code pede `stream: true` e sabe ler só esse formato. Não há
    streaming de verdade aqui: o texto já está completo quando esta função
    começa, e sai num `content_block_delta` único. Streaming real exigiria que
    todos os provedores entregassem token a token, e o `complete()` do Robin
    devolve a resposta inteira de uma vez.

    A sequência de eventos é a que o SDK espera; faltar um deles trava o
    cliente esperando o resto.
    """
    import json

    texto = ""
    if corpo.get("content"):
        texto = str(corpo["content"][0].get("text") or "")

    abertura = {k: v for k, v in corpo.items() if k != "content"}
    abertura["content"] = []

    def evento(nome: str, dados: Dict[str, Any]) -> str:
        return f"event: {nome}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n"

    yield evento("message_start", {"type": "message_start", "message": abertura})
    yield evento("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    yield evento("content_block_delta", {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": texto},
    })
    yield evento("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield evento("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": corpo.get("usage", {"output_tokens": 0}),
    })
    yield evento("message_stop", {"type": "message_stop"})


def erro(mensagem: str, tipo: str = "api_error") -> Dict[str, Any]:
    """O envelope de erro da Anthropic.

    Devolver o erro do jeito que o cliente entende faz ele mostrar a mensagem
    real em vez de "unknown error" — e a mensagem real é o que diz qual
    provedor caiu.
    """
    return {"type": "error", "error": {"type": tipo, "message": mensagem}}


__all__ = ["Blocos", "erro", "eventos", "para_mensagens", "resposta", "texto_de"]
