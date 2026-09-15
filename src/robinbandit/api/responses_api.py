"""Compatibilidade entre a OpenAI Responses API e a cadeia do RobinBandit.

O Codex atual usa ``POST /v1/responses`` e espera itens, chamadas de ferramenta
e eventos SSE próprios. Internamente o RobinBandit continua falando a forma
Chat Completions que seus provedores já entendem; este módulo é a fronteira de
tradução entre os dois protocolos.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple


def _texto(conteudo: Any) -> Any:
    """Converte blocos Responses em conteúdo aceito por Chat Completions."""
    if isinstance(conteudo, str):
        return conteudo
    if not isinstance(conteudo, list):
        return ""
    partes: List[Any] = []
    for bloco in conteudo:
        if isinstance(bloco, str):
            partes.append({"type": "text", "text": bloco})
            continue
        if not isinstance(bloco, dict):
            continue
        tipo = bloco.get("type")
        if tipo in {"input_text", "output_text", "text"}:
            partes.append({"type": "text", "text": str(bloco.get("text") or "")})
        elif tipo == "input_image":
            url = bloco.get("image_url") or bloco.get("file_id")
            if url:
                partes.append({
                    "type": "image_url",
                    "image_url": {"url": str(url), "detail": bloco.get("detail", "auto")},
                })
    if not partes:
        return ""
    if all(parte.get("type") == "text" for parte in partes):
        return "\n".join(parte["text"] for parte in partes if parte["text"])
    return partes


def para_mensagens(entrada: Any, instrucoes: Any = None) -> List[Dict[str, Any]]:
    """Responses ``input`` para o histórico enviado aos provedores."""
    mensagens: List[Dict[str, Any]] = []
    instrucao = _texto(instrucoes)
    if instrucao:
        mensagens.append({"role": "system", "content": instrucao})

    if isinstance(entrada, str):
        entrada = [{"type": "message", "role": "user", "content": entrada}]
    elif isinstance(entrada, dict):
        entrada = [entrada]
    if not isinstance(entrada, list):
        return mensagens

    for item in entrada:
        if isinstance(item, str):
            mensagens.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            continue
        tipo = item.get("type") or ("message" if item.get("role") else "")
        if tipo == "message":
            papel = str(item.get("role") or "user")
            if papel == "developer":
                papel = "system"
            conteudo = _texto(item.get("content"))
            if conteudo:
                mensagens.append({"role": papel, "content": conteudo})
        elif tipo in {"function_call", "custom_tool_call"}:
            nome = str(item.get("name") or "").strip()
            if not nome:
                continue
            argumentos = item.get("arguments")
            if tipo == "custom_tool_call":
                argumentos = json.dumps({"input": item.get("input", "")}, ensure_ascii=False)
            elif not isinstance(argumentos, str):
                argumentos = json.dumps(argumentos or {}, ensure_ascii=False)
            mensagens.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": str(item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex}"),
                    "type": "function",
                    "function": {"name": nome, "arguments": argumentos},
                }],
            })
        elif tipo in {"function_call_output", "custom_tool_call_output"}:
            saida = item.get("output", "")
            if not isinstance(saida, str):
                saida = json.dumps(saida, ensure_ascii=False)
            mensagens.append({
                "role": "tool",
                "tool_call_id": str(item.get("call_id") or item.get("id") or ""),
                "content": saida,
            })
    return mensagens


def para_ferramentas(ferramentas: Any) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Declarações Responses para funções no formato Chat Completions."""
    saida: List[Dict[str, Any]] = []
    personalizadas: Set[str] = set()
    for ferramenta in ferramentas if isinstance(ferramentas, list) else []:
        if not isinstance(ferramenta, dict):
            continue
        if isinstance(ferramenta.get("function"), dict):
            saida.append(ferramenta)
            continue
        nome = str(ferramenta.get("name") or "").strip()
        if not nome:
            # Ferramentas hospedadas pela OpenAI não têm equivalente genérico.
            continue
        parametros = ferramenta.get("parameters")
        descricao = str(ferramenta.get("description") or "")
        if ferramenta.get("type") == "custom":
            personalizadas.add(nome)
            formato = ferramenta.get("format") or {}
            pista = "\n".join(str(formato.get(k) or "") for k in ("syntax", "definition"))
            descricao = "\n\n".join(parte for parte in (descricao, pista) if parte)
            parametros = {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Entrada livre"}},
                "required": ["input"],
                "additionalProperties": False,
            }
        if not isinstance(parametros, dict):
            parametros = {"type": "object", "properties": {}}
        elif parametros.get("type") == "object" and "properties" not in parametros:
            parametros = {**parametros, "properties": {}}
        funcao: Dict[str, Any] = {
            "name": nome,
            "description": descricao,
            "parameters": parametros,
        }
        if "strict" in ferramenta:
            funcao["strict"] = ferramenta["strict"]
        saida.append({"type": "function", "function": funcao})
    return saida, personalizadas


