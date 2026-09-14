"""Endpoint OpenAI-compatible: qualquer agente que aceite trocar a base_url
passa a rotear pelo bandit sem código de integração.

O protocolo OpenAI não tem campo para "essa resposta foi boa", então o canal de
qualidade — que é o que o router tem de diferente — vive num endpoint próprio,
`POST /feedback`, correlacionado pelo `id` que a resposta já devolve.

Extra opcional: `pip install robinbandit[server]`. O núcleo não depende disso.
"""
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .clientes import Clientes as _Clientes
from pydantic import BaseModel, Field

from pathlib import Path

from .chain import ChainProvider


def pasta_das_logos() -> Path:
    """A arte dos provedores, dentro do pacote.

    Ficava em `assets/` na raiz do repositorio: quem clonava via as imagens e
    quem instalava pelo pip abria o painel com tudo quebrado.
    """
    return Path(__file__).resolve().parent / "assets" / "providers"


# Teto de decisões guardadas à espera de feedback. Sem isso o dicionário cresce
# para sempre; com isso, feedback muito atrasado é descartado em silêncio.
_MAX_PENDENTES = 10_000


def _com_conexao(ferramentas: List[Dict[str, Any]], clientes) -> List[Dict[str, Any]]:
    """Casa a configuração de cada ferramenta com quem já chamou.

    O `id` do `cli_tools` e o que `clientes.detectar` devolve são o mesmo
    vocabulário de propósito: assim a tela junta as duas coisas sem uma tabela
    de tradução no meio, que envelheceria sozinha.
    """
    vistos = {item["id"]: item for item in clientes.status()}
    return [{**f, "conexao": vistos.get(f["id"])} for f in ferramentas]


class _Mensagem(BaseModel):
    role: str
    content: str


class _Pedido(BaseModel):
    messages: List[_Mensagem]
    model: Optional[str] = None
    temperature: float = 0.2
    stream: bool = False


class _PedidoAnthropic(BaseModel):
    """O que o Claude Code manda em `/v1/messages`.

    Campos que existem no protocolo e são ignorados de propósito — `tools`,
    `thinking`, `output_config`, `metadata` — nem aparecem aqui: o Pydantic
    descarta o que não foi declarado, e declarar para não usar daria a entender
    que são atendidos.
    """

    messages: List[Dict[str, Any]]
    model: Optional[str] = None
    system: Optional[Union[str, List[Dict[str, Any]]]] = None
    max_tokens: Optional[int] = None
    temperature: float = 0.2
    stream: bool = False


class _PedidoResponses(BaseModel):
    """Campos do protocolo usado pelo Codex CLI atual.

    Itens desconhecidos continuam aceitos pelo Pydantic e são descartados. A
    compatibilidade que afirmamos fica explícita aqui: histórico, ferramentas,
    esforço de raciocínio e SSE.
    """

    input: Any
    model: Optional[str] = None
    instructions: Any = None
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning: Optional[Dict[str, Any]] = None
    temperature: Optional[float] = 0.2
    stream: bool = False


class _Feedback(BaseModel):
    id: str
    good: bool


class _Estrategia(BaseModel):
    valor: str


class _Idioma(BaseModel):
    valor: str


class _Cadeia(BaseModel):
    nomes: List[str]


class _Modelos(BaseModel):
    provedor: str
    modelos: List[str]


class _Tier(BaseModel):
    provedor: str
    tier: Optional[int] = None


class _Conta(BaseModel):
    """Uma conta nomeada de um provedor: `openrouter paga`, `groq 2`."""

    id: str
    provedor: str
    variavel: str
    label: str = ""
    # Crédito pago fica reservado para o que vale a pena: sem esta marca, uma
    # tarefa lateral gasta a chave cara igual à gratuita.
    paga: bool = False


class _TierDaConta(BaseModel):
    tier: str
    conta: str


class _OrdemDoReforcado(BaseModel):
    contas: List[str]


class _Credencial(BaseModel):
    """O valor entra; nunca sai. Só o nome da variável volta nas respostas."""

    variavel: str
    valor: str
    # Uma conta pode ter várias chaves — o rotador alterna quando uma bate a
    # cota. Substituir por padrão seria apagar as outras em silêncio.
    adicionar: bool = True
    # Apelido dado na hora de colar. Quatro chaves do mesmo provedor viravam
    # quatro dicas de quatro caracteres, e rotacionar era adivinhar.
    rotulo: str = ""
    paga: bool = False


class _Ping(BaseModel):
    ativo: Optional[bool] = None
    intervalo_s: Optional[float] = None
    so_em_cooldown: Optional[bool] = None


class _RotuloDaChave(BaseModel):
    rotulo: Optional[str] = None
    paga: Optional[bool] = None


