"""Provedor ChatGPT Codex via ``codex app-server`` oficial."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# A restrição é sobre executar dentro do CLI, não sobre descrever uma ação
# para o harness hospedeiro. A proibição genérica fazia o modelo negar até
# `ler_arquivo` em JSON, embora o Sentury fosse quem executaria a leitura.
_PROVIDER_GUARD = (
    "Você está operando como provedor de modelo do RobinBandit, não como agente do Codex. "
    "Não execute ferramentas locais do Codex, comandos, plugins, MCP, navegação ou alterações de arquivos. "
    "As ferramentas descritas nas instruções da conversa pertencem ao harness hospedeiro: "
    "você pode selecionar essas ferramentas e emitir o JSON de ação pedido; quem executa e "
    "autoriza é o hospedeiro, fora deste CLI. Emitir esse JSON não é executar uma ferramenta local. "
    "Siga o formato de saída das instruções da conversa, independentemente do idioma do pedido. "
    "Não negue acesso a uma capacidade do hospedeiro apenas porque o CLI não a executa. "
    "Se nenhuma ferramenta for necessária, siga o contrato de resposta da conversa. "
    "Nunca afirme ter executado uma ação sem resultado fornecido pelo hospedeiro."
)


class CodexAppServerError(RuntimeError):
    """Falha segura do transporte Codex, sem incluir credenciais."""


@dataclass(frozen=True)
class CodexAuthStatus:
    configured: bool
    source: str
    detail: str = ""


_STATUS_CACHE: Dict[str, tuple[float, CodexAuthStatus]] = {}

# Qual modelo respondeu por ultimo, por (provedor, lista de modelos escolhida).
#
# Fica no MODULO e nao na instancia porque `build_tier_provider` resolve por
# request — e o que faz trocar a conta no painel valer sem reiniciar. Guardado
# na instancia, o grude nascia vazio a cada chamada e o modelo morto era
# tentado de novo, que e exatamente o desperdicio que ele existe para evitar.
#
# A lista de modelos entra na chave de proposito: trocar a selecao no painel
# muda a chave e solta o grude na hora, sem estado velho mandando.
_GRUDADO: Dict[tuple, str] = {}
# Features que ESTE Codex nao conhece. Aprendido em execucao: a lista de
# features muda de versao pra versao, e uma flag desconhecida e fatal.
_FEATURES_RECUSADAS: set[str] = set()
_PADRAO_FEATURE_RECUSADA = re.compile(r"Unknown feature flag:\s*([A-Za-z0-9_.-]+)")
_STATUS_TTL_SECONDS = 15.0

# Teto de uma chamada. Nao pode passar do orcamento do turno (120s em
# `LoopBudget.max_elapsed_ms`): um provedor que desiste depois de o turno ja
# estar morto garante queimar o orcamento inteiro e devolver um erro generico
# quando nao ha mais nada a fazer. Medido: uma rodada no Dedicado levou 300,3s
# esperando o proprio timeout, para uma chamada que isolada leva 14,6s.
_TETO_DA_CHAMADA_S = 110.0

# Acima disto a chamada ganha aviso no log. Uma chamada lenta e uma travada sao
# indistinguiveis ate o timeout estourar, e a diferenca importa: uma pede
# paciencia, a outra pede investigacao.
_AVISO_DE_LENTIDAO_S = 60.0


# Locais comuns do CLI quando ele não está no PATH do servidor.
_LOCAIS_CONHECIDOS = (
    ("~", ".codex", "bin"),
    ("~", ".codex", ".sandbox-bin"),
    ("~", ".codex", "plugins", ".plugin-appserver"),
)


def resolve_codex_binary(binary: str = "codex") -> Optional[str]:
    """Resolve o executável configurado sem invocar shell."""
    candidate = str(binary or "codex").strip() or "codex"
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate
    achado = shutil.which(candidate)
    if achado:
        return achado
    nomes = (candidate, f"{candidate}.exe", f"{candidate}.cmd")
    for partes in _LOCAIS_CONHECIDOS:
        pasta = os.path.expanduser(os.path.join(*partes))
        for nome in nomes:
            caminho = os.path.join(pasta, nome)
            if os.path.isfile(caminho):
                return caminho
    return None


def codex_auth_status(binary: str = "codex", *, timeout: float = 5.0) -> CodexAuthStatus:
    """Consulta apenas o status público do CLI; nunca abre ``auth.json``."""
    executable = resolve_codex_binary(binary)
    if not executable:
        return CodexAuthStatus(False, "codex_cli", "Codex CLI não instalado")

    now = time.monotonic()
    cached = _STATUS_CACHE.get(executable)
    if cached and now - cached[0] < _STATUS_TTL_SECONDS:
        return cached[1]
    try:
        result = subprocess.run(
            [executable, "login", "status"],
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
        # O contrato estável para automação é o exit code.
        configured = result.returncode == 0
        detail = "autenticado" if configured else "execute: codex login"
        status = CodexAuthStatus(configured, "codex_cli", detail)
    except (OSError, subprocess.SubprocessError):
        status = CodexAuthStatus(False, "codex_cli", "não foi possível consultar o login")
    _STATUS_CACHE[executable] = (now, status)
    return status


_NOME_DE_SERVIDOR = re.compile(r"^[A-Za-z0-9_-]+$")


def _servidores_mcp_do_usuario() -> List[str]:
    """Os servidores MCP da config do Codex da pessoa.

    O app-server carrega essa config, e o modelo tentava usar o `node_repl` do
    app desktop em vez de devolver o plano ao hospedeiro. `-c mcp_servers={}`
    não esvazia a tabela (as configs se juntam), então cada um é desligado pelo nome.
    """
    import tomllib

    casa = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    try:
        with open(os.path.join(casa, "config.toml"), "rb") as arquivo:
            servidores = tomllib.load(arquivo).get("mcp_servers") or {}
    except (OSError, ValueError):
        return []
    return sorted(nome for nome in servidores if _NOME_DE_SERVIDOR.match(str(nome)))


def _feature_recusada(stderr: str) -> Optional[str]:
    """O nome da feature que este Codex nao conhece, se foi por isso que caiu."""
    achado = _PADRAO_FEATURE_RECUSADA.search(stderr or "")
    return achado.group(1) if achado else None


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: List[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            text = part.get("text") or part.get("content")
            if text is not None:
                parts.append(str(text))
    return "\n".join(value for value in parts if value)


def _split_messages(messages: Iterable[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]], str]:
    """Separa instruções, histórico injetável e a entrada do turno."""
    instructions: List[str] = []
    conversational: List[Dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        content = _text_content(message.get("content"))
        if role in {"system", "developer"}:
            if content.strip():
                instructions.append(content.strip())
            continue
        conversational.append({**message, "role": role, "content": content})

    turn_text = "Continue."
    history = conversational
    if conversational and conversational[-1]["role"] == "user":
        turn_text = str(conversational[-1].get("content") or "Continue.")
        history = conversational[:-1]
    return "\n\n".join(instructions), history, turn_text


def _history_items(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Converte histórico Chat Completions para itens aceitos por app-server."""
    items: List[Dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "").lower()
        content = str(message.get("content") or "")
        if role == "user":
            items.append({
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": content}],
            })
        elif role == "assistant":
            items.append({
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": content}],
            })
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                name = str(function.get("name") or "").strip()
                call_id = str(call.get("id") or "").strip()
                if name and call_id:
                    arguments = function.get("arguments") or "{}"
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    items.append({
                        "type": "function_call", "call_id": call_id,
                        "name": name, "arguments": arguments,
                    })
        elif role == "tool":
            call_id = str(message.get("tool_call_id") or "").strip()
            if call_id:
                items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": content,
                })
    return items


