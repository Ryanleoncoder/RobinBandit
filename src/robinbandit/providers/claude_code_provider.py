"""Provedor Claude Code via CLI oficial."""
from __future__ import annotations

import json
import re
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


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


def _conteudo(bruto: Any, imagens: List[str]) -> str:
    """O texto da mensagem; as imagens do conteúdo multimodal vão para `imagens`."""
    if not isinstance(bruto, list):
        return str(bruto or "").strip()
    textos = []
    for parte in bruto:
        if not isinstance(parte, dict):
            continue
        if parte.get("type") == "text":
            textos.append(str(parte.get("text") or ""))
        elif str(parte.get("type") or "").startswith("image"):
            url = parte.get("image_url")
            url = str((url.get("url") if isinstance(url, dict) else url) or "")
            if url.startswith("data:image/") and "base64," in url:
                imagens.append(url)
    return "\n".join(textos).strip()


def _texto_das_mensagens(messages: List[Dict[str, Any]], imagens: Optional[List[str]] = None) -> tuple:
    """Separa instruções e junta o diálogo num prompt único. As imagens do
    conteúdo multimodal vão para `imagens`, na ordem em que aparecem."""
    sistema: List[str] = []
    dialogo: List[str] = []
    imagens = imagens if imagens is not None else []
    for mensagem in messages or []:
        papel = str(mensagem.get("role") or "user").lower()
        conteudo = _conteudo(mensagem.get("content"), imagens)
        # O CLI nao tem papel de ferramenta: a chamada e o resultado viram
        # texto. Sem isto a chamada (conteudo vazio) sumia e o resultado
        # aparecia sem o pedido que o gerou.
        # A chamada passada vai no mesmo bloco que a instrução pede para as novas:
        # em prosa ("chamei X com ..."), o modelo imitava a prosa, nada rodava e
        # ele inventava o resultado.
        chamadas = []
        for chamada in mensagem.get("tool_calls") or []:
            funcao = (chamada or {}).get("function") or {}
            argumentos = funcao.get("arguments") or {}
            if isinstance(argumentos, str):
                try:
                    argumentos = json.loads(argumentos)
                except ValueError:
                    argumentos = {}
            chamadas.append({"name": funcao.get("name"), "arguments": argumentos})
        if chamadas:
            bloco = "```json\n" + json.dumps({"tool_calls": chamadas}, ensure_ascii=False) + "\n```"
            conteudo += ("\n" if conteudo else "") + bloco
        if not conteudo:
            continue
        if papel == "system":
            sistema.append(conteudo)
        elif papel == "assistant":
            dialogo.append(f"Assistente: {conteudo}")
        elif papel == "tool":
            dialogo.append(f"Resultado da ferramenta: {conteudo}")
        else:
            dialogo.append(f"Usuário: {conteudo}")
    return "\n\n".join(sistema), "\n\n".join(dialogo)


def _ler_stream(saida: str) -> Dict[str, Any]:
    """Junta as linhas NDJSON do `--output-format stream-json` num so fato.

    O formato `json` devolvia so o resultado final: nenhum sinal de vida
    enquanto o CLI trabalhava, e nada para preencher `last_reasoning_summary`
    (o Gemini e o Codex preenchem, o Claude Code ficava mudo). O stream traz o
    que existe — mas nao traz o texto do pensamento: medido no CLI 2.1.278, o
    bloco `thinking` vem com `thinking: ""` e so a assinatura, e os
    `thinking_delta` de `--include-partial-messages` vem vazios tambem. O que
    chega de verdade e o contador `system/thinking_tokens`. Entao lemos o texto
    quando ele vier (outro modelo pode expor) e, quando nao vier, contamos.
    """
    texto: List[str] = []
    pensamento: List[str] = []
    chamadas: List[Dict[str, Any]] = []
    tokens_de_pensamento = 0
    resultado: Optional[str] = None
    uso: Dict[str, Any] = {}
    custo = None
    erro: Optional[str] = None

    for linha in saida.splitlines():
        linha = linha.strip()
        if not linha.startswith("{"):
            # O CLI imprime aviso de workspace nao confiado no meio do stream.
            continue
        try:
            evento = json.loads(linha)
        except (ValueError, json.JSONDecodeError):
            continue
        tipo = evento.get("type")
        if tipo == "system" and evento.get("subtype") == "thinking_tokens":
            try:
                tokens_de_pensamento = int(evento.get("estimated_tokens") or 0)
            except (TypeError, ValueError):
                pass
        elif tipo == "assistant":
            for bloco in (evento.get("message") or {}).get("content") or []:
                if bloco.get("type") == "text":
                    texto.append(str(bloco.get("text") or ""))
                elif bloco.get("type") == "thinking":
                    pensamento.append(str(bloco.get("thinking") or ""))
                elif bloco.get("type") == "tool_use":
                    chamadas.append({"id": str(bloco.get("id") or ""), "nome": str(bloco.get("name") or ""),
                                     "argumentos": bloco.get("input") or {}})
        elif tipo == "result":
            # Com as ferramentas nativas o CLI roda um passo só (`--max-turns 1`)
            # e termina em `error_max_turns` depois do tool_use: é o fim esperado.
            if evento.get("is_error") and not (chamadas and evento.get("subtype") == "error_max_turns"):
                erro = str(evento.get("result") or "erro sem descricao")
            resultado = str(evento.get("result") or "")
            uso = evento.get("usage") or {}
            custo = evento.get("total_cost_usd")

    return {
        "texto": resultado if resultado else "".join(texto),
        "chamadas": chamadas,
        # Sem resultado e sem texto o stream nao chegou ao fim: quem chama
        # precisa distinguir "respondeu vazio" de "morreu no meio".
        "completou": resultado is not None,
        "pensamento": "".join(pensamento).strip(),
        "tokens_de_pensamento": tokens_de_pensamento,
        "uso": uso,
        "custo": custo,
        "erro": erro,
    }


