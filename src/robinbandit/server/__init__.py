"""Servidor OpenAI/Anthropic/Responses compatível do RobinBandit."""
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from ..api.clientes import Clientes as _Clientes
from pydantic import BaseModel, Field

from pathlib import Path

from ..routing.chain import ChainProvider


def pasta_das_logos() -> Path:
    """Pasta de logos empacotada junto do módulo."""
    return Path(__file__).resolve().parent.parent / "assets" / "providers"


# Limita respostas aguardando feedback.
_MAX_PENDENTES = 10_000


def _com_conexao(ferramentas: List[Dict[str, Any]], clientes) -> List[Dict[str, Any]]:
    """Anexa o status de conexão conhecido de cada ferramenta."""
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
    """Subset do protocolo Anthropic usado pelo Claude Code."""

    messages: List[Dict[str, Any]]
    model: Optional[str] = None
    system: Optional[Union[str, List[Dict[str, Any]]]] = None
    max_tokens: Optional[int] = None
    temperature: float = 0.2
    stream: bool = False


class _PedidoResponses(BaseModel):
    """Subset da Responses API usado pelo Codex CLI."""

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
    paga: bool = False
    modelos: List[str] = Field(default_factory=list)


class _TierDaConta(BaseModel):
    tier: str
    conta: str


class _OrdemDoReforcado(BaseModel):
    contas: List[str]


class _AlvoDoModo(BaseModel):
    conta: str
    modelos: List[str] = Field(default_factory=list)


class _SelecaoDoModo(BaseModel):
    alvos: List[_AlvoDoModo] = Field(default_factory=list)


class _Credencial(BaseModel):
    """O valor entra; nunca sai. Só o nome da variável volta nas respostas."""

    variavel: str
    valor: str
    # Por padrão, acrescenta sem substituir chaves existentes.
    adicionar: bool = True
    rotulo: str = ""
    paga: bool = False


class _Ping(BaseModel):
    ativo: Optional[bool] = None
    intervalo_s: Optional[float] = None
    so_em_cooldown: Optional[bool] = None


class _RotuloDaChave(BaseModel):
    rotulo: Optional[str] = None
    paga: Optional[bool] = None