def _uso(uso: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(uso, dict):
        return None
    entrada = int(uso.get("entrada") or 0)
    saida = int(uso.get("saida") or 0)
    corpo = {
        "input_tokens": entrada,
        "input_tokens_details": {"cached_tokens": int(uso.get("cacheado") or 0)},
        "output_tokens": saida,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": int(uso.get("total") or 0) or entrada + saida,
    }
    return corpo


def _argumentos_da_personalizada(argumentos: str) -> str:
    try:
        valor = json.loads(argumentos)
        if isinstance(valor, dict) and isinstance(valor.get("input"), str):
            return valor["input"]
    except (TypeError, ValueError):
        pass
    return argumentos


def resposta(
    texto: str,
    modelo: Optional[str] = None,
    uso: Optional[Dict[str, Any]] = None,
    chamadas: Any = None,
    personalizadas: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Monta uma resposta completa, inclusive chamadas de ferramenta."""
    rid = f"resp_{uuid.uuid4().hex}"
    saidas: List[Dict[str, Any]] = []
    if texto:
        saidas.append({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{
                "type": "output_text", "text": texto, "annotations": [], "logprobs": [],
            }],
        })
    nomes_personalizados = personalizadas or set()
    for chamada in chamadas if isinstance(chamadas, list) else []:
        funcao = chamada.get("function") or {}
        nome = str(funcao.get("name") or "")
        call_id = str(chamada.get("id") or f"call_{uuid.uuid4().hex}")
        argumentos = funcao.get("arguments") or "{}"
        if not isinstance(argumentos, str):
            argumentos = json.dumps(argumentos, ensure_ascii=False)
        if nome in nomes_personalizados:
            saidas.append({
                "id": f"ctc_{call_id}", "type": "custom_tool_call", "status": "completed",
                "call_id": call_id, "name": nome,
                "input": _argumentos_da_personalizada(argumentos),
            })
        else:
            saidas.append({
                "id": f"fc_{call_id}", "type": "function_call", "status": "completed",
                "call_id": call_id, "name": nome, "arguments": argumentos,
            })
    corpo: Dict[str, Any] = {
        "id": rid,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "background": False,
        "error": None,
        "incomplete_details": None,
        "model": modelo or "robinbandit",
        "output": saidas,
        "parallel_tool_calls": True,
    }
    medicao = _uso(uso)
    if medicao is not None:
        corpo["usage"] = medicao
    return corpo


def eventos(corpo: Dict[str, Any]) -> Iterator[str]:
    """Emite a resposta já pronta na sequência SSE esperada pelo Codex."""
    sequencia = 0

    def emitir(tipo: str, dados: Dict[str, Any]) -> str:
        nonlocal sequencia
        sequencia += 1
        payload = {"type": tipo, "sequence_number": sequencia, **dados}
        return f"event: {tipo}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    base = {k: v for k, v in corpo.items() if k not in {"output", "usage"}}
    base["status"] = "in_progress"
    base["output"] = []
    yield emitir("response.created", {"response": base})
    yield emitir("response.in_progress", {"response": base})

    for indice, item in enumerate(corpo.get("output") or []):
        vazio = {**item}
        if item["type"] == "message":
            vazio["content"] = []
        elif item["type"] == "function_call":
            vazio["arguments"] = ""
        elif item["type"] == "custom_tool_call":
            vazio["input"] = ""
        vazio["status"] = "in_progress"
        yield emitir("response.output_item.added", {"output_index": indice, "item": vazio})

        if item["type"] == "message":
            conteudo = item["content"][0]
            parte_vazia = {**conteudo, "text": ""}
            yield emitir("response.content_part.added", {
                "item_id": item["id"], "output_index": indice,
                "content_index": 0, "part": parte_vazia,
            })
            yield emitir("response.output_text.delta", {
                "item_id": item["id"], "output_index": indice,
                "content_index": 0, "delta": conteudo["text"], "logprobs": [],
            })
            yield emitir("response.output_text.done", {
                "item_id": item["id"], "output_index": indice,
                "content_index": 0, "text": conteudo["text"], "logprobs": [],
            })
            yield emitir("response.content_part.done", {
                "item_id": item["id"], "output_index": indice,
                "content_index": 0, "part": conteudo,
            })
        elif item["type"] == "function_call":
            yield emitir("response.function_call_arguments.delta", {
                "item_id": item["id"], "output_index": indice,
                "delta": item["arguments"],
            })
            yield emitir("response.function_call_arguments.done", {
                "item_id": item["id"], "output_index": indice,
                "arguments": item["arguments"],
            })
        else:
            yield emitir("response.custom_tool_call_input.delta", {
                "item_id": item["id"], "output_index": indice, "delta": item["input"],
            })
            yield emitir("response.custom_tool_call_input.done", {
                "item_id": item["id"], "output_index": indice, "input": item["input"],
            })
        yield emitir("response.output_item.done", {"output_index": indice, "item": item})

    yield emitir("response.completed", {"response": corpo})


__all__ = ["eventos", "para_ferramentas", "para_mensagens", "resposta"]