def _resumo_do_pensamento(lido: Dict[str, Any]) -> Optional[str]:
    """O que mostrar de raciocinio. Nunca inventa o texto que o CLI nao deu."""
    if lido.get("pensamento"):
        return str(lido["pensamento"])[:2400]
    tokens = int(lido.get("tokens_de_pensamento") or 0)
    if tokens > 0:
        return (f"Pensou por cerca de {tokens} tokens antes de responder "
                f"(o CLI do Claude Code nao expoe o texto do raciocinio).")
    return None


# O CLI nao aceita definicao de ferramenta: `--tools ""` o deixa ser modelo, e
# modelo sem ferramenta nao emite `tool_use`. O agente que chama JA manda
# `tools=` (o orquestrador monta em `llm/tool_schemas.py`) e o provedor engolia
# isso num `**_ignorado` — por isso `last_tool_calls` nunca saia de None e o
# caminho nativo, que existe e funciona nos provedores de API, nunca disparava
# aqui. Este bloco e a adaptacao: o canal de fala que o `tool_use` deixa aberto
# de graca, aqui precisa ser aberto a mao.
_COMO_USAR_FERRAMENTA = """

## Como chamar ferramentas aqui
Este ambiente não tem canal próprio de chamada de ferramenta: a chamada vai no
texto, e o agente que te chamou executa. Quando o pedido pede ação, responda
com uma frase curta, na primeira pessoa, dizendo o que vai fazer agora (ela
aparece na tela enquanto a pessoa espera; o passo ainda não rodou, então sem
prometer resultado), seguida de um bloco assim:

```json
{{"tool_calls": [{{"name": "<ferramenta>", "arguments": {{...}}}}]}}
```

Só a frase, sem o bloco, encerra o turno sem executar nada. Quando o pedido
já está resolvido ou não precisa de ferramenta, responda em texto, sem bloco.
Várias chamadas podem ir na mesma lista: as independentes, e também uma
sequência em que você já sabe o próximo passo; elas rodam em ordem, e se uma
falhar as seguintes não rodam e você decide de novo com o resultado.

Ferramentas disponíveis, com os parâmetros de cada uma:
{ferramentas}
"""


_COMO_USAR_FERRAMENTA_NATIVA = """

## Ferramentas
As ferramentas do Sentury estão no seu canal de ferramentas (`mcp__sentury__<nome>`). Quando o
pedido pede ação, escreva uma frase curta dizendo o que vai fazer e chame a ferramenta; chamadas
independentes podem ir juntas. Quem executa é o Sentury: o resultado volta na mensagem seguinte.
Sem ação a fazer, responda em texto.
"""

_PREFIXO_MCP = "mcp__sentury__"