def create_app(
    providers: List[Any], router, cache=None, config=None, activity=None,
    *,
    include_interface: bool = True,
    dependencies: Optional[List[Any]] = None,
) -> FastAPI:
    """Monta o app HTTP sobre os provedores e o router."""
    app = FastAPI(
        title="RobinBandit",
        dependencies=list(dependencies or []),
        docs_url="/docs" if include_interface else None,
        redoc_url="/redoc" if include_interface else None,
        openapi_url="/openapi.json" if include_interface else None,
    )
    # id da resposta -> (provedor, contexto), para /feedback.
    decisoes: "OrderedDict[str, tuple]" = OrderedDict()
    clientes = _Clientes()
    app.state.clientes = clientes
    from ..state.atividade import Atividade

    atividade = activity or Atividade()
    # Usado por testes/demos sem expor rota de escrita.
    app.state.atividade = atividade

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
        from ..providers import build_tier_provider
        from ..routing.selection import RouteSelection

        reforcado = build_tier_provider(config, "ultra")
        return [reforcado, *providers], RouteSelection.hybrid("ultra")

    @app.post("/v1/chat/completions")
    async def chat_completions(pedido: _Pedido, request: Request) -> Dict[str, Any]:
        if pedido.stream:
            raise HTTPException(400, "streaming não é suportado")

        contexto = pedido.model
        # Mesmo erro de provedor prova que a ferramenta chegou ao RobinBandit.
        clientes.anotar(request.headers.get("user-agent", ""), contexto)
        # Uma cadeia por request preserva last_provider sob concorrência.
        provedores_da_chamada, selecao = rota_da_chamada(request)
        chain = ChainProvider(provedores_da_chamada, router, cache=cache, activity=atividade)
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
        """Endpoint Anthropic usado pelo Claude Code."""
        from ..api import anthropic_api

        contexto = pedido.model
        clientes.anotar(request.headers.get("user-agent", ""), contexto)

        mensagens = anthropic_api.para_mensagens(pedido.messages, pedido.system)
        if not mensagens:
            raise HTTPException(400, "nenhuma mensagem de texto no pedido")

        provedores_da_chamada, selecao = rota_da_chamada(request)
        chain = ChainProvider(provedores_da_chamada, router, cache=cache, activity=atividade)
        try:
            texto = await chain.complete(
                mensagens, pedido.temperature, context=contexto, selection=selecao,
            )
        except RuntimeError as exc:
            # Mantém o envelope de erro esperado pela Anthropic.
            return JSONResponse(status_code=502, content=anthropic_api.erro(str(exc)))

        corpo = anthropic_api.resposta(texto, chain.last_model, chain.last_usage)
        if chain.last_provider:
            decisoes[corpo["id"]] = (chain.last_provider, contexto)
            while len(decisoes) > _MAX_PENDENTES:
                decisoes.popitem(last=False)

        if pedido.stream:
            # SSE compatível: resposta pronta em um único evento.
            return StreamingResponse(
                anthropic_api.eventos(corpo),
                media_type="text/event-stream",
            )
        return corpo

    @app.post("/v1/responses")
    async def responses(pedido: _PedidoResponses, request: Request) -> Any:
        """Responses API para clientes como Codex CLI."""
        from ..api import responses_api

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
        chain = ChainProvider(provedores_da_chamada, router, cache=cache, activity=atividade)
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
        """Fecha o loop de qualidade de uma resposta."""
        decisao = decisoes.pop(fb.id, None)
        if decisao is None:
            raise HTTPException(404, "id desconhecido ou já avaliado")
        provedor, contexto = decisao
        router.reward_quality(provedor, contexto, fb.good)
        return {"ok": True, "provider": provedor}

    @app.get("/v1/models")
    async def models() -> Dict[str, Any]:
        # Clientes que enumeram modelos esperam esta rota.
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

    async def painel_html() -> str:
        from ..ui.painel import PAGINA

        return PAGINA

    if include_interface:
        app.add_api_route(
            "/painel",
            painel_html,
            methods=["GET"],
            response_class=HTMLResponse,
        )

    @app.get("/painel/dados")
    async def painel_dados(request: Request) -> Dict[str, Any]:
        """Dados agregados que o painel desenha."""
        from ..ui import cli_tools

        estado = router.snapshot()
        todos = [getattr(p, "name", type(p).__name__) for p in providers]
        # O último recurso é aviso/fallback, não provedor competitivo.
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
                "ultimo_modelo": dados.get("last_model") or "",
                "ha_segundos": dados.get("seconds_ago"),
                "em_andamento": dados.get("inflight", 0),
                "rpm_restante": dados.get("rpm_remaining"),
                "rpd_restante": dados.get("rpd_remaining"),
                "rpm_usado": dados.get("rpm_used", 0),
            })

        # Ordem calculada pelo router.
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
                # Sem feedback explícito, usa saúde operacional.
                qualidade = dados.get("quality_mean")
                saude = dados.get("health_mean")
                # Sem chamada, o número ainda é prior do catálogo.
                estimado = not total
                ordem.append({
                    "nome": nome,
                    # Número cru para a barra do painel.
                    "qualidade_num": qualidade or saude or 0,
                    "estimado": estimado,
                    "qualidade": (
                        f"{(qualidade or saude):.2f} estimado" if estimado and (qualidade or saude)
                        else f"{qualidade:.2f}" if qualidade
                        else f"{saude:.2f} (saúde)" if saude else "—"
                    ),
                    "sucesso": f"{(ok / total * 100):.0f}%" if total else "—",
                    "latencia": f"{dados.get('latency_ms')}ms" if dados.get("latency_ms") else "—",
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
            "atividade": atividade.resumo(),
            "ferramentas": _com_conexao(cli_tools.todas(base), clientes),
            "rodape": (
                "A fila segue o modo escolhido em Provedores. Saúde e cooldown "
                "continuam protegendo as chamadas em todos os modos."
            ),
        }

    @app.get("/logos/{arquivo}")
    async def logo(arquivo: str):
        """Serve logos empacotadas dos provedores."""
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
        from ..accounts import account_config

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

        from ..ui import idioma as _idioma

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
        from ..accounts import account_config

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
        """Define o idioma do painel e da CLI."""
        from ..ui import idioma as _idioma

        try:
            escolhido = _idioma.definir(payload.valor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"idioma": escolhido}

    @app.put("/config/cadeia")
    async def trocar_cadeia(payload: _Cadeia) -> Dict[str, Any]:
        from ..accounts import account_config

        catalogo = getattr(config, "providers", None) or {}
        try:
            nova = account_config.definir_cadeia(payload.nomes, list(catalogo.keys()) or None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Provedores já instanciados podem ser reordenados imediatamente.
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
        from ..accounts import account_config

        try:
            account_config.definir_tier_de_provedor(payload.provedor, payload.tier)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tiers": account_config.overrides_de_tier()}

    @app.put("/config/modelos")
    async def trocar_modelos(payload: _Modelos) -> Dict[str, Any]:
        """Define a ordem de tentativa de modelos dentro de um provedor."""
        from ..accounts import account_config

        try:
            escolhidos = account_config.definir_modelos_de_provedor(
                payload.provedor, payload.modelos)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Persistir sem atualizar a instancia deixava o painel dizer que a
        # mudanca foi feita, mas o processo continuava usando os modelos
        # anteriores ate reiniciar. Lista vazia remove o override e restaura o
        # catalogo base imediatamente.
        efetivos = escolhidos
        if not efetivos and config is not None:
            efetivos = config.provider_models(payload.provedor)
        aplicados = []
        alvo = str(payload.provedor or "").strip().lower()
        for provider in providers:
            nome = str(getattr(provider, "name", "") or "").strip().lower()
            if nome != alvo or not hasattr(provider, "models"):
                continue
            provider.models = list(efetivos)
            aplicados.append(nome)
        return {
            "provedor": payload.provedor,
            "modelos": escolhidos,
            "modelos_efetivos": efetivos,
            "aplicada_agora": bool(aplicados),
        }

    @app.get("/saldo")
    async def saldo() -> Dict[str, Any]:
        """Credito restante, onde o provedor informa. Nunca a chave."""
        from ..catalog import saldo as _saldo

        try:
            return {"contas": await _saldo.consultar(config)}
        except Exception as exc:
            return {"contas": [], "erro": f"{type(exc).__name__}"}

    @app.get("/contas")
    async def contas() -> Dict[str, Any]:
        """Contas de cada provedor e seus métodos de autenticação."""
        from ..accounts import account_config
        from ..accounts import catalogo_efetivo

        if config is None:
            return {
                "contas": [], "tiers": {}, "alvos": {}, "reforcado": [],
                "selecoes": {"reforcado": [], "dedicado": []},
            }
        painel = catalogo_efetivo(None, config).para_painel()
        rotulos = {
            chave: str(spec.get("label") or chave)
            for chave, spec in config.providers.items()
        }
        for conta in painel["contas"]:
            conta["provedor_label"] = rotulos.get(conta["provider"], conta["provider"])
        # Alvos de modo vêm do mapa tier->modelo e do tier->conta declarado.
        rotulos_de_tier = {"ultra": "Reforçado", "ultra_max": "Dedicado"}
        alvos: Dict[str, str] = {}
        for spec in config.providers.values():
            for tier in (spec.get("modelo_do_tier") or {}):
                alvos[str(tier)] = rotulos_de_tier.get(str(tier), str(tier))
        for tier in painel.get("tiers", {}):
            alvos.setdefault(str(tier), rotulos_de_tier.get(str(tier), str(tier)))
        painel["agent_mode"] = getattr(config, "agent_mode", "universal")
        # Dedicado é fluxo do Sentury; o painel universal mantém só Reforçado.
        alvos = {tier: label for tier, label in alvos.items() if tier == "ultra"}
        painel["alvos"] = alvos
        ordem = account_config.ordem_do_reforcado()
        if not ordem and painel.get("tiers", {}).get("ultra"):
            ordem = [painel["tiers"]["ultra"]]
        painel["reforcado"] = ordem
        painel["selecoes"] = {
            modo: account_config.selecao_do_modo(modo)
            for modo in ("reforcado", "dedicado")
        }
        return painel

    @app.post("/contas")
    async def criar_conta(req: _Conta) -> Dict[str, Any]:
        """Declara outra conta do mesmo provedor."""
        from ..accounts import account_config

        try:
            return account_config.salvar_conta({
                "id": req.id, "provider": req.provedor, "key_env": req.variavel,
                "label": req.label, "paga": req.paga, "models": req.modelos,
            })
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/contas/{conta_id}")
    async def apagar_conta(conta_id: str) -> Dict[str, Any]:
        """Remove a conta declarada, sem apagar a chave do cofre."""
        from ..accounts import account_config

        return {"removida": account_config.remover_conta(conta_id)}

    @app.put("/contas/tier")
    async def apontar_tier(req: _TierDaConta) -> Dict[str, Any]:
        """Define qual conta atende um tier de seleção."""
        from ..accounts import account_config
        from ..accounts import catalogo_efetivo

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
        """Compatibilidade do painel universal.

        As contas são ordenadas aqui, mas os modelos precisam ter sido
        escolhidos antes na tela de Modelos. Nada é inferido por fábrica.
        """
        from ..accounts import account_config
        from ..accounts import catalogo_efetivo

        if config is None:
            raise HTTPException(status_code=400, detail="sem catálogo carregado")
        catalogo = catalogo_efetivo(None, config)
        validos = [c.id for c in catalogo.listar()]
        try:
            ordem = account_config.definir_ordem_do_reforcado(
                req.contas, ids_validos=validos,
            )
            escolhidos = account_config.overrides_de_modelos()
            alvos = []
            for conta_id in ordem:
                conta = catalogo.obter(conta_id)
                modelos = list(escolhidos.get(conta.provider, [])) if conta else []
                if not modelos and conta is not None:
                    modelos = list(conta.models)
                alvos.append({"conta": conta_id, "modelos": modelos})
            account_config.definir_selecao_do_modo(
                "reforcado", alvos, ids_validos=validos,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"contas": ordem}

    @app.put("/contas/modos/{modo}")
    async def selecionar_modo(
        modo: str, req: _SelecaoDoModo,
    ) -> Dict[str, Any]:
        """Escolhe contas/provedores e modelos de Reforçado ou Dedicado.

        Dedicado é consumido pelo Sentury e não aparece como modo no painel
        universal do RobinBandit.
        """
        from ..accounts import account_config
        from ..accounts import catalogo_efetivo

        if config is None:
            raise HTTPException(status_code=400, detail="sem catálogo carregado")
        validos = [c.id for c in catalogo_efetivo(None, config).listar()]
        try:
            alvos = account_config.definir_selecao_do_modo(
                modo,
                [alvo.model_dump() for alvo in req.alvos],
                ids_validos=validos,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"modo": modo, "alvos": alvos}

    @app.get("/credenciais")
    async def credenciais() -> Dict[str, Any]:
        """Lista variáveis esperadas e presença no cofre/ambiente."""
        import os

        from ..accounts import secrets as _secrets
        from ..accounts import variaveis_conhecidas

        if config is None:
            return {"credenciais": [], "cofre": ""}
        # Agrupa credenciais pelo provedor efetivo.
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
        """Grava no cofre local, validando contra o catálogo."""
        import os

        from ..accounts import secrets as _secrets
        from ..accounts import variaveis_conhecidas

        if config is None:
            raise HTTPException(status_code=400, detail="sem catalogo carregado")
        try:
            # Preserva chaves já vindas do ambiente ao criar o cofre.
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
        """Copia para o cofre chaves presentes só no ambiente."""
        import os

        from ..accounts import secrets as _secrets
        from ..accounts import variaveis_conhecidas

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
        return {"trazidas": trazidas, "ja_no_cofre": ja_tinha, "cofre": str(_secrets.caminho_do_cofre())}

    @app.put("/credenciais/{variavel}/{indice}")
    async def descrever_chave(variavel: str, indice: int, req: _RotuloDaChave) -> Dict[str, Any]:
        """Renomeia uma chave ou marca crédito pago."""
        from ..accounts import secrets as _secrets

        ok = _secrets.descrever_chave(variavel, indice, rotulo=req.rotulo, paga=req.paga)
        if not ok:
            raise HTTPException(status_code=404, detail="chave nao encontrada")
        return {"ok": True}

    @app.delete("/credenciais/{variavel}/{indice}")
    async def remover_uma_chave(variavel: str, indice: int) -> Dict[str, Any]:
        """Remove uma chave pelo índice."""
        from ..accounts import secrets as _secrets

        return {"removida": _secrets.remover_chave(variavel, indice)}

    @app.delete("/credenciais/{variavel}")
    async def remover_credencial(variavel: str) -> Dict[str, Any]:
        """Remove do cofre sem tocar no ambiente."""
        from ..accounts import secrets as _secrets

        return {"removida": _secrets.remover(variavel)}

    @app.get("/modelos/{provedor}")
    async def descobrir_modelos(provedor: str) -> Dict[str, Any]:
        """Modelos que o provedor informa no momento."""
        from ..catalog.model_catalog import fetch_model_catalog

        try:
            catalogo = await fetch_model_catalog(config, provedor)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}") from exc
        return catalogo

    @app.get("/janelas")
    async def janelas() -> Dict[str, Any]:
        """Janelas de uso dos provedores de assinatura."""
        from ..state import janela; from ..catalog import quota_ping

        if config is None:
            return {"janelas": [], "ping": quota_ping.configuracao()}
        return {"janelas": janela.resumo(config), "ping": quota_ping.configuracao()}

    @app.put("/janelas/ping")
    async def configurar_ping(req: _Ping) -> Dict[str, Any]:
        """Configura a sonda opcional de cota."""
        from ..catalog import quota_ping

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
        """Histórico diário de estabilidade por provedor."""
        from ..state import historico as _historico

        # Exclui o último recurso do uptime de provedores.
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
        from ..state import uso as _uso

        limite = max(1, min(int(dias or 365), _uso.DIAS_GUARDADOS))
        return {
            "dias": limite,
            "calendario": _uso.calendario(limite),
            "por_provedor": _uso.por_provedor(limite),
            "periodo": _uso.total(limite),
            "mes": _uso.total(30),
            "total": _uso.total(limite),
        }

    @app.get("/diagnostico")
    async def diagnostico() -> Dict[str, Any]:
        """Diagnóstico legível da configuração."""
        from ..accounts.account_health import diagnosticar
        from ..accounts import catalogo_efetivo

        if config is None:
            return {"achados": []}
        contas = catalogo_efetivo(None, config).para_painel()["contas"]
        try:
            return {"achados": diagnosticar(config, None, contas)}
        except Exception as exc:
            return {"achados": [], "erro": f"{type(exc).__name__}"}

    @app.get("/aprendizado")
    async def aprendizado() -> Dict[str, Any]:
        """Estado do aprendizado local do roteador."""
        from ..state import estado as _estado

        guardado = _estado.carregar()
        return {
            "arquivo": str(_estado.caminho()),
            "tem": bool(guardado),
            "provedores": sorted(guardado or {}),
            "validade_dias": int(_estado.VALIDADE_S // 86400),
        }

    @app.delete("/aprendizado")
    async def esquecer_aprendizado() -> Dict[str, Any]:
        """Apaga o aprendizado local."""
        from ..state import estado as _estado

        apagou = _estado.esquecer()
        router.reset()
        return {"esquecido": apagou}

    @app.get("/erros")
    async def tabela_de_erros() -> Dict[str, Any]:
        """Tabela ativa de classificação de erros."""
        from ..routing import erros as _erros

        return {"cooldown_padrao": _erros.COOLDOWN_PADRAO, "regras": _erros.REGRAS_PADRAO}

    @app.get("/cli-tools")
    async def cli_tools_todas(request: Request) -> Dict[str, Any]:
        """Configuração pronta para cada CLI apontar para cá."""
        from ..ui import cli_tools

        ferramentas = _com_conexao(cli_tools.todas(str(request.base_url).rstrip("/")), clientes)
        conhecidos = {f["id"] for f in ferramentas}

        # Mantém User-Agents desconhecidos visíveis como "outros".
        outros = [i for i in clientes.status() if i["id"] not in conhecidos]
        return {"ferramentas": ferramentas, "outros": outros}

    return app
