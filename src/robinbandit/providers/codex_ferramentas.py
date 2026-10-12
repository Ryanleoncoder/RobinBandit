"""Ferramentas do hospedeiro têm nomes separados das ferramentas internas do CLI."""
import hashlib
import json
import re


class FerramentaEscolhida(Exception):
    def __init__(self, params):
        self.params = params


def nome_no_cli(nome):
    alias = "rb_" + nome
    return alias if len(alias) <= 64 else alias[:47] + "_" + hashlib.sha256(nome.encode()).hexdigest()[:16]


def declarar(ferramentas):
    declaradas, nomes = [], {}
    for ferramenta in ferramentas or []:
        funcao = ferramenta.get("function") or {}
        nome = str(funcao.get("name") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nome):
            raise ValueError("nome de ferramenta inválido")
        alias = nome_no_cli(nome)
        if alias in nomes:
            raise ValueError("ferramenta declarada duas vezes")
        nomes[alias] = nome
        declaradas.append({"type": "function", "name": alias,
            "description": str(funcao.get("description") or ""),
            "inputSchema": funcao.get("parameters") or {"type": "object", "properties": {}}})
    return declaradas, nomes


def capturar(params, nomes, thread_id):
    if params.get("threadId") != thread_id or params.get("tool") not in nomes:
        return None
    ident = params.get("callId")
    if not isinstance(ident, str) or not ident:
        raise ValueError("chamada de ferramenta sem identificador")
    argumentos = params.get("arguments")
    if isinstance(argumentos, str):
        argumentos = json.loads(argumentos)
    if not isinstance(argumentos, dict):
        raise ValueError("argumentos de ferramenta precisam ser um objeto")
    return {"id": ident, "type": "function", "function": {
        "name": nomes[params["tool"]], "arguments": json.dumps(argumentos, ensure_ascii=False)}}
