"""Configuração pronta para as ferramentas de CLI apontarem para o RobinBandit.

Qualquer cliente que aceite trocar a `base_url` passa a rotear pelo bandit. O
trabalho chato é lembrar onde cada um guarda isso e com que nome de campo —
Claude Code usa variável de ambiente, Codex usa TOML, Cline usa JSON do VS Code.

Aqui a resposta já sai no formato de cada um, com o caminho do arquivo. Nada é
escrito no disco: quem decide alterar a própria configuração é a pessoa.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

# `model` vira o contexto do bandit, não o nome de um modelo: é o único campo
# que todo cliente OpenAI manda, e dá para separar células de aprendizado sem
# modificar o cliente.
_CONTEXTO_PADRAO = "codigo"


def _base(url: str) -> str:
    return str(url or "http://localhost:8000").rstrip("/")


def claude_code(url: str, chave: str = "robinbandit") -> Dict[str, Any]:
    """Claude Code lê a base pelo ambiente; não tem arquivo de provedor."""
    base = _base(url)
    return {
        "id": "claude-code",
        "label": "Claude Code",
        "formato": "env",
        "arquivo": "",
        "conteudo": (
            f"ANTHROPIC_BASE_URL={base}\n"
            f"ANTHROPIC_AUTH_TOKEN={chave}\n"
            f"ANTHROPIC_MODEL={_CONTEXTO_PADRAO}\n"
        ),
        "como": (
            "Exporte as três variáveis antes de abrir o `claude`. "
            "Para voltar ao normal, abra um terminal novo."
        ),
    }


def codex(url: str, chave: str = "robinbandit") -> Dict[str, Any]:
    base = _base(url)
    return {
        "id": "codex",
        "label": "Codex CLI",
        "formato": "toml",
        "arquivo": "~/.codex/config.toml",
        "conteudo": (
            'model_provider = "robinbandit"\n'
            f'model = "{_CONTEXTO_PADRAO}"\n\n'
            "[model_providers.robinbandit]\n"
            'name = "RobinBandit"\n'
            f'base_url = "{base}/v1"\n'
            'wire_api = "responses"\n'
            'env_key = "ROBINBANDIT_API_KEY"\n'
            'requires_openai_auth = false\n'
        ),
        "como": f"Some ao `~/.codex/config.toml` e exporte ROBINBANDIT_API_KEY={chave}.",
    }


def cline(url: str, chave: str = "robinbandit") -> Dict[str, Any]:
    base = _base(url)
    return {
        "id": "cline",
        "label": "Cline (VS Code)",
        "formato": "json",
        "arquivo": "Settings do VS Code",
        "conteudo": json.dumps({
            "cline.apiProvider": "openai",
            "cline.openAiBaseUrl": f"{base}/v1",
            "cline.openAiApiKey": chave,
            "cline.openAiModelId": _CONTEXTO_PADRAO,
        }, indent=2, ensure_ascii=False),
        "como": "Cole no settings.json do VS Code.",
    }


def opencode(url: str, chave: str = "robinbandit") -> Dict[str, Any]:
    base = _base(url)
    return {
        "id": "opencode",
        "label": "OpenCode",
        "formato": "json",
        "arquivo": "~/.config/opencode/opencode.json",
        "conteudo": json.dumps({
            "provider": {
                "robinbandit": {
                    "npm": "@ai-sdk/openai-compatible",
                    "options": {"baseURL": f"{base}/v1", "apiKey": chave},
                    "models": {_CONTEXTO_PADRAO: {"name": "RobinBandit"}},
                }
            }
        }, indent=2, ensure_ascii=False),
        "como": "Grave em `~/.config/opencode/opencode.json`.",
    }


def openai_sdk(url: str, chave: str = "robinbandit") -> Dict[str, Any]:
    base = _base(url)
    return {
        "id": "openai-sdk",
        "label": "SDK OpenAI (qualquer linguagem)",
        "formato": "python",
        "arquivo": "",
        "conteudo": (
            "from openai import OpenAI\n\n"
            f'cliente = OpenAI(base_url="{base}/v1", api_key="{chave}")\n'
            "resposta = cliente.chat.completions.create(\n"
            f'    model="{_CONTEXTO_PADRAO}",  # vira o contexto do bandit\n'
            '    messages=[{"role": "user", "content": "oi"}],\n'
            ")\n"
        ),
        "como": "O campo `model` escolhe a célula de aprendizado, não o modelo.",
    }


def curl(url: str, chave: str = "robinbandit") -> Dict[str, Any]:
    base = _base(url)
    return {
        "id": "curl",
        "label": "curl",
        "formato": "shell",
        "arquivo": "",
        "conteudo": (
            f"curl {base}/v1/chat/completions \\\n"
            f'  -H "Authorization: Bearer {chave}" \\\n'
            '  -H "Content-Type: application/json" \\\n'
            f'  -d \'{{"model":"{_CONTEXTO_PADRAO}",'
            '"messages":[{"role":"user","content":"oi"}]}\'\n'
        ),
        "como": "Para conferir que o endpoint responde.",
    }


_FERRAMENTAS = (claude_code, codex, cline, opencode, openai_sdk, curl)


def todas(url: str, chave: str = "robinbandit") -> List[Dict[str, Any]]:
    return [montar(url, chave) for montar in _FERRAMENTAS]


def uma(nome: str, url: str, chave: str = "robinbandit") -> Dict[str, Any]:
    alvo = str(nome or "").strip().lower()
    for montar in _FERRAMENTAS:
        config = montar(url, chave)
        if config["id"] == alvo:
            return config
    raise KeyError(nome)


__all__ = ["todas", "uma"]
