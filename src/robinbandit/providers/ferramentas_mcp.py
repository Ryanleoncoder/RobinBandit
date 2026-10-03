"""Servidor MCP que só declara as ferramentas do Sentury para o Claude Code.

O CLI não aceita definição de ferramenta de fora, mas aceita servidor MCP. Com
as ferramentas declaradas aqui, o modelo emite `tool_use` estruturado em vez de
escrever a chamada em JSON no texto. Nada é executado: quem executa é o
Sentury, que lê o `tool_use` do stream do CLI (rodado com `--max-turns 1`). Se
o CLI tentar executar mesmo assim, a resposta é erro.

Uso: python ferramentas_mcp.py <arquivo com a lista de ferramentas em JSON>
Protocolo: JSON-RPC 2.0, uma mensagem por linha no stdin/stdout.
"""
from __future__ import annotations

import json
import sys


def _ferramentas(caminho: str) -> list:
    with open(caminho, encoding="utf-8") as arquivo:
        return [{"name": f["name"], "description": f.get("description", ""),
                 "inputSchema": f.get("parameters") or {"type": "object", "properties": {}}}
                for f in json.load(arquivo)]


def _responder(pedido: dict, ferramentas: list) -> dict | None:
    metodo, ident = pedido.get("method"), pedido.get("id")
    if ident is None:  # notificação: não tem resposta
        return None
    if metodo == "initialize":
        resultado = {"protocolVersion": (pedido.get("params") or {}).get("protocolVersion", "2024-11-05"),
                     "capabilities": {"tools": {}}, "serverInfo": {"name": "sentury", "version": "1"}}
    elif metodo == "tools/list":
        resultado = {"tools": ferramentas}
    elif metodo == "tools/call":
        resultado = {"isError": True, "content": [{"type": "text", "text": "quem executa é o Sentury"}]}
    elif metodo == "ping":
        resultado = {}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"método {metodo}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": resultado}


def main() -> None:
    ferramentas = _ferramentas(sys.argv[1])
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            resposta = _responder(json.loads(linha), ferramentas)
        except ValueError:
            continue
        if resposta is not None:
            sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