def _especificacoes(tools: Any) -> List[Dict[str, Any]]:
    """As ferramentas no formato que o servidor MCP declara ao CLI."""
    saida = []
    for t in tools or []:
        fn = t.get("function") if isinstance(t, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            saida.append({"name": fn["name"], "description": fn.get("description", ""),
                          "parameters": fn.get("parameters") or {"type": "object", "properties": {}}})
    return saida


def _config_do_mcp(pasta: str, tools: Any) -> str:
    """Grava as ferramentas e a config do servidor MCP que só as declara; o caminho da config."""
    import sys

    ferramentas = os.path.join(pasta, "ferramentas.json")
    with open(ferramentas, "w", encoding="utf-8") as f:
        json.dump(_especificacoes(tools), f, ensure_ascii=False)
    servidor = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ferramentas_mcp.py")
    config = os.path.join(pasta, "mcp.json")
    with open(config, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"sentury": {"command": sys.executable, "args": [servidor, ferramentas]}}}, f)
    return config


def _ferramentas_para_o_texto(tools: Any) -> str:
    """Nome, descrição e parâmetros de cada ferramenta, um JSON por linha."""
    linhas = []
    for t in tools or []:
        fn = t.get("function") if isinstance(t, dict) else None
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        linhas.append(json.dumps({"name": fn["name"], "description": fn.get("description", ""),
                                  "parameters": fn.get("parameters", {})}, ensure_ascii=False))
    return "\n".join(linhas) or "(nenhuma)"


# Os níveis do `--effort` do CLI. `none` (pensamento desligado, o Leve em
# outros provedores) não existe nele: vira o menor.
_ESFORCOS_DO_CLI = ("low", "medium", "high", "xhigh", "max")


def esforco_do_cli(nivel: Optional[str]) -> Optional[str]:
    nivel = str(nivel or "").strip().lower()
    if nivel in ("none", "minimal", "off"):
        return "low"
    return nivel if nivel in _ESFORCOS_DO_CLI else None


def _entrada_com_imagens(prompt: str, imagens: List[str]) -> str:
    """Uma linha do `--input-format stream-json`: o prompt e as imagens em base64."""
    partes: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for url in imagens:
        cabecalho, dados = url.split("base64,", 1)
        partes.append({"type": "image", "source": {"type": "base64", "data": dados,
                                                    "media_type": cabecalho[5:].rstrip(";") or "image/png"}})
    return json.dumps({"type": "user", "message": {"role": "user", "content": partes}}, ensure_ascii=False) + "\n"


def _uma_chamada(item: Any, nomes: Optional[set] = None) -> Optional[Dict[str, Any]]:
    """`{name|tool, arguments|args}` ou `{function: {name, arguments}}` no formato de `tool_calls`.
    Com `nomes`, só vale nome de ferramenta que está na mesa."""
    if not isinstance(item, dict):
        return None
    funcao = item.get("function") if isinstance(item.get("function"), dict) else item
    nome = funcao.get("tool") or funcao.get("name")
    if not nome or (nomes is not None and str(nome) not in nomes):
        return None
    argumentos = funcao.get("arguments") or funcao.get("args") or {}
    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos)
        except ValueError:
            argumentos = {}
    return {"function": {"name": str(nome), "arguments": argumentos if isinstance(argumentos, dict) else {}}}


_BLOCO_JSON = re.compile(r"```(?:json)?\s*(.*?)(?:```|$)", re.DOTALL)


def _fechar_json(trecho: str) -> str:
    """Fecha o que o modelo deixou aberto no fim do JSON (a chave que faltou num
    roteiro aninhado), contando colchetes e chaves fora das strings."""
    pilha: List[str] = []
    dentro, escapado = False, False
    for c in trecho:
        if dentro:
            if escapado:
                escapado = False
            elif c == "\\":
                escapado = True
            elif c == '"':
                dentro = False
            continue
        if c == '"':
            dentro = True
        elif c in "{[":
            pilha.append("}" if c == "{" else "]")
        elif c in "}]" and pilha and pilha[-1] == c:
            pilha.pop()
    return trecho.rstrip() + "".join(reversed(pilha)) if pilha and not dentro else trecho


def _dos_blocos_fechados(texto: str) -> str:
    """Os blocos ```json do texto, cada um fechado se o modelo esqueceu o fim."""
    return "\n".join(_fechar_json(m.group(1).strip()) for m in _BLOCO_JSON.finditer(texto))


