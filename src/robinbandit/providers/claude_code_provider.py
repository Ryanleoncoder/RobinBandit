"""Provedor Claude Code via CLI oficial."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ClaudeCodeError(RuntimeError):
    """Falha do transporte, sem incluir credencial."""


@dataclass(frozen=True)
class ClaudeCodeAuthStatus:
    configured: bool
    source: str
    detail: str = ""


_STATUS_CACHE: Dict[str, tuple] = {}
_STATUS_TTL_SECONDS = 15.0

# Locais comuns do CLI quando ele não está no PATH do servidor.
_LOCAIS_CONHECIDOS = (
    ("~", ".claude", "local"),
    ("~", ".local", "bin"),
    ("~", "AppData", "Roaming", "npm"),
)

_EXTENSOES_VSCODE = (
    ("~", ".vscode", "extensions"),
    ("~", ".vscode-insiders", "extensions"),
    ("~", ".cursor", "extensions"),
)


def _na_extensao_do_editor() -> Optional[str]:
    """`claude.exe` que vem embutido na extensão do editor."""
    for partes in _EXTENSOES_VSCODE:
        raiz = os.path.expanduser(os.path.join(*partes))
        if not os.path.isdir(raiz):
            continue
        try:
            pastas = sorted(os.listdir(raiz), reverse=True)
        except OSError:
            continue
        for pasta in pastas:
            if "claude-code" not in pasta.lower():
                continue
            for nome in ("claude.exe", "claude"):
                caminho = os.path.join(raiz, pasta, "resources", "native-binary", nome)
                if os.path.isfile(caminho):
                    return caminho
    return None


def resolve_claude_binary(binary: str = "claude") -> Optional[str]:
    """Resolve o executável sem invocar shell."""
    candidato = str(binary or "claude").strip() or "claude"
    if os.path.isabs(candidato) and os.path.isfile(candidato):
        return candidato

    achado = shutil.which(candidato)
    if achado:
        return achado

    nomes = (candidato, f"{candidato}.exe", f"{candidato}.cmd")
    for partes in _LOCAIS_CONHECIDOS:
        pasta = os.path.expanduser(os.path.join(*partes))
        for nome in nomes:
            caminho = os.path.join(pasta, nome)
            if os.path.isfile(caminho):
                return caminho
    return _na_extensao_do_editor()


def claude_code_auth_status(binary: str = "claude", *, timeout: float = 8.0) -> ClaudeCodeAuthStatus:
    """Se o CLI existe e responde. Nunca abre o arquivo de credencial."""
    executavel = resolve_claude_binary(binary)
    if not executavel:
        return ClaudeCodeAuthStatus(False, "claude_cli", "Claude Code CLI não instalado")

    agora = time.monotonic()
    guardado = _STATUS_CACHE.get(executavel)
    if guardado and agora - guardado[0] < _STATUS_TTL_SECONDS:
        return guardado[1]

    try:
        resultado = subprocess.run(
            [executavel, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, float(timeout)),
            check=False,
            shell=False,
        )
        versao = (resultado.stdout or "").strip().splitlines()[:1]
        status = ClaudeCodeAuthStatus(
            resultado.returncode == 0,
            "claude_cli",
            versao[0] if versao else "",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        status = ClaudeCodeAuthStatus(False, "claude_cli", f"{type(exc).__name__}")

    _STATUS_CACHE[executavel] = (agora, status)
    return status


def _texto_das_mensagens(messages: List[Dict[str, Any]]) -> tuple:
    """Separa instruções e junta o diálogo num prompt único."""
    sistema: List[str] = []
    dialogo: List[str] = []
    for mensagem in messages or []:
        papel = str(mensagem.get("role") or "user").lower()
        conteudo = str(mensagem.get("content") or "").strip()
        if not conteudo:
            continue
        if papel == "system":
            sistema.append(conteudo)
        elif papel == "assistant":
            dialogo.append(f"Assistente: {conteudo}")
        else:
            dialogo.append(f"Usuário: {conteudo}")
    return "\n\n".join(sistema), "\n\n".join(dialogo)


class ClaudeCodeProvider:
    """Fala com o modelo da assinatura pelo CLI, em modo não-interativo."""

    def __init__(
        self,
        *,
        name: str = "claude_code",
        binary: str = "claude",
        models: Optional[List[str]] = None,
        timeout: float = 300.0,
        cwd: str = "",
    ):
        self.name = name
        self.binary = binary
        self.models = list(models or [])
        self.timeout = max(10.0, float(timeout))
        self.cwd = cwd or os.getcwd()
        self.last_usage: Dict[str, Any] = {}

    @property
    def configured(self) -> bool:
        return claude_code_auth_status(self.binary).configured

    def _comando(self, prompt: str, sistema: str, modelo: str) -> List[str]:
        executavel = resolve_claude_binary(self.binary)
        if not executavel:
            raise ClaudeCodeError("Claude Code CLI não encontrado")
        comando = [executavel, "-p", prompt, "--output-format", "json"]
        if sistema:
            comando += ["--append-system-prompt", sistema]
        if modelo:
            comando += ["--model", modelo]
        # Sem ferramentas: quem orquestra é o agente hospedeiro. Deixar o CLI
        # usar as dele faria dois loops disputando o mesmo turno.
        comando += ["--allowed-tools", ""]
        return comando

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str = "",
        **_ignorado: Any,
    ) -> str:
        import asyncio

        sistema, prompt = _texto_das_mensagens(messages)
        if not prompt:
            raise ClaudeCodeError("nada para perguntar")

        escolhido = str(model or "").strip() or (self.models[0] if self.models else "")
        comando = self._comando(prompt, sistema, escolhido)

        def _rodar() -> subprocess.CompletedProcess:
            return subprocess.run(
                comando,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                shell=False,
                cwd=self.cwd,
            )

        try:
            resultado = await asyncio.get_running_loop().run_in_executor(None, _rodar)
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCodeError(f"Claude Code passou de {self.timeout:.0f}s") from exc
        except OSError as exc:
            raise ClaudeCodeError(f"{type(exc).__name__} ao chamar o Claude Code") from exc

        saida = (resultado.stdout or "").strip()
        if not saida:
            # O stderr traz aviso de workspace não confiado junto do erro real;
            # a última linha costuma ser o que importa.
            motivo = (resultado.stderr or "").strip().splitlines()[-1:] or ["sem saída"]
            raise ClaudeCodeError(motivo[0][:300])

        try:
            # O CLI imprime avisos antes do JSON: o objeto começa na primeira `{`.
            dados = json.loads(saida[saida.index("{"):])
        except (ValueError, json.JSONDecodeError) as exc:
            raise ClaudeCodeError("resposta do Claude Code não é JSON") from exc

        if dados.get("is_error"):
            raise ClaudeCodeError(str(dados.get("result") or "erro sem descrição")[:300])

        uso = dados.get("usage") or {}
        self.last_usage = {
            "entrada": int(uso.get("input_tokens") or 0),
            "saida": int(uso.get("output_tokens") or 0),
            "cacheado": int(uso.get("cache_read_input_tokens") or 0),
            "custo_usd": dados.get("total_cost_usd"),
        }
        return str(dados.get("result") or "")


__all__ = [
    "ClaudeCodeAuthStatus",
    "ClaudeCodeError",
    "ClaudeCodeProvider",
    "claude_code_auth_status",
    "resolve_claude_binary",
]
