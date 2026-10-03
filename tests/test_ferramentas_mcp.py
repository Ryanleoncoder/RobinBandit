"""Claude Code com ferramentas nativas: o servidor MCP só declara, o stream traz o tool_use."""
import json
import subprocess
import sys
from pathlib import Path

from robinbandit.providers import claude_code_provider as ccp
from robinbandit.providers import ferramentas_mcp

BROWSER = {"type": "function", "function": {"name": "browser", "description": "Opera uma página.",
                                            "parameters": {"type": "object", "properties": {"acao": {"type": "string"}}}}}


def test_o_servidor_declara_e_nao_executa(tmp_path):
    arquivo = tmp_path / "ferramentas.json"
    arquivo.write_text(json.dumps(ccp._especificacoes([BROWSER])), encoding="utf-8")
    pedidos = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
               {"jsonrpc": "2.0", "method": "notifications/initialized"},
               {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
               {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "browser", "arguments": {}}}]
    saida = subprocess.run([sys.executable, ferramentas_mcp.__file__, str(arquivo)],
                           input="\n".join(json.dumps(p) for p in pedidos) + "\n",
                           capture_output=True, text=True, encoding="utf-8", timeout=30).stdout
    respostas = {r["id"]: r for r in map(json.loads, saida.splitlines())}
    assert set(respostas) == {1, 2, 3}, "notificação não tem resposta"
    assert respostas[1]["result"]["protocolVersion"] == "2025-06-18"
    (ferramenta,) = respostas[2]["result"]["tools"]
    assert ferramenta["name"] == "browser" and ferramenta["inputSchema"]["properties"] == {"acao": {"type": "string"}}
    assert respostas[3]["result"]["isError"], "quem executa é o Sentury"


def test_o_comando_leva_o_mcp_e_um_passo_so(tmp_path):
    p = ccp.ClaudeCodeProvider(name="claude_code")
    config = ccp._config_do_mcp(str(tmp_path), [BROWSER])
    comando = p._comando("", "claude-haiku-4-5", config_do_mcp=config)
    assert comando[comando.index("--mcp-config") + 1] == config and comando[comando.index("--max-turns") + 1] == "1"
    servidor = json.loads(Path(config).read_text(encoding="utf-8"))["mcpServers"]["sentury"]
    assert servidor["args"][0].endswith("ferramentas_mcp.py")
    assert "--mcp-config" not in p._comando("", "claude-haiku-4-5")


def test_o_stream_traz_o_tool_use_e_o_fim_por_max_turns_nao_e_erro():
    linhas = [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Vou abrir a página."},
            {"type": "tool_use", "id": "toolu_1", "name": "mcp__sentury__browser", "input": {"acao": "navegar"}}]}},
        {"type": "result", "subtype": "error_max_turns", "is_error": True, "usage": {"output_tokens": 150}},
    ]
    lido = ccp._ler_stream("\n".join(json.dumps(l) for l in linhas))
    assert lido["erro"] is None and lido["texto"] == "Vou abrir a página."
    assert lido["chamadas"] == [{"id": "toolu_1", "nome": "mcp__sentury__browser", "argumentos": {"acao": "navegar"}}]


def test_max_turns_sem_tool_use_continua_erro():
    lido = ccp._ler_stream(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True,
                                       "result": "limite"}))
    assert lido["erro"] == "limite"