def _chamadas_do_texto(texto: str, nomes: Optional[set] = None) -> Optional[List[Dict[str, Any]]]:
    """Traduz o JSON que o modelo escreveu para o formato de `tool_calls`.

    O provedor de API devolve `tool_calls` estruturado; aqui o mesmo conteúdo
    chega como texto. Traduzir no provedor — e não no orquestrador — é o que
    faz o CLI entrar pela mesma porta que os outros: quem chama não precisa
    saber de onde veio.

    Aceita `tool_calls` (o pedido na instrução), `plan` (o contrato do
    planejador) e, com o nome de uma ferramenta da mesa, a chamada solta
    (`{name, arguments}`, ou no formato `{function: ...}`), sozinha ou em lista.
    """
    soltas: List[Dict[str, Any]] = []
    for trecho in _objetos_json(texto):
        try:
            dados = json.loads(trecho)
        except (ValueError, json.JSONDecodeError):
            continue
        if not isinstance(dados, dict):
            continue
        itens = dados.get("plan") or dados.get("tool_calls")
        if isinstance(itens, list):
            chamadas = [c for c in (_uma_chamada(i) for i in itens) if c]
            if chamadas:
                return chamadas
            continue
        if nomes and (chamada := _uma_chamada(dados, nomes)):
            soltas.append(chamada)
    if soltas:
        return soltas
    # Nada inteiro no texto: tenta de novo com os blocos json fechados.
    fechados = _dos_blocos_fechados(texto)
    if fechados and fechados != texto:
        return _chamadas_do_texto(fechados, nomes)
    return None


def _objetos_json(texto: str) -> Iterator[str]:
    """Cada objeto `{...}` de primeiro nivel do texto, por contagem de chaves.

    Tentar `json.loads` em cada corte possivel custa um parse por caractere;
    num plano de cinco mil caracteres isso e trabalho a toa. Aqui o fim do
    objeto sai da propria estrutura, e aspas e escape nao confundem a contagem.
    """
    profundidade = 0
    inicio = -1
    dentro_de_aspas = False
    escapado = False
    for i, c in enumerate(texto):
        if dentro_de_aspas:
            if escapado:
                escapado = False
            elif c == "\\":
                escapado = True
            elif c == '"':
                dentro_de_aspas = False
            continue
        if c == '"':
            dentro_de_aspas = True
        elif c == "{":
            if profundidade == 0:
                inicio = i
            profundidade += 1
        elif c == "}":
            profundidade -= 1
            if profundidade == 0 and inicio != -1:
                yield texto[inicio:i + 1]
                inicio = -1
            elif profundidade < 0:
                profundidade = 0