class CodexAppServerClient:
    """Cliente JSONL mínimo do protocolo estável do app-server."""

    # Tudo que faz o Codex executar algo por conta própria. Quem executa é o
    # hospedeiro. `code_mode_host` (ligado no 0.159) tenta abrir um executável
    # à parte e, sem ele, o turno morre antes de chegar à ferramenta do Sentury.
    _DISABLED_FEATURES = (
        "apps", "browser_use", "browser_use_external", "code_mode_host", "computer_use",
        "image_generation", "multi_agent", "plugins", "shell_tool", "skill_search",
        "sleep_tool", "tool_suggest", "unified_exec", "view_image",
    )

    def __init__(self, binary: str = "codex", timeout: float = _TETO_DA_CHAMADA_S):
        self.binary = str(binary or "codex")
        self.timeout = min(max(5.0, float(timeout)), _TETO_DA_CHAMADA_S)
        self._next_id = 1

    def _command(self, executable: str) -> List[str]:
        """Comando isolado do Codex usado como provedor de saída."""
        # Evita recursão quando o mesmo Codex também usa RobinBandit como cliente.
        command = [
            executable, "app-server", "--listen", "stdio://",
            "-c", 'model_provider="openai"',
        ]
        for feature in self._DISABLED_FEATURES:
            if feature in _FEATURES_RECUSADAS:
                continue
            command.extend(["--disable", feature])
        for servidor in _servidores_mcp_do_usuario():
            command.extend(["-c", f"mcp_servers.{servidor}.enabled=false"])
        return command

    async def _send(self, process: asyncio.subprocess.Process, message: Dict[str, Any]) -> None:
        if process.stdin is None:
            raise CodexAppServerError("codex app-server encerrou a entrada")
        process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def _request(
        self,
        process: asyncio.subprocess.Process,
        method: str,
        params: Dict[str, Any],
        *,
        on_notification=None,
    ) -> Dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        await self._send(process, {"method": method, "id": request_id, "params": params})
        if process.stdout is None:
            raise CodexAppServerError("codex app-server não abriu a saída")
        while True:
            raw = await process.stdout.readline()
            if not raw:
                raise CodexAppServerError("codex app-server encerrou inesperadamente")
            try:
                message = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            # JSON-RPC bidirecional tem espaços de IDs independentes.
            if "method" in message and "id" in message:
                await self._decline_server_request(process, message)
                continue
            if message.get("id") == request_id:
                if message.get("error"):
                    error = message["error"]
                    detail = error.get("message") if isinstance(error, dict) else str(error)
                    raise CodexAppServerError(f"{method}: {detail}")
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            if on_notification is not None and "method" in message:
                on_notification(message)

    async def _decline_server_request(
        self, process: asyncio.subprocess.Process, request: Dict[str, Any]
    ) -> None:
        method = str(request.get("method") or "")
        if "approval" in method.lower() or "permissions" in method.lower():
            result: Dict[str, Any] = {"decision": "decline"}
            await self._send(process, {"id": request.get("id"), "result": result})
        else:
            await self._send(process, {
                "id": request.get("id"),
                "error": {"code": -32601, "message": "método não disponível no modo provedor"},
            })


    async def complete(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        reasoning_effort: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        executable = resolve_codex_binary(self.binary)
        if not executable:
            raise CodexAppServerError("Codex CLI não instalado")
        # Uma flag que este Codex nao conhece derruba o processo antes do
        # primeiro byte. Em vez de fixar a lista certa — que envelhece a cada
        # versao do CLI —, tira a recusada e tenta de novo.
        for _ in range(len(self._DISABLED_FEATURES) + 1):
            try:
                return await self._tentar(executable, messages, model, reasoning_effort)
            except CodexAppServerError as exc:
                recusada = _feature_recusada(getattr(exc, "stderr", "") or "")
                if not recusada or recusada in _FEATURES_RECUSADAS:
                    raise
                _FEATURES_RECUSADAS.add(recusada)
                logger.warning(
                    "codex app-server nao conhece a feature '%s'; seguindo sem desabilita-la",
                    recusada,
                )
        raise CodexAppServerError("codex app-server recusou as flags de feature")

    async def _tentar(
        self,
        executable: str,
        messages: List[Dict[str, Any]],
        model: str,
        reasoning_effort: Optional[str],
    ) -> tuple[str, Optional[str]]:
        command = self._command(executable)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.create_task(process.stderr.read()) if process.stderr else None
        # Guardado pra que o `finally` possa anexar o stderr ao erro que sobe:
        # e no stderr que o Codex diz qual flag ele nao conhece.
        erro: Optional[CodexAppServerError] = None
        try:
            return await asyncio.wait_for(
                self._drive(process, messages, model, reasoning_effort),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            erro = CodexAppServerError(
                f"Codex não concluiu em {self.timeout:g}s"
            )
            raise erro from exc
        except CodexAppServerError as exc:
            erro = exc
            raise
        finally:
            if process.stdin:
                process.stdin.close()
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
            if stderr_task:
                bruto = await stderr_task
                stderr = bruto.decode("utf-8", errors="replace") if bruto else ""
                if stderr and process.returncode not in {0, None}:
                    # Era `debug`: a causa real nunca chegava ao log e o
                    # usuario via so "encerrou inesperadamente".
                    logger.warning("codex app-server stderr: %s", stderr[-1200:])
                if erro is not None:
                    erro.stderr = stderr

    async def _drive(
        self,
        process: asyncio.subprocess.Process,
        messages: List[Dict[str, Any]],
        model: str,
        reasoning_effort: Optional[str],
    ) -> tuple[str, Optional[str]]:
        await self._request(process, "initialize", {
            "clientInfo": {
                "name": "robinbandit",
                "title": "RobinBandit",
                "version": "0.5.0",
            }
        })
        await self._send(process, {"method": "initialized", "params": {}})

        system_instructions, history, turn_text = _split_messages(messages)
        guard = _PROVIDER_GUARD
        thread = await self._request(process, "thread/start", {
            "model": model,
            "ephemeral": True,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "baseInstructions": system_instructions or guard,
            "developerInstructions": guard,
            "serviceName": "robinbandit",
        })
        thread_obj = thread.get("thread") or {}
        thread_id = thread_obj.get("id") or thread_obj.get("sessionId")
        if not thread_id:
            raise CodexAppServerError("thread/start não retornou thread id")

        injected = _history_items(history)
        if injected:
            await self._request(process, "thread/inject_items", {
                "threadId": thread_id,
                "items": injected,
            })

        final_text = ""
        deltas: List[str] = []
        reasoning: List[str] = []
        turn_done = asyncio.Event()
        turn_error: List[str] = []

        def notification(message: Dict[str, Any]) -> None:
            nonlocal final_text
            method = str(message.get("method") or "")
            params = message.get("params") or {}
            if method == "item/agentMessage/delta":
                delta = params.get("delta") or params.get("text")
                if isinstance(delta, str):
                    deltas.append(delta)
            elif method == "item/reasoning/summaryTextDelta":
                delta = params.get("delta")
                if isinstance(delta, str):
                    reasoning.append(delta)
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage":
                    phase = str(item.get("phase") or "").lower()
                    text = item.get("text")
                    if isinstance(text, str) and (not final_text or phase in {"final", "final_answer"}):
                        final_text = text
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                status = str(turn.get("status") or "completed")
                if status.lower() not in {"completed", "complete"}:
                    error = turn.get("error") or status
                    turn_error.append(str(error))
                turn_done.set()

        effort = str(reasoning_effort or "medium").strip().lower()
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            effort = "medium"
        await self._request(process, "turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": turn_text}],
            "model": model,
            "effort": effort,
            "sandboxPolicy": {"type": "readOnly"},
            "approvalPolicy": "never",
        }, on_notification=notification)

        if process.stdout is None:
            raise CodexAppServerError("codex app-server não abriu a saída")
        while not turn_done.is_set():
            raw = await process.stdout.readline()
            if not raw:
                raise CodexAppServerError("Codex encerrou antes de concluir o turno")
            try:
                message = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if "method" in message and "id" in message:
                await self._decline_server_request(process, message)
            elif "method" in message:
                notification(message)

        if turn_error:
            raise CodexAppServerError(f"turno Codex falhou: {turn_error[-1]}")
        answer = final_text.strip() or "".join(deltas).strip()
        if not answer:
            raise CodexAppServerError("Codex concluiu sem resposta de texto")
        summary = "".join(reasoning).strip() or None
        return answer, summary