def create_app(providers: List[Any], router, cache=None, config=None) -> FastAPI:
    """Monta o app sobre os provedores e o router que você já tem.

    O campo `model` do pedido vira o **contexto** do bandit. É o único campo que
    todo cliente OpenAI envia, então dá para escolher contexto de um cliente sem
    modificação: `model="auditoria"` aprende numa célula, `model="triagem"` em
    outra. Sem `model`, cai na célula default.
    """
    app = FastAPI(title="RobinBandit")
    # id da resposta -> (provedor que respondeu, contexto), para o /feedback
    # atribuir a recompensa à decisão certa mesmo chegando muito depois.
    decisoes: "OrderedDict[str, tuple]" = OrderedDict()
    # Quem está do outro lado, para a tela Conectar responder "funcionou?".
    clientes = _Clientes()

    def rota_da_chamada(request: Request):
        """Traduz o modo HTTP sem sequestrar o campo `model` do cliente."""
        modo = str(request.headers.get("x-robinbandit-mode") or "router").strip().lower()
        if modo in {"", "auto", "normal", "router"}:
            return list(providers), None
        if modo not in {"hybrid", "reinforced", "reforcado"}:
            raise HTTPException(
                400,
                "X-RobinBandit-Mode aceita normal, router ou reinforced; "
                "Dedicado é configurado pelo Sentury.",
            )
        if config is None:
            raise HTTPException(400, "Reforçado exige um catálogo configurado")
        from .providers import build_tier_provider
        from .selection import RouteSelection

        reforcado = build_tier_provider(config, "ultra")
        return [reforcado, *providers], RouteSelection.hybrid("ultra")

    @app.post("/v1/chat/completions")
    async def chat_completions(pedido: _Pedido, request: Request) -> Dict[str, Any]:
        if pedido.stream:
            raise HTTPException(400, "streaming não é suportado")

        contexto = pedido.model
        # Antes de qualquer coisa que possa falhar: uma chamada que chegou e
        # deu errado prova tanto quanto uma que deu certo que a ferramenta
        # encontrou o RobinBandit — e é justo quando a tela precisa dizer isso.
        clientes.anotar(request.headers.get("user-agent", ""), contexto)
        # Uma cadeia por request: last_provider é atributo de instância e uma
        # cadeia compartilhada embaralharia as respostas concorrentes.
        provedores_da_chamada, selecao = rota_da_chamada(request)
        chain = ChainProvider(provedores_da_chamada, router, cache=cache)
        mensagens = [m.model_dump() for m in pedido.messages]
        try:
            texto = await chain.complete(
                mensagens, pedido.temperature, context=contexto, selection=selecao,
            )
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

        rid = f"chatcmpl-{uuid.uuid4().hex}"
        if chain.last_provider:
            decisoes[rid] = (chain.last_provider, contexto)
            while len(decisoes) > _MAX_PENDENTES:
                decisoes.popitem(last=False)

        corpo = {
            "id": rid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": chain.last_model or "robinbandit",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": texto},
                "finish_reason": "stop",
            }],
        }
        if isinstance(chain.last_usage, dict):
            entrada = int(chain.last_usage.get("entrada") or 0)
            saida = int(chain.last_usage.get("saida") or 0)
            corpo["usage"] = {
                "prompt_tokens": entrada,
                "completion_tokens": saida,
                "total_tokens": int(chain.last_usage.get("total") or 0) or entrada + saida,
            }
        return corpo

    @app.post("/v1/messages")
    async def messages(pedido: _PedidoAnthropic, request: Request) -> Any:
        """O protocolo da Anthropic, que é o que o Claude Code fala.

        Ele não chama `/v1/chat/completions`: chama aqui, com `system` à parte e
        `content` em blocos. Enquanto esta rota não existia, a configuração que
        o painel entregava respondia 404 — a tela prometia uma ligação que nunca
        se completava.

        O `model` continua sendo o contexto do bandit, igual ao endpoint
        OpenAI: `ANTHROPIC_MODEL=codigo` aprende numa célula, `revisao` em
        outra.
        """
        from . import anthropic_api

        contexto = pedido.model
        clientes.anotar(request.headers.get("user-agent", ""), contexto)

        mensagens = anthropic_api.para_mensagens(pedido.messages, pedido.system)
        if not mensagens:
            raise HTTPException(400, "nenhuma mensagem de texto no pedido")

        provedores_da_chamada, selecao = rota_da_chamada(request)
        chain = ChainProvider(provedores_da_chamada, router, cache=cache)
        try:
            texto = await chain.complete(
                mensagens, pedido.temperature, context=contexto, selection=selecao,
            )
        except RuntimeError as exc:
            # No envelope da Anthropic: o cliente lê `error.message` e mostra o
            # motivo real em vez de "unknown error".
            return JSONResponse(status_code=502, content=anthropic_api.erro(str(exc)))

        corpo = anthropic_api.resposta(texto, chain.last_model, chain.last_usage)
        if chain.last_provider:
            decisoes[corpo["id"]] = (chain.last_provider, contexto)
            while len(decisoes) > _MAX_PENDENTES:
                decisoes.popitem(last=False)

        if pedido.stream:
            # O cliente pede SSE; a resposta já está pronta e vai inteira, num
            # bloco só. Não é streaming de verdade — é o formato que ele sabe
            # ler. Streaming real exigiria os provedores entregarem token a
            # token, e nem todos entregam.
            return StreamingResponse(
                anthropic_api.eventos(corpo),
                media_type="text/event-stream",
            )
        return corpo

    @app.post("/v1/responses")
    async def responses(pedido: _PedidoResponses, request: Request) -> Any:
        """Responses API para o Codex entrar pelo mesmo roteador.

        O protocolo é traduzido na borda. A conta ChatGPT/Codex de saída
        continua sendo apenas mais um provedor e não é confundida com o cliente
        que chamou esta rota.
        """
        from . import responses_api

        contexto = pedido.model
        clientes.anotar(request.headers.get("user-agent", ""), contexto)
        mensagens = responses_api.para_mensagens(pedido.input, pedido.instructions)
        if not mensagens:
            raise HTTPException(400, "nenhuma mensagem utilizável no pedido")
        ferramentas, personalizadas = responses_api.para_ferramentas(pedido.tools)
        esforco = None
        if isinstance(pedido.reasoning, dict):
            esforco = pedido.reasoning.get("effort")

        provedores_da_chamada, selecao = rota_da_chamada(request)
        chain = ChainProvider(provedores_da_chamada, router, cache=cache)
        try:
            texto = await chain.complete(
                mensagens,
                pedido.temperature if pedido.temperature is not None else 0.2,
                context=contexto,
                selection=selecao,
                tools=ferramentas or None,
                reasoning_effort=str(esforco) if esforco else None,
            )
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

        corpo = responses_api.resposta(
            texto,
            chain.last_model,
            chain.last_usage,
            chain.last_tool_calls,
            personalizadas,
        )
        if chain.last_provider:
            decisoes[corpo["id"]] = (chain.last_provider, contexto)
            while len(decisoes) > _MAX_PENDENTES:
                decisoes.popitem(last=False)

        if pedido.stream:
            return StreamingResponse(
                responses_api.eventos(corpo),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return corpo

    @app.post("/feedback")
    async def feedback(fb: _Feedback) -> Dict[str, Any]:
        """Fecha o loop de qualidade. O `id` é o da resposta que você avaliou —
        pode chegar bem depois, quando o revisor terminar."""
        decisao = decisoes.pop(fb.id, None)
        if decisao is None:
            raise HTTPException(404, "id desconhecido ou já avaliado")
        provedor, contexto = decisao
        router.reward_quality(provedor, contexto, fb.good)
        return {"ok": True, "provider": provedor}

    @app.get("/v1/models")
    async def models() -> Dict[str, Any]:
        # Clientes que enumeram modelos esperam esta rota. O que o RobinBandit
        # expõe são os provedores; qual modelo cada um usa é decisão dele.
        return {
            "object": "list",
            "data": [
                {"id": getattr(p, "name", type(p).__name__),
                 "object": "model", "owned_by": "robinbandit"}
                for p in providers
            ],
        }

    @app.get("/state")
    async def state() -> Dict[str, Any]:
        return {"providers": router.snapshot(), "pending_feedback": len(decisoes)}

    @app.get("/painel", response_class=HTMLResponse)
    async def painel_html() -> str:
        from .painel import PAGINA

        return PAGINA

    @app.get("/painel/dados")
    async def painel_dados(request: Request) -> Dict[str, Any]:
        """O que a página mostra. Tudo daqui já existe no router — a página não
        calcula nada, só desenha."""
        from . import cli_tools

        estado = router.snapshot()
        todos = [getattr(p, "name", type(p).__name__) for p in providers]
        # O último recurso não é provedor: é o aviso de que nenhum respondeu.
        # Listado junto, ele aparecia num ranking de qualidade e num gráfico de
        # uptime, como se competisse com os outros.
        ultimo = str(getattr(config, "last_resort", "") or "").strip().lower()
        nomes = [n for n in todos if n != ultimo]

        provedores = []
        for nome in nomes:
            dados = estado.get(nome) or {}
            provedores.append({
                "nome": nome,
                "status": dados.get("status") or "",
                "ok": dados.get("ok", 0),
                "err": dados.get("err", 0),
                "latencia_ms": dados.get("latency_ms"),
                "cooldown": dados.get("cooldown", 0),
                "qualidade": dados.get("quality_mean") or dados.get("health_mean") or 0,
                "amostras": dados.get("quality_samples", 0),
            })

        # A ordem de verdade, pedida ao router — não uma reordenação da página.
        ordem = []
        try:
            for provedor in router.order(list(providers), "painel"):
                nome = getattr(provedor, "name", type(provedor).__name__)
                if nome == ultimo:
                    continue
                dados = estado.get(nome) or {}
                ok, err = dados.get("ok", 0), dados.get("err", 0)
                total = ok + err
                cooldown = dados.get("cooldown", 0)
                # Qualidade só existe com feedback; sem ele o que o router tem
                # é saúde. Mostrar "—" nas duas esconde que ele está decidindo
                # com alguma coisa.
                qualidade = dados.get("quality_mean")
                saude = dados.get("health_mean")
                # Sem nenhuma chamada, o número é o prior do catálogo — um
                # palpite de fábrica, igual para todo mundo. Escrito como
                # "0.60" ele passava por medição de um provedor nunca usado.
                estimado = not total
                ordem.append({
                    "nome": nome,
                    # O número cru, para a página desenhar a barra; o texto é só
                    # para quem lê a tabela.
                    "qualidade_num": qualidade or saude or 0,
                    "estimado": estimado,
                    "qualidade": (
                        f"{(qualidade or saude):.2f} estimado" if estimado and (qualidade or saude)
                        else f"{qualidade:.2f}" if qualidade
                        else f"{saude:.2f} (saúde)" if saude else "—"
                    ),
                    "sucesso": f"{(ok / total * 100):.0f}%" if total else "—",
                    "latencia": f"{dados.get('latency_ms')}ms" if dados.get("latency_ms") else "—",
                    # "saudavel" era o texto padrao de quem nao tinha detalhe —
                    # inclusive de quem tinha acabado de falhar 18 vezes. A
                    # coluna so fala quando tem o que dizer.
                    "motivo": (
                        f"em espera ({cooldown}s)" if cooldown
                        else "sem histórico" if not total
                        else dados.get("detail") or (
                            "" if not err else f"{err} falha{'s' if err > 1 else ''} até agora"
                        )
                    ),
                })
        except Exception:
            ordem = []

        base = str(request.base_url).rstrip("/")
        chamadas = sum((estado.get(n) or {}).get("ok", 0) + (estado.get(n) or {}).get("err", 0)
                       for n in nomes)
        return {
            "provedores": provedores,
            "ordem": ordem,
            "chamadas": chamadas,
            "estrategia": getattr(router, "_strategy", "adaptive"),
            # Com quem já chamou junto: a tela Conectar entregava a
            # configuração e parava aí, deixando "colei no lugar certo?" para o
            # primeiro erro dentro do agente — o pior lugar para descobrir.
            "ferramentas": _com_conexao(cli_tools.todas(base), clientes),
            "rodape": (
                "A fila segue o modo escolhido em Provedores. Saúde e cooldown "
                "continuam protegendo as chamadas em todos os modos."
            ),
        }

    @app.get("/logos/{arquivo}")
    async def logo(arquivo: str):
        """A arte dos provedores mora aqui, com o resto do que é deles.

        O Sentury servia essas imagens da própria pasta pública — e uma cópia
        por agente hospedeiro envelhece em ritmos diferentes. Quem sabe qual
        provedor existe é o RobinBandit.
        """
        from pathlib import Path as _Path

        from fastapi.responses import FileResponse

        nome = _Path(str(arquivo or "")).name
        if not nome or nome.startswith("."):
            raise HTTPException(status_code=404, detail="logo nao encontrada")
        base = pasta_das_logos()
        alvo = (base / nome).resolve()
        if base.resolve() not in alvo.parents or not alvo.is_file():
            raise HTTPException(status_code=404, detail="logo nao encontrada")
        return FileResponse(alvo)

    @app.get("/logos")
    async def logos() -> Dict[str, Any]:
        base = pasta_das_logos()
        if not base.is_dir():
            return {"logos": []}
        return {"logos": sorted(p.name for p in base.iterdir() if p.is_file())}

    @app.get("/config")
    async def ler_config() -> Dict[str, Any]:
        """O que dá para mudar sem editar arquivo.

        O RobinBandit roteia para qualquer agente, então a configuração dele
        mora aqui — não na tela de quem o hospeda.
        """
        from . import account_config

        catalogo = getattr(config, "providers", None) or {}
        na_cadeia = [getattr(p, "name", type(p).__name__) for p in providers]
        escolhida = account_config.cadeia() or na_cadeia
        tiers_escolhidos = account_config.overrides_de_tier()
        modelos_escolhidos = account_config.overrides_de_modelos()

        # Tier é um grupo: vários provedores em cada um. Quem está no tier 1 é
        # tentado antes; quem está no 2 só entra depois — ou concorre de igual
        # para igual, conforme a estratégia.
        provedores = []
        for nome in sorted(set(list(catalogo.keys()) + na_cadeia)):
            spec = catalogo.get(nome) or {}
            do_yaml = list(spec.get("models") or [])
            provedores.append({
                "nome": nome,
                "label": str(spec.get("label") or nome),
                # `ultra` e `ultra_max` batem no mesmo endpoint do OpenRouter
                # com outra chave: sao contas dele, e listar como provedor
                # separado faz parecer que ha tres OpenRouters.
                "conta_de": str(spec.get("conta_de") or ""),
                # Nao e provedor: e o aviso de que nenhum respondeu.
                "e_aviso": nome == "fallback",
                "tier": int(tiers_escolhidos.get(nome, spec.get("tier", 2))),
                "tier_do_yaml": int(spec.get("tier", 2)),
                "na_cadeia": nome in escolhida,
                "custo": str(spec.get("cost_class") or ""),
                "auth": str(spec.get("auth_type") or ("api_key" if spec.get("api_key_env") else "")),
                # A ordem dos modelos é a ordem de tentativa DENTRO do provedor:
                # "no Claude Code, tente Opus, depois Sonnet, depois Haiku".
                "modelos": modelos_escolhidos.get(nome) or do_yaml,
                "modelos_do_yaml": do_yaml,
                "modelos_proprios": bool(modelos_escolhidos.get(nome)),
            })

        from . import idioma as _idioma

        return {
            "idioma": _idioma.escolhido(),
            "idiomas": list(_idioma.IDIOMAS),
            "estrategia": account_config.estrategia(
                getattr(router, "_strategy", "adaptive")),
            "estrategias": {
                "adaptive": (
                    "Aprende com qualidade, saúde, latência e cota. O tier "
                    "ajuda, mas um provedor melhor pode passar na frente."
                ),
                "tier": (
                    "Esgota o tier 1 antes do 2 e o 2 antes do 3; dentro de "
                    "cada grupo, continua aprendendo."
                ),
                "fixed": (
                    "Segue a ordem exata da sua cadeia. Só passa ao próximo "
                    "quando o anterior está indisponível ou falha."
                ),
                "round_robin": (
                    "Alterna o primeiro provedor a cada tentativa concluída, "
                    "distribuindo a carga entre os disponíveis."
                ),
            },
            "tiers": {
                "1": "Prioridade alta",
                "2": "Prioridade normal",
                "3": "Reserva",
                # Existe para ser o último e não é destino de arrasto: mover
                # alguém para cá seria dizer "só use quando tudo falhar".
                "9": "Último recurso",
            },
            "provedores": provedores,
            "cadeia": escolhida,
        }

    @app.put("/config/estrategia")
    async def trocar_estrategia(payload: _Estrategia) -> Dict[str, Any]:
        from . import account_config

        try:
            escolhida = account_config.definir_estrategia(payload.valor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Vale no próximo `order()`, sem reiniciar: trocar de estratégia é uma
        # decisão que se toma no meio do dia, olhando a conta subir.
        router._strategy = escolhida
        return {"estrategia": escolhida}

    @app.put("/config/idioma")
    async def trocar_idioma(payload: _Idioma) -> Dict[str, Any]:
        """Em que língua o painel e a linha de comando respondem.

        A escolha é uma só para as duas interfaces: trocar no painel e continuar
        recebendo a CLI em outra língua seria configurar duas vezes a mesma
        coisa.
        """
        from . import idioma as _idioma

        try:
            escolhido = _idioma.definir(payload.valor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"idioma": escolhido}

    @app.put("/config/cadeia")
    async def trocar_cadeia(payload: _Cadeia) -> Dict[str, Any]:
        from . import account_config

        catalogo = getattr(config, "providers", None) or {}
        try:
            nova = account_config.definir_cadeia(payload.nomes, list(catalogo.keys()) or None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Reordenar quem já está montado vale imediatamente. Entrar com um
        # provedor que ainda não foi instanciado continua exigindo reinício.
        atuais = {getattr(p, "name", type(p).__name__): p for p in providers}
        ultimo = str(getattr(config, "last_resort", "") or "").strip().lower()
        ativos = [atuais[nome] for nome in nova if nome in atuais and nome != ultimo]
        if ultimo in atuais:
            ativos.append(atuais[ultimo])
        if ativos and isinstance(providers, list):
            providers[:] = ativos
        pendentes = [nome for nome in nova if nome not in atuais]
        return {
            "cadeia": nova,
            "aplicada_agora": [getattr(p, "name", type(p).__name__) for p in providers],
            "reiniciar_para": pendentes,
        }

    @app.put("/config/tier")
    async def trocar_tier(payload: _Tier) -> Dict[str, Any]:
        from . import account_config

        try:
            account_config.definir_tier_de_provedor(payload.provedor, payload.tier)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tiers": account_config.overrides_de_tier()}

    @app.put("/config/modelos")
    async def trocar_modelos(payload: _Modelos) -> Dict[str, Any]:
        """A ordem de tentativa dentro de um provedor.

        "No Claude Code, tente Opus; se não der, Sonnet; por último Haiku." É
        outra decisão que o tier não resolve: tier ordena provedores, isto
        ordena modelos.
        """
        from . import account_config

        try:
            escolhidos = account_config.definir_modelos_de_provedor(
                payload.provedor, payload.modelos)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"provedor": payload.provedor, "modelos": escolhidos}

    @app.get("/saldo")
    async def saldo() -> Dict[str, Any]:
        """Credito restante, onde o provedor informa. Nunca a chave."""
        from . import saldo as _saldo

        try:
            return {"contas": await _saldo.consultar(config)}
        except Exception as exc:
            return {"contas": [], "erro": f"{type(exc).__name__}"}

    @app.get("/contas")
    async def contas() -> Dict[str, Any]:
        """As contas de cada provedor, e como cada uma autentica.

        Uma conta pode ter várias chaves, e algumas não têm chave nenhuma: o
        Claude Code e o Codex autenticam pelo CLI oficial, que é dono da
        sessão. Listadas junto com as outras e sem essa distinção, elas
        apareciam como "sem chave" com o login funcionando.
        """
        from . import account_config
        from .accounts import catalogo_efetivo

        if config is None:
            return {"contas": [], "tiers": {}, "alvos": {}, "reforcado": []}
        painel = catalogo_efetivo(None, config).para_painel()
        rotulos = {
            chave: str(spec.get("label") or chave)
            for chave, spec in config.providers.items()
        }
        for conta in painel["contas"]:
            conta["provedor_label"] = rotulos.get(conta["provider"], conta["provider"])
        # Os modos pesados vinham de `selection_tier` num provedor `ultra` que
        # deixou de existir — virou conta do OpenRouter. Agora saem de onde a
        # informação de fato mora: o mapa tier→modelo do provedor, e o
        # tier→conta declarado.
        rotulos_de_tier = {"ultra": "Reforçado", "ultra_max": "Dedicado"}
        alvos: Dict[str, str] = {}
        for spec in config.providers.values():
            for tier in (spec.get("modelo_do_tier") or {}):
                alvos[str(tier)] = rotulos_de_tier.get(str(tier), str(tier))
        for tier in painel.get("tiers", {}):
            alvos.setdefault(str(tier), rotulos_de_tier.get(str(tier), str(tier)))
        painel["agent_mode"] = getattr(config, "agent_mode", "universal")
        # Dedicado pertence ao fluxo do Sentury e já tem interface lá. Repetir
        # o controle no painel do RobinBandit criava duas fontes de verdade.
        # Reforçado permanece porque é a seleção híbrida do núcleo.
        alvos = {tier: label for tier, label in alvos.items() if tier == "ultra"}
        painel["alvos"] = alvos
        ordem = account_config.ordem_do_reforcado()
        if not ordem and painel.get("tiers", {}).get("ultra"):
            ordem = [painel["tiers"]["ultra"]]
        painel["reforcado"] = ordem
        return painel

    @app.post("/contas")
    async def criar_conta(req: _Conta) -> Dict[str, Any]:
        """Declara outra conta do mesmo provedor, com nome próprio.

        Duas chaves do Groq não são dois Groqs: são duas contas, e o rotador
        alterna entre elas quando uma bate a cota.
        """
        from . import account_config

        try:
            return account_config.salvar_conta({
                "id": req.id, "provider": req.provedor, "key_env": req.variavel,
                "label": req.label, "paga": req.paga,
            })
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/contas/{conta_id}")
    async def apagar_conta(conta_id: str) -> Dict[str, Any]:
        """Tira a conta declarada. A chave dela continua no cofre até ser
        removida na mão: apagar as duas coisas de uma vez seria destrutivo
        demais para um clique."""
        from . import account_config

        return {"removida": account_config.remover_conta(conta_id)}

    @app.put("/contas/tier")
    async def apontar_tier(req: _TierDaConta) -> Dict[str, Any]:
        """Qual conta serve um tier de seleção (Reforçado, Dedicado).

        É o que separa "gaste a conta gratuita" de "pode gastar meu crédito".
        """
        from . import account_config
        from .accounts import catalogo_efetivo

        if config is None:
            raise HTTPException(status_code=400, detail="sem catalogo carregado")
        validos = [c.id for c in catalogo_efetivo(None, config).listar()]
        try:
            account_config.apontar_tier(req.tier, req.conta, ids_validos=validos)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tier": req.tier, "conta": req.conta}

    @app.put("/contas/reforcado")
    async def ordenar_reforcado(req: _OrdemDoReforcado) -> Dict[str, Any]:
        """Escolhe as contas tentadas, em ordem, antes da rota normal."""
        from . import account_config
        from .accounts import catalogo_efetivo

        if config is None:
            raise HTTPException(status_code=400, detail="sem catálogo carregado")
        validos = [c.id for c in catalogo_efetivo(None, config).listar()]
        try:
            ordem = account_config.definir_ordem_do_reforcado(
                req.contas, ids_validos=validos,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"contas": ordem}

    @app.get("/credenciais")
    async def credenciais() -> Dict[str, Any]:
        """Quais variáveis cada provedor espera, e se já estão preenchidas.

        O RobinBandit tem cofre próprio; quem o expunha era o agente
        hospedeiro. Sem esta rota, quem não usa um deles só conseguia
        configurar chave exportando variável de ambiente e reiniciando.

        Volta nome da variável, presença, origem e quantas chaves há. Nunca o
        valor — nem prefixo, nem sufixo: a dica é só o final, e só quando sobra
        o bastante para esconder.
        """
        import os

        from . import secrets as _secrets
        from .accounts import variaveis_conhecidas

        if config is None:
            return {"credenciais": [], "cofre": ""}
        # Agrupadas pelo provedor EFETIVO. `ultra` e `ultra_max` batem no mesmo
        # endpoint do OpenRouter com outra chave: são credenciais com nome, não
        # provedores, e listá-las à parte fazia parecer haver três OpenRouters.
        por_variavel: Dict[str, Dict[str, str]] = {}
        for chave, spec in config.providers.items():
            dono = str(spec.get("conta_de") or "").strip() or chave
            for campo in ("api_key_env", "api_key_fallback_env"):
                nome = str(spec.get(campo) or "").strip()
                if nome:
                    por_variavel.setdefault(nome, {
                        "provedor": dono,
                        "conta": chave if dono != chave else "",
                        "label": str(spec.get("label") or ""),
                    })

        saida = []
        for nome in variaveis_conhecidas(None, config):
            situacao = _secrets.situacao(nome, os.environ.get(nome, ""))
            situacao["variavel"] = nome
            situacao.update(por_variavel.get(nome) or {"provedor": "", "conta": "", "label": ""})
            saida.append(situacao)
        saida.sort(key=lambda linha: (linha["provedor"], linha["conta"], linha["variavel"]))
        return {"credenciais": saida, "cofre": str(_secrets.caminho_do_cofre())}

    @app.post("/credenciais")
    async def guardar_credencial(req: _Credencial) -> Dict[str, Any]:
        """Grava no cofre (0600), não no `.env` de ninguém.

        A lista branca vem do catálogo: variável que nenhum provedor declara
        não entra, senão um POST escreveria qualquer configuração.
        """
        import os

        from . import secrets as _secrets
        from .accounts import variaveis_conhecidas

        if config is None:
            raise HTTPException(status_code=400, detail="sem catalogo carregado")
        try:
            # A semente preserva o que o ambiente já tinha: sem ela, acrescentar
            # a terceira chave a uma variável com duas no ambiente deixaria a
            # conta com uma só, porque o cofre vence o ambiente.
            chaves = _secrets.guardar(
                req.variavel, req.valor,
                permitidos=variaveis_conhecidas(None, config),
                adicionar=req.adicionar,
                semente=os.environ.get(req.variavel, ""),
                rotulo=req.rotulo,
                paga=req.paga,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"variavel": req.variavel, "chaves": len(chaves), "reinicie": True}

    @app.post("/credenciais/importar")
    async def importar_do_ambiente() -> Dict[str, Any]:
        """Copia para o cofre do RobinBandit as chaves que só existem no ambiente.

        Sem isto, o RobinBandit depende do `.env` do agente que o hospeda: as
        chaves são dele, mas moravam no repositório do outro, e rodar o
        RobinBandit sozinho trazia metade dos provedores.

        O arquivo de origem não é tocado — nada é apagado, nada é reescrito.
        Variável que já está no cofre fica como está: o cofre é a palavra mais
        recente e sobrescrevê-la desfaria uma escolha feita aqui.
        """
        import os

        from . import secrets as _secrets
        from .accounts import variaveis_conhecidas

        if config is None:
            raise HTTPException(status_code=400, detail="sem catalogo carregado")
        trazidas, ja_tinha = [], []
        for nome in variaveis_conhecidas(None, config):
            if _secrets.listar(nome):
                ja_tinha.append(nome)
                continue
            valor = str(os.environ.get(nome) or "").strip()
            if not valor:
                continue
            try:
                _secrets.guardar(nome, valor, permitidos=variaveis_conhecidas(None, config))
                trazidas.append(nome)
            except ValueError:
                continue
        # Só os NOMES voltam. O valor não sai daqui nem em pedaço.
        return {"trazidas": trazidas, "ja_no_cofre": ja_tinha, "cofre": str(_secrets.caminho_do_cofre())}

    @app.put("/credenciais/{variavel}/{indice}")
    async def descrever_chave(variavel: str, indice: int, req: _RotuloDaChave) -> Dict[str, Any]:
        """Renomeia uma chave, ou marca que ela é crédito pago.

        Pela posição, nunca pelo valor: o valor não sai daqui, então é a
        posição e a dica que o painel conhece.
        """
        from . import secrets as _secrets

        ok = _secrets.descrever_chave(variavel, indice, rotulo=req.rotulo, paga=req.paga)
        if not ok:
            raise HTTPException(status_code=404, detail="chave nao encontrada")
        return {"ok": True}

    @app.delete("/credenciais/{variavel}/{indice}")
    async def remover_uma_chave(variavel: str, indice: int) -> Dict[str, Any]:
        """Índice em vez do valor: o valor nunca sai daqui, então o painel só
        conhece a posição e a dica."""
        from . import secrets as _secrets

        return {"removida": _secrets.remover_chave(variavel, indice)}

    @app.delete("/credenciais/{variavel}")
    async def remover_credencial(variavel: str) -> Dict[str, Any]:
        """Tira do cofre. O ambiente NÃO é tocado: se a variável veio do `.env`,
        ela continua valendo — remover do cofre não pode apagar o que o deploy
        configurou."""
        from . import secrets as _secrets

        return {"removida": _secrets.remover(variavel)}

    @app.get("/modelos/{provedor}")
    async def descobrir_modelos(provedor: str) -> Dict[str, Any]:
        """Modelos que o provedor diz ter, agora.

        Digitar o id do modelo a mao envelhece: o provedor aposenta um id e a
        cadeia so descobre quando falha.
        """
        from .model_catalog import fetch_model_catalog

        try:
            catalogo = await fetch_model_catalog(config, provedor)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}") from exc
        return catalogo

    @app.get("/janelas")
    async def janelas() -> Dict[str, Any]:
        """Quanto falta para o bloco de uso de cada assinatura virar.

        Assinatura não fica lenta quando acaba: ela para, e volta numa hora que
        dá para saber. O painel mostrava só o cooldown que o roteador chutou a
        partir do último erro, e a pergunta real — *quando posso usar de novo?*
        — não tinha resposta.
        """
        from . import janela, quota_ping

        if config is None:
            return {"janelas": [], "ping": quota_ping.configuracao()}
        return {"janelas": janela.resumo(config), "ping": quota_ping.configuracao()}

    @app.put("/janelas/ping")
    async def configurar_ping(req: _Ping) -> Dict[str, Any]:
        """Liga o ping de cota, que custa cota para medir cota.

        Vinha desligado e só mudava editando YAML — para uma opção que só faz
        sentido para quem tem assinatura, e que essa pessoa quer ligar olhando
        a janela, não reiniciando o processo.
        """
        from . import quota_ping

        atual = quota_ping.configuracao()
        quota_ping.configurar({
            "ativo": req.ativo if req.ativo is not None else atual["ativo"],
            "intervalo_s": req.intervalo_s if req.intervalo_s is not None else atual["intervalo_s"],
            "so_em_cooldown": (
                req.so_em_cooldown if req.so_em_cooldown is not None else atual["so_em_cooldown"]
            ),
        })
        return quota_ping.configuracao()

    @app.get("/historico")
    async def historico_por_dia(dias: int = 30) -> Dict[str, Any]:
        """Quem passou mais tempo no vermelho, e há quanto tempo foi.

        Um provedor bom que caiu um dia aparece com `dias_ruins: 1` e uptime
        alto — o bastante para não ser julgado pelo pior dia dele.
        """
        from . import historico as _historico

        # Fora daqui também: uptime do último recurso mede quantas vezes tudo
        # falhou, não a saúde de um provedor.
        ultimo = str(getattr(config, "last_resort", "") or "").strip().lower()
        nomes = [n for n in (getattr(p, "name", type(p).__name__) for p in providers) if n != ultimo]
        limite = max(1, min(int(dias or 30), _historico.DIAS_GUARDADOS))
        return {
            "dias": limite,
            "resumo": _historico.resumo(nomes, limite),
            "faixas": {nome: _historico.faixa(nome, limite) for nome in nomes},
        }

    @app.get("/uso")
    async def uso_de_tokens(dias: int = 365) -> Dict[str, Any]:
        """Tokens por dia e provedor, mais custo quando ele foi informado."""
        from . import uso as _uso

        limite = max(1, min(int(dias or 365), _uso.DIAS_GUARDADOS))
        return {
            "dias": limite,
            "calendario": _uso.calendario(limite),
            "por_provedor": _uso.por_provedor(min(limite, 30)),
            "mes": _uso.total(30),
            "total": _uso.total(limite),
        }

    @app.get("/diagnostico")
    async def diagnostico() -> Dict[str, Any]:
        """O que está errado na configuração, em português.

        O módulo existia e ninguém via: a pessoa descobria que faltava uma
        variável quando o provedor falhava no meio de um turno.
        """
        from .account_health import diagnosticar
        from .accounts import catalogo_efetivo

        if config is None:
            return {"achados": []}
        contas = catalogo_efetivo(None, config).para_painel()["contas"]
        try:
            return {"achados": diagnosticar(config, None, contas)}
        except Exception as exc:
            return {"achados": [], "erro": f"{type(exc).__name__}"}

    @app.get("/aprendizado")
    async def aprendizado() -> Dict[str, Any]:
        """O que o roteador mediu nesta máquina, e quando.

        Não vai para o repositório de jeito nenhum: foi medido com ESTAS
        chaves, neste plano, nesta região.
        """
        from . import estado as _estado

        guardado = _estado.carregar()
        return {
            "arquivo": str(_estado.caminho()),
            "tem": bool(guardado),
            "provedores": sorted(guardado or {}),
            "validade_dias": int(_estado.VALIDADE_S // 86400),
        }

    @app.delete("/aprendizado")
    async def esquecer_aprendizado() -> Dict[str, Any]:
        """Apaga o que foi medido. Para quando as chaves ou os planos mudaram e
        o que foi medido antes passou a descrever outro mundo."""
        from . import estado as _estado

        apagou = _estado.esquecer()
        router.reset()
        return {"esquecido": apagou}

    @app.get("/erros")
    async def tabela_de_erros() -> Dict[str, Any]:
        """Como o roteador reage ao erro de cada provedor.

        Tabela, não algoritmo: a redação da mensagem muda quando o provedor
        quer, e o tempo certo de espera muda por instalação e por plano.
        """
        from . import erros as _erros

        return {"cooldown_padrao": _erros.COOLDOWN_PADRAO, "regras": _erros.REGRAS_PADRAO}

    @app.get("/cli-tools")
    async def cli_tools_todas(request: Request) -> Dict[str, Any]:
        """Configuração pronta para cada CLI apontar para cá.

        Junto vai quem já chamou: copiar a configuração e não ter como saber se
        colou no lugar certo deixava a conferência para o primeiro erro dentro
        do agente, que é o pior lugar para descobrir.
        """
        from . import cli_tools

        ferramentas = _com_conexao(cli_tools.todas(str(request.base_url).rstrip("/")), clientes)
        conhecidos = {f["id"] for f in ferramentas}

        # Quem chamou sem casar com nenhuma ferramenta conhecida ainda conta:
        # é prova de que o endpoint está recebendo tráfego, e é como um padrão
        # de detecção errado aparece em vez de sumir.
        outros = [i for i in clientes.status() if i["id"] not in conhecidos]
        return {"ferramentas": ferramentas, "outros": outros}

    return app