class ClaudeCodeProvider:
    """Fala com o modelo da assinatura pelo CLI, em modo não-interativo."""

    # O CLI roda sem ferramentas proprias e nao devolve chamada estruturada.
    # Declarar `False` tirava o provedor da lista sempre que o turno mandava
    # `tools=` — e o Dedicado nao tem fallback, entao o modo ficava sem
    # ninguem. Agora `_chamadas_do_texto` traduz o que ele escreve para o
    # formato de `tool_calls`, e o texto que sobra e a fala do passo: o mesmo
    # que o `tool_use` entrega de graca nos provedores de API.
    supports_tools = True

    def __init__(
        self,
        *,
        name: str = "claude_code",
        binary: str = "claude",
        models: Optional[List[str]] = None,
        timeout: float = _TETO_DA_CHAMADA_S,
        cwd: str = "",
    ):
        self.name = name
        self.binary = binary
        self.models = list(models or [])
        self.timeout = min(max(10.0, float(timeout)), _TETO_DA_CHAMADA_S)
        self.cwd = cwd or os.getcwd()
        self.last_usage: Dict[str, Any] = {}
        # Lidos pela cadeia depois de cada chamada (telemetria e diagnostico).
        self.last_model: Optional[str] = None
        self.last_attempted_model: Optional[str] = None
        self.last_quota = None
        self.last_tool_calls = None
        self.last_reasoning_summary: Optional[str] = None
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
    def configured(self) -> bool:
        return claude_code_auth_status(self.binary).configured

    def _comando(self, sistema_em_arquivo: str, modelo: str, com_imagem: bool = False,
                 esforco: Optional[str] = None, config_do_mcp: str = "") -> List[str]:
        """O comando SEM os textos grandes: eles nao cabem em `argv`.

        O `CreateProcess` do Windows corta a linha de comando em 32.767
        caracteres, e a persona sozinha tem 27 mil. O prompt vai por stdin e
        o sistema por arquivo — as duas rotas que o proprio CLI oferece."""
        # Montar o comando e descobrir se o CLI esta instalado sao duas
        # responsabilidades diferentes. Manter a montagem pura permite
        # validar em qualquer SO que prompt e sistema nao vazam para argv. A
        # disponibilidade real continua sendo verificada por ``configured``
        # antes de ``complete`` e uma execucao direta ainda falha naturalmente.
        executavel = resolve_claude_binary(self.binary) or self.binary
        # `-p` sem argumento le o prompt de stdin (`--input-format text`).
        # `stream-json` no lugar de `json`: o formato fechado devolvia so o
        # resultado final, sem nenhum sinal de que o modelo estava trabalhando.
        # `--verbose` e exigencia do proprio CLI para stream com `-p`.
        comando = [executavel, "-p", "--output-format", "stream-json", "--verbose"]
        if com_imagem:
            # Imagem só entra pela entrada em stream-json, como bloco base64.
            comando += ["--input-format", "stream-json"]
        # O Sentury controla ferramentas e laço; o CLI não deve iniciar ações
        # próprias nem herdar hooks ou instruções do projeto.
        comando += ["--tools", "", "--permission-mode", "dontAsk",
                    "--setting-sources", "", "--strict-mcp-config"]
        if sistema_em_arquivo:
            # Substitui, nao anexa: a persona do CLI descreve ferramentas que
            # ele nao tem aqui, e o modelo continuava tentando usa-las.
            comando += ["--system-prompt-file", sistema_em_arquivo]
        if modelo:
            comando += ["--model", modelo]
        # Sem o nível, o CLI pensa o quanto quiser: centenas de tokens de
        # raciocínio antes de cada passo do computer use.
        if esforco := esforco_do_cli(esforco):
            comando += ["--effort", esforco]
        if config_do_mcp:
            # As ferramentas do Sentury como ferramentas de verdade; um passo só,
            # porque quem executa é o Sentury.
            comando += ["--mcp-config", config_do_mcp, "--max-turns", "1"]
        return comando

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        preferred_model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        **_ignorado: Any,
    ) -> str:
        """O nome que a cadeia chama. Sem isto o provedor era inalcancavel."""
        # `ReinforcedProvider.complete` faz `inspect.signature(provider.complete)`;
        # como so existia `generate`, o AttributeError era engolido pelo
        # `except Exception` do laco e o tier inteiro reportava "nenhuma conta
        # respondeu". O provedor estava pronto e ninguem conseguia chegar nele.
        del temperature  # o CLI governa a amostragem
        if not self.configured:
            raise ClaudeCodeError(f"{self.name}: execute `claude login`")
        # Gruda no que respondeu. Percorrer a lista sempre na mesma ordem faz
        # um modelo morto custar uma tentativa em TODA chamada seguinte, antes
        # de chegar no que funciona — e aqui cada tentativa e um processo do
        # CLI. Grudar nao vira teimosia: o que cai e solto na hora.
        tentar = list(self.models) or [""]
        if preferred_model:
            escolhido = str(preferred_model).strip()
            tentar = [escolhido] + [m for m in tentar if m != escolhido]
        elif self._modelo_grudado:
            tentar = (
                [self._modelo_grudado]
                + [m for m in tentar if m != self._modelo_grudado]
            )

        self.last_model = None
        self.last_reasoning_summary = None
        self.last_tool_calls = None
        self.model_failures = []
        ultimo_erro: Optional[Exception] = None
        for modelo in tentar:
            self.last_attempted_model = f"{self.name}:{modelo}" if modelo else self.name
            _comeco = time.monotonic()
            try:
                resposta = await self.generate(messages, model=modelo, tools=tools,
                                               reasoning_effort=reasoning_effort)
            except Exception as exc:
                ultimo_erro = exc
                if modelo:
                    self.model_failures.append(modelo)
                if self._modelo_grudado == modelo:
                    self._modelo_grudado = None
                logger.warning("%s: modelo %s falhou: %s", self.name, modelo or "(padrao)", exc)
                continue
            _gasto = time.monotonic() - _comeco
            if _gasto > _AVISO_DE_LENTIDAO_S:
                logger.warning("%s: %s levou %.0fs (teto %.0fs).",
                               self.name, modelo or "(padrao)", _gasto, self.timeout)
            self.last_model = self.last_attempted_model
            self._modelo_grudado = modelo
            return resposta
        raise ClaudeCodeError(f"{self.name}: todos os modelos falharam: {ultimo_erro}")

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        **_ignorado: Any,
    ) -> str:
        import asyncio

        imagens: List[str] = []
        sistema, prompt = _texto_das_mensagens(messages, imagens)
        pasta_do_mcp = tempfile.mkdtemp(prefix="sentury-mcp-") if tools else ""
        if tools:
            sistema = (sistema or "") + _COMO_USAR_FERRAMENTA_NATIVA
        if not prompt:
            raise ClaudeCodeError("nada para perguntar")

        escolhido = str(model or "").strip() or (self.models[0] if self.models else "")
        # O sistema vai para um arquivo temporario; o prompt, para stdin.
        arquivo_sistema = ""
        if sistema:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(sistema)
                arquivo_sistema = f.name
        comando = self._comando(arquivo_sistema, escolhido, com_imagem=bool(imagens), esforco=reasoning_effort,
                                config_do_mcp=_config_do_mcp(pasta_do_mcp, tools) if tools else "")
        entrada = _entrada_com_imagens(prompt, imagens) if imagens else prompt

        def _rodar() -> subprocess.CompletedProcess:
            return subprocess.run(
                comando,
                input=entrada,
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

        inicio = time.monotonic()
        try:
            resultado = await asyncio.get_running_loop().run_in_executor(None, _rodar)
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCodeError(f"Claude Code passou de {self.timeout:.0f}s") from exc
        except OSError as exc:
            raise ClaudeCodeError(f"{type(exc).__name__} ao chamar o Claude Code") from exc
        finally:
            if arquivo_sistema:
                try:
                    os.unlink(arquivo_sistema)
                except OSError:
                    pass
            if pasta_do_mcp:
                import shutil

                shutil.rmtree(pasta_do_mcp, ignore_errors=True)

        saida = (resultado.stdout or "").strip()
        if not saida:
            # O stderr traz aviso de workspace não confiado junto do erro real;
            # a última linha costuma ser o que importa.
            motivo = (resultado.stderr or "").strip().splitlines()[-1:] or ["sem saída"]
            raise ClaudeCodeError(motivo[0][:300])

        lido = _ler_stream(saida)
        if lido["erro"]:
            raise ClaudeCodeError(lido["erro"][:300])
        if not lido["completou"] and not lido["texto"] and not lido["chamadas"]:
            # Sem evento `result` e sem texto, o CLI morreu no meio. Devolver ""
            # aqui faria a cadeia tratar a morte como resposta vazia e seguir.
            motivo = (resultado.stderr or "").strip().splitlines()[-1:] or ["stream interrompido"]
            raise ClaudeCodeError(motivo[0][:300])

        uso = lido["uso"]
        self.last_usage = {
            "entrada": int(uso.get("input_tokens") or 0),
            "saida": int(uso.get("output_tokens") or 0),
            "cacheado": int(uso.get("cache_read_input_tokens") or 0),
            "custo_usd": lido["custo"],
        }
        self.last_reasoning_summary = _resumo_do_pensamento(lido)
        nomes = {str((f.get("function") or {}).get("name")) for f in tools or [] if isinstance(f, dict)}
        nativas = [{"id": c["id"], "type": "function",
                    "function": {"name": c["nome"].removeprefix(_PREFIXO_MCP), "arguments": c["argumentos"]}}
                   for c in lido["chamadas"] if c["nome"].removeprefix(_PREFIXO_MCP) in nomes]
        # Plano B: modelo que ainda escreva a chamada no texto.
        self.last_tool_calls = (nativas or _chamadas_do_texto(lido["texto"], nomes)) if tools else None
        if tools and not self.last_tool_calls and "{" in lido["texto"]:
            # Chamada escrita que o leitor não reconheceu: o texto cru diz o formato.
            logger.warning("Claude Code: JSON no texto sem chamada reconhecida: %s", lido["texto"][:2000])
        logger.info("Claude Code %s (esforço %s): %.1fs, sistema %d + prompt %d caracteres, %d imagem(ns), "
                    "saida %d tokens (pensamento %s)", escolhido, esforco_do_cli(reasoning_effort) or "padrão",
                    time.monotonic() - inicio, len(sistema or ""), len(prompt), len(imagens),
                    self.last_usage["saida"], lido.get("tokens_de_pensamento") or 0)
        return lido["texto"]


__all__ = [
    "ClaudeCodeAuthStatus",
    "ClaudeCodeError",
    "ClaudeCodeProvider",
    "claude_code_auth_status",
    "resolve_claude_binary",
]