async def listar_modelos_codex(binary: str = "codex", *, timeout: float = 20.0) -> List[Dict[str, Any]]:
    """Consulta o catálogo do CLI autenticado, sem iniciar turno nem ler credenciais."""
    executable = resolve_codex_binary(binary)
    if not executable:
        raise CodexAppServerError("Codex CLI não instalado")
    process = await asyncio.create_subprocess_exec(
        executable, "app-server", "--listen", "stdio://",
        "-c", 'model_provider="openai"',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(process.stderr.read()) if process.stderr else None
    client = CodexAppServerClient(binary, timeout=timeout)

    async def consultar() -> List[Dict[str, Any]]:
        await client._request(process, "initialize", {
            "clientInfo": {"name": "robinbandit", "title": "RobinBandit", "version": "0.5.0"}
        })
        await client._send(process, {"method": "initialized", "params": {}})
        modelos: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(20):
            pagina = await client._request(process, "model/list", {
                "cursor": cursor, "limit": 100, "includeHidden": False,
            })
            modelos.extend(item for item in pagina.get("data", []) if isinstance(item, dict))
            cursor = pagina.get("nextCursor")
            if not cursor:
                return modelos
        raise CodexAppServerError("model/list excedeu 20 páginas")

    try:
        return await asyncio.wait_for(consultar(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise CodexAppServerError("model/list do Codex demorou demais") from exc
    finally:
        if process.stdin:
            process.stdin.close()
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if stderr_task:
            await stderr_task


class CodexProvider:
    """Adaptador Robin para modelos da assinatura ChatGPT via Codex CLI."""

    # App-server aqui roda sem ferramentas próprias; tool calls ficam no host.
    supports_tools = False

    def __init__(
        self,
        models: List[str],
        *,
        binary: str = "codex",
        timeout: float = _TETO_DA_CHAMADA_S,
        client_factory=None,
    ):
        self.name = "chatgpt_codex"
        self.models = [str(model).strip() for model in models if str(model).strip()]
        self.binary = binary
        # Cortado pelo teto: o provedor nascia com 180s, mais que o turno inteiro.
        self.timeout = min(float(timeout), _TETO_DA_CHAMADA_S)
        self._client_factory = client_factory or CodexAppServerClient
        self.last_model: Optional[str] = None
        self.last_attempted_model: Optional[str] = None
        self.last_reasoning_summary: Optional[str] = None
        self.last_quota = None
        self.last_tool_calls = None
        self.last_truncated = False
        self.model_failures: List[str] = []


    @property
    def _chave_do_grude(self) -> tuple:
        return (self.name, tuple(self.models))

    @property
    def _modelo_grudado(self) -> Optional[str]:
        return _GRUDADO.get(self._chave_do_grude)

    @_modelo_grudado.setter
    def _modelo_grudado(self, valor: Optional[str]) -> None:
        if valor:
            _GRUDADO[self._chave_do_grude] = valor
        else:
            _GRUDADO.pop(self._chave_do_grude, None)

    @property
    def auth_status(self) -> CodexAuthStatus:
        return codex_auth_status(self.binary)

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        complexity: Optional[str] = None,
        preferred_model: Optional[str] = None,
        tools: Optional[list] = None,
        reasoning_effort: Optional[str] = None,
        strict_model: bool = False,
    ) -> str:
        del temperature, tools  # app-server governa amostragem; ferramentas ficam no host.
        if not self.models:
            raise RuntimeError(f"{self.name}: nenhum modelo configurado")
        status = self.auth_status
        if not status.configured:
            raise RuntimeError(f"{self.name}: {status.detail}")

        models_to_try = list(self.models)
        if preferred_model and strict_model:
            models_to_try = [preferred_model]
        elif preferred_model:
            models_to_try = [preferred_model] + [m for m in models_to_try if m != preferred_model]
        # Gruda no que funcionou. A lista era tentada sempre na mesma ordem,
        # entao um modelo morto custava uma tentativa — e um `app-server`
        # inteiro — em TODA chamada seguinte, antes de chegar no que responde.
        # Medido: numa rodada `gpt-5.6-sol` deu "at capacity" e cada chamada do
        # turno pagou esse tropeco de novo.
        if self._modelo_grudado and not preferred_model:
            models_to_try = (
                [self._modelo_grudado]
                + [m for m in models_to_try if m != self._modelo_grudado]
            )

        self.last_model = None
        self.last_attempted_model = None
        self.last_reasoning_summary = None
        self.last_tool_calls = None
        self.model_failures = []
        last_error: Optional[Exception] = None
        effort = "low" if str(complexity or "").upper() == "CLASSIFY" else reasoning_effort
        for model in models_to_try:
            self.last_attempted_model = f"{self.name}:{model}"
            _comeco = time.monotonic()
            try:
                client = self._client_factory(binary=self.binary, timeout=self.timeout)
                content, summary = await client.complete(
                    messages, model=model, reasoning_effort=effort,
                )
                _gasto = time.monotonic() - _comeco
                if _gasto > _AVISO_DE_LENTIDAO_S:
                    logger.warning("%s: %s levou %.0fs (teto %.0fs).",
                                   self.name, model, _gasto, self.timeout)
                self.last_model = self.last_attempted_model
                self.last_reasoning_summary = summary
                self._modelo_grudado = model
                return content
            except Exception as exc:
                last_error = exc
                self.model_failures.append(model)
                if self._modelo_grudado == model:
                    # O grudado caiu: solta, para nao insistir nele na proxima.
                    self._modelo_grudado = None
                logger.warning("%s: modelo %s falhou: %s", self.name, model, exc)
        raise RuntimeError(f"{self.name}: todos os modelos falharam: {last_error}") from last_error


__all__ = [
    "CodexAppServerClient", "CodexAppServerError", "CodexAuthStatus",
    "CodexProvider", "codex_auth_status", "resolve_codex_binary",
]
