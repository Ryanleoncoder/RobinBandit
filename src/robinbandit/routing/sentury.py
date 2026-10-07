import asyncio
import contextvars
import hashlib
import inspect
import logging
import time
from collections import OrderedDict
from typing import Callable, Dict, List, Optional

from ..catalog.profiles import preferred_model_for

logger = logging.getLogger(__name__)

_kwargs_cache: Dict[object, Optional[set]] = {}


def _accepted_kwargs(func) -> Optional[set]:
    """Nomes de kwargs que o `complete` do provedor aceita. None = aceita
    qualquer um (**kwargs). Evita descobrir isso por TypeError a cada chamada."""
    # A função da classe, não o método ligado: o ligado é recriado a cada acesso
    # e seu id() seria reciclado pelo GC (cacharia a assinatura errada).
    chave = getattr(func, "__func__", func)
    if chave not in _kwargs_cache:
        try:
            params = inspect.signature(func).parameters
        except (TypeError, ValueError):
            _kwargs_cache[chave] = None
            return None
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            _kwargs_cache[chave] = None
        else:
            _kwargs_cache[chave] = set(params)
    return _kwargs_cache[chave]


# --- Seleção Reforçado/Dedicado (ids legados Ultra/Ultra Max) ---
# O provedor selecionado do request atual vive num contextvar (isolado por request no
# contexto async — asyncio.create_task copia o contexto, então o /chat/stream
# também herda). Quando presente, o ChainProvider o tenta ANTES da cadeia normal
# e, se ele falhar (timeout/erro/sem crédito), cascateia pro fallback de sempre.
_ultra_provider_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "sentury_ultra_provider", default=None
)
_ultra_classify_provider_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "sentury_ultra_classify_provider", default=None
)

# No modo Máxima, classificação e roteamento usam opções gratuitas.
# Este contexto reserva Ultra para planejamento e resposta.
_suppress_ultra_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "sentury_suppress_ultra", default=False
)


class no_ultra:
    """Context manager: suprime o alvo fixo e usa o Router neste trecho.

    Mantém compatibilidade com o nome interno legado; é usado quando uma etapa
    auxiliar não deve consumir a conta reservada do Reforçado/Dedicado.
    """

    def __enter__(self):
        self._prev = _suppress_ultra_ctx.get()
        _suppress_ultra_ctx.set(True)
        return self

    def __exit__(self, *exc):
        _suppress_ultra_ctx.set(self._prev)
        return False


def is_ultra_active() -> bool:
    """True se Reforçado ou Dedicado está ativo NESTE request."""
    return _ultra_provider_ctx.get() is not None


def active_ultra_tier() -> Optional[str]:
    """Id legado da seleção ativa: 'ultra' (Reforçado), 'ultra_max' (Dedicado),
    ou None no Router. O provedor vive no contextvar (herdado pela task do
    turno), então funciona em qualquer ponto do fluxo. Usado pela telemetria de
    intervenção/latência pra comparar os tiers."""
    prov = _ultra_provider_ctx.get()
    if prov is None:
        return None
    return getattr(prov, "name", None)


def ultra_capabilities() -> Optional[set]:
    """O que a conta escolhida do request faz (`vision`, ...), ou None no
    Router. Quem manda imagem pergunta isto para saber se a conta vê."""
    prov = _ultra_provider_ctx.get()
    if prov is None:
        return None
    return _capacidades(None, prov)


def _capacidades(router, provider) -> set:
    medir = getattr(router, "capabilities_of", None)
    if callable(medir):
        try:
            return set(medir(provider))
        except Exception:
            pass
    proprias = getattr(provider, "capabilities", None) or ()
    if isinstance(proprias, str):
        proprias = [proprias]
    if not isinstance(proprias, (list, tuple, set, frozenset)):
        return set()
    return {str(c).strip().lower() for c in proprias if str(c).strip()}


# A descrição de uma imagem para a conta do Dedicado que não enxerga. Um turno
# chama a cadeia várias vezes com o mesmo histórico: sem guardar, a mesma
# imagem seria descrita a cada chamada.
_DESCRICOES: "OrderedDict[str, str]" = OrderedDict()
_DESCRICOES_TETO = 32
_PEDIDO_DE_DESCRICAO = (
    "Outro modelo vai responder a pessoa sem ver as imagens abaixo; você é os olhos dele. Descreva cada "
    "imagem com fidelidade: o que é, todo texto legível (transcrito), números, tabelas, código, gráficos, "
    "rostos e objetos, cores e posição quando importarem. Não responda o pedido da pessoa, só descreva o "
    "que ajuda a responder. Não invente o que não aparece; se algo estiver ilegível, diga."
)


def _imagens_da_mensagem(mensagem: Dict) -> List[str]:
    urls = [str((i or {}).get("data_url") or "") for i in (mensagem.get("imagens") or [])]
    conteudo = mensagem.get("content")
    if isinstance(conteudo, list):
        for parte in conteudo:
            if isinstance(parte, dict) and str(parte.get("type") or "").startswith("image"):
                url = (parte.get("image_url") or {}).get("url") if isinstance(parte.get("image_url"), dict) \
                    else parte.get("image_url") or parte.get("url")
                urls.append(str(url or ""))
    return [u for u in urls if u]


def _texto_da_mensagem(mensagem: Dict) -> str:
    conteudo = mensagem.get("content")
    if isinstance(conteudo, list):
        return "\n".join(str(p.get("text") or "") for p in conteudo
                         if isinstance(p, dict) and p.get("type") == "text").strip()
    return str(conteudo or "")


def use_ultra_provider(provider):
    """Ativa o modo Ultra para o request atual. Devolve um token; passe-o para
    clear_ultra_provider() no finally. `provider` deve ter a mesma interface dos
    demais (async complete + atributo name/last_model)."""
    return _ultra_provider_ctx.set(provider)


def use_ultra_classify_provider(provider):
    """Ativa um provedor Ultra leve apenas para chamadas CLASSIFY neste request."""
    return _ultra_classify_provider_ctx.set(provider)


def clear_ultra_provider(token) -> None:
    try:
        _ultra_provider_ctx.reset(token)
    except (ValueError, LookupError):
        # token de outro contexto (ex.: task filha) — ignorar é seguro.
        pass


def clear_ultra_classify_provider(token) -> None:
    try:
        _ultra_classify_provider_ctx.reset(token)
    except (ValueError, LookupError):
        pass


from .chain import ChainProvider as _ChainBase, FalhaDaCadeia, _somar as _somar_uso
from .chain import anotar_resposta as _anotar_resposta
from .chain import classify_error, grude_da_conversa, _anotar_o_gasto, _grudar, _soltar, _RECUSAS_DO_TURNO
from .erros import da_requisicao, transitorio

_exigencias = _ChainBase.exigencias
_para_provedor = _ChainBase.para_provedor


class ChainProvider:
    """Encadeia provedores de LLM e tenta cada um até um responder. O
    FallbackProvider nunca lança exceção, então deixá-lo por último garante que
    o chat nunca quebra por falha de LLM. Nenhuma regra do Harness depende de
    qual provedor respondeu.

    A ORDEM não é mais fixa: o provider_router reordena a cada request por
    saúde + latência + qualidade-por-complexidade (Fases 2-4) e joga quem está
    em cooldown pro fim (Fase 1). Num 429, faz UM retry curto no mesmo provedor
    (agora há muitos atrás dele) antes de cascatear."""

    _RATE_LIMIT_RETRIES = 1
    _RATE_LIMIT_BACKOFF = 1.5  # segundos

    def __init__(self, providers: List, router=None,
                 active_effort: Optional[Callable[[], Optional[str]]] = None,
                 provider_effort_for: Optional[Callable[..., Optional[str]]] = None):
        self.providers = [p for p in providers if p is not None]
        if not self.providers:
            raise ValueError("ChainProvider precisa de pelo menos um provedor")
        if router is None:
            from ..config import RobinConfig
            from ..gateway import RobinGateway
            names = {
                getattr(provider, "name", type(provider).__name__): {}
                for provider in self.providers
            }
            routing = {}
            if "fallback" in names:
                routing["last_resort"] = "fallback"
            router = RobinGateway(RobinConfig.from_mapping({
                "providers": names,
                "routing": routing,
            }))
        self.router = router
        self._active_effort = active_effort or (lambda: None)
        self._provider_effort_for = provider_effort_for or (lambda level, mode=None: level)
        self._last_model_ctx = contextvars.ContextVar(
            f"chain_last_model_{id(self)}", default=None
        )
        self._last_provider_ctx = contextvars.ContextVar(
            f"chain_last_provider_{id(self)}", default=None
        )
        self._last_reasoning_ctx = contextvars.ContextVar(
            f"chain_last_reasoning_{id(self)}", default=None
        )
        self._last_tools_ctx = contextvars.ContextVar(
            f"chain_last_tools_{id(self)}", default=None
        )
        self._preferred_model_ctx = contextvars.ContextVar(
            f"chain_preferred_model_{id(self)}", default=None
        )

    @property
    def last_model(self):
        return self._last_model_ctx.get()

    @last_model.setter
    def last_model(self, value):
        self._last_model_ctx.set(value)

    @property
    def last_provider(self):
        return self._last_provider_ctx.get()

    @last_provider.setter
    def last_provider(self, value):
        self._last_provider_ctx.set(value)

    @property
    def last_reasoning_summary(self):
        return self._last_reasoning_ctx.get()

    @last_reasoning_summary.setter
    def last_reasoning_summary(self, value):
        self._last_reasoning_ctx.set(value)

    @property
    def last_tool_calls(self):
        return self._last_tools_ctx.get()

    @last_tool_calls.setter
    def last_tool_calls(self, value):
        self._last_tools_ctx.set(value)

    @property
    def supports_tools(self) -> bool:
        """Se QUEM VAI RESPONDER devolve chamada estruturada.

        O `complete` desta cadeia sempre tem `tools=`, entao a assinatura dizia
        sim para qualquer turno. Com uma conta escolhida no painel e ela que
        responde, e a resposta tem de ser a dela: o Claude Code no Dedicado
        caia no passo unico e o plano em texto virava resposta final."""
        from .chain import suporta_ferramentas

        escolhido = _ultra_provider_ctx.get()
        if escolhido is not None and not _suppress_ultra_ctx.get():
            return suporta_ferramentas(escolhido)
        return any(suporta_ferramentas(p) for p in self.providers)

    @property
    def preferred_model_override(self):
        return self._preferred_model_ctx.get()

    @preferred_model_override.setter
    def preferred_model_override(self, value):
        self._preferred_model_ctx.set(value)

    async def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2,
                       complexity: Optional[str] = None, profile: Optional[str] = None,
                       tools: Optional[list] = None) -> str:
        # Não existe cache de resposta aqui, e é de propósito. Um turno de
        # análise lê dado que muda: devolver a resposta guardada da mesma
        # pergunta entrega número velho com cara de número novo, e o trace
        # ainda diz que o modelo pensou. Se voltar a fazer sentido, precisa
        # nascer com invalidação por dado, não por texto de entrada.
        ultra = _ultra_provider_ctx.get()
        ultra_active = ultra is not None
        last_error = None
        self.last_model = None
        self.last_usage = None
        self.last_provider = None
        self.last_reasoning_summary = None
        self.last_tool_calls = None  # native function-calling (A2b), se `tools=` fornecido
        # Effort do request (barra/Auto/deliberate) traduzido pro que o provedor
        # entende. Classify tem regra própria (sem raciocínio) e fica de fora.
        nivel = None if (complexity or "").upper() == "CLASSIFY" else self._active_effort()
        efforce = self._provider_effort_for(nivel, mode=getattr(ultra, "name", None))
        candidates = [
            provider for provider in self.providers
            if getattr(provider, "name", type(provider).__name__) not in {"ultra", "ultra_max"}
        ]
        route_selection = None
        selected = None
        # Os três modos são políticas do Robin, não uma reordenação paralela do
        # Harness. Reforçado = hybrid; Dedicado = strict; ausência = Router.
        if ultra_active:
            classify_ultra = _ultra_classify_provider_ctx.get()
            selected = (
                classify_ultra or ultra
                if (complexity or "").upper() == "CLASSIFY"
                else ultra
            )
            candidates = [selected] + [p for p in candidates if p is not selected]
            selected_name = getattr(selected, "name", type(selected).__name__)
            selected_models = list(getattr(selected, "models", []) or [])
            target = selected_name
            if selected_models:
                target = f"{target}:{selected_models[0]}"
            mode = "dedicado" if getattr(ultra, "name", None) == "ultra_max" else "reforçado"
            selector = getattr(self.router, "selection", None)
            route_selection = selector(mode, target) if callable(selector) else None
        else:
            selector = getattr(self.router, "selection", None)
            route_selection = selector("router") if callable(selector) else None

        override = getattr(self, "preferred_model_override", None)
        if override and not ultra_active:
            selector = getattr(self.router, "selection", None)
            route_selection = selector("reforçado", override) if callable(selector) else None

        # Dedicado com imagem e a conta escolhida não enxerga: o Router tiraria
        # a conta do turno e, estrito, ninguém responderia. Quem enxerga no
        # Router descreve a imagem e a resposta continua sendo da conta.
        exigidas = _exigencias(messages)
        if (exigidas and selected is not None and getattr(route_selection, "mode", None) == "strict"
                and not exigidas <= _capacidades(self.router, selected)):
            messages = await self._descrever_imagens(
                messages, [p for p in candidates if p is not selected], complexity, profile,
            )

        try:
            ordered = self.router.order(
                candidates, complexity, profile=profile, selection=route_selection,
                requires=_exigencias(messages),
            )
        except TypeError:
            # Compatibilidade para routers duck-typed antigos usados por agentes
            # universais; o runtime Sentury sempre usa RobinGateway.
            ordered = self.router.order(candidates, complexity, profile=profile)

        if not ordered and _exigencias(messages):
            raise RuntimeError("Nenhum provedor configurado consegue ler imagem neste turno.")
        if not ordered:
            raise RuntimeError("Nenhum provedor de LLM permitido para este modo")

        messages = _para_provedor(messages)

        # Se houver override do modelo preferido (ex: sincronização de Planner e Responder)
        pref_name = None
        override_model = None
        if override:
            parts = override.split(":", 1)
            pref_name = parts[0]
            if len(parts) > 1:
                override_model = parts[1]
            matching_providers = [p for p in ordered if getattr(p, "name", type(p).__name__) == pref_name]
            if matching_providers:
                if ultra_active and pref_name != "ultra":
                    ultra_items = [p for p in ordered if getattr(p, "name", type(p).__name__) == "ultra"]
                    matching_non_ultra = [
                        p for p in matching_providers
                        if getattr(p, "name", type(p).__name__) != "ultra"
                    ]
                    rest = [
                        p for p in ordered
                        if p not in ultra_items and p not in matching_non_ultra
                    ]
                    ordered = ultra_items + matching_non_ultra + rest
                else:
                    non_matching = [p for p in ordered if getattr(p, "name", type(p).__name__) != pref_name]
                    ordered = matching_providers + non_matching

        # No Router livre, a conversa continua com quem respondeu da última vez:
        # trocar de modelo a cada turno muda o tom e o formato no meio da conversa.
        livre = not ultra_active and not override
        grude = grude_da_conversa() if livre else None
        if grude:
            ordered = sorted(ordered, key=lambda p: getattr(p, "name", type(p).__name__) != grude[0])
        tipos_das_falhas: List[str] = []

        for provider in ordered:

            pname = getattr(provider, "name", type(provider).__name__)

            # Modelo preferido do perfil PARA este provedor (ex.: coding+gemini →
            # antigravity). None fora de perfil = comportamento de hoje.
            if override_model and pname == pref_name:
                pref = override_model
            elif route_selection and pname == route_selection.provider and route_selection.model:
                pref = route_selection.model
            elif grude and pname == grude[0] and grude[1] in (getattr(provider, "models", None) or []):
                pref = grude[1]
            else:
                pref = preferred_model_for(profile, pname)
            order_models = getattr(self.router, "order_models", None)
            if callable(order_models) and getattr(provider, "models", None):
                ranked_models = order_models(
                    pname, list(provider.models), complexity, profile,
                    preferred_model=pref,
                    strict=bool(
                        route_selection and route_selection.mode == "strict"
                        and pname == route_selection.provider
                    ),
                )
                if ranked_models:
                    pref = ranked_models[0]
            for tentativa in range(self._RATE_LIMIT_RETRIES + 1):
                inicio = time.perf_counter()
                begin = getattr(self.router, "begin", None)
                end = getattr(self.router, "end", None)
                if callable(begin):
                    begin(pname)
                try:
                    # Só manda o que o provedor aceita: `tools` e `reasoning_effort`
                    # são opcionais e nem todo provider os implementa.
                    aceitos = _accepted_kwargs(provider.complete)
                    extras = {"complexity": complexity, "preferred_model": pref,
                              "strict_model": bool(
                                  route_selection and route_selection.mode == "strict"
                                  and pname == route_selection.provider
                              ),
                              "tools": tools or None, "reasoning_effort": efforce}
                    kwargs = {k: v for k, v in extras.items()
                              if v is not None and (aceitos is None or k in aceitos)}
                    try:
                        result = await provider.complete(messages, temperature, **kwargs)
                    except TypeError:
                        # Provedor com assinatura fora do padrão — degrada pro mínimo.
                        result = await provider.complete(messages, temperature)
                    latency_ms = (time.perf_counter() - inicio) * 1000.0
                    self.last_model = getattr(provider, "last_model", type(provider).__name__)
                    self.last_provider = getattr(provider, "last_provider", None) or pname
                    # Tokens do provedor que respondeu, somados no turno.
                    self.last_usage = getattr(provider, "last_usage", None)
                    _somar_uso(self.last_usage)
                    _anotar_o_gasto(self.last_provider, self.last_usage)
                    self.last_reasoning_summary = getattr(provider, "last_reasoning_summary", None)
                    self.last_tool_calls = getattr(provider, "last_tool_calls", None)
                    record_model_failure = getattr(self.router, "record_model_failure", None)
                    if callable(record_model_failure):
                        for failed_model in dict.fromkeys(getattr(provider, "model_failures", []) or []):
                            record_model_failure(pname, failed_model)
                    self.router.record_success(
                        pname, latency_ms, model=self.last_model,
                        complexity=complexity, profile=profile,
                    )
                    if livre:
                        _grudar(pname, self.last_model)
                    # Fase 5 — cota (quando o provedor expõe no header da resposta).
                    quota = getattr(provider, "last_quota", None)
                    if isinstance(quota, dict):
                        self.router.record_quota(pname, quota.get("rpm"), quota.get("rpd"))
                    # O unico ponto por onde TODA resposta do turno passa. Ver
                    # `chain.anotar_resposta`: sem `tool_calls` aqui, repetir um
                    # turno nativo mediria o vazio.
                    _anotar_resposta(
                        texto=result,
                        tool_calls=self.last_tool_calls,
                        modelo=self.last_model,
                        provedor=self.last_provider,
                        complexidade=complexity,
                        perfil=profile,
                        ms=int(latency_ms),
                    )
                    return result
                except Exception as exc:
                    last_error = exc
                    record_model_failure = getattr(self.router, "record_model_failure", None)
                    failed_models = list(dict.fromkeys(getattr(provider, "model_failures", []) or []))
                    if callable(record_model_failure):
                        for failed_model in failed_models:
                            record_model_failure(pname, failed_model)
                    tipo = classify_error(exc)
                    if transitorio(tipo) and tentativa < self._RATE_LIMIT_RETRIES:
                        espera = self._RATE_LIMIT_BACKOFF * (tentativa + 1)
                        logger.warning("Provedor %s com falha passageira (%s); aguardando %.1fs e 1 retry...",
                                       pname, tipo, espera)
                        await asyncio.sleep(espera)
                        continue
                    tipos_das_falhas.append(tipo)
                    _soltar(pname)
                    if tipo == "content_policy":
                        recusas = _RECUSAS_DO_TURNO.get()
                        if recusas is not None:
                            recusas.append({"provedor": pname, "modelo": getattr(exc, "modelo", None)
                                            or getattr(provider, "last_attempted_model", None)})
                    if da_requisicao(tipo):
                        # O pedido não cabe ou não passa aqui, e outro provedor pode
                        # aceitar. Castigar este ensinaria o roteador a desconfiar
                        # de um provedor bom para o próximo pedido normal.
                        logger.warning("Provedor %s recusou o pedido (%s), tentando o próximo: %s",
                                       pname, tipo, exc)
                        break
                    self.router.record_failure(
                        pname, tipo, complexity=complexity,
                        detail=str(exc), profile=profile,
                        model=None if failed_models else getattr(provider, "last_attempted_model", None),
                    )
                    logger.warning("Provedor %s falhou (%s), tentando o próximo: %s", pname, tipo, exc)
                    break  # próximo provedor
                finally:
                    if callable(end):
                        end(pname)
        # A falha também é uma resposta do turno: sem ela gravada, o replay
        # ficava sem a resposta daquela chamada e não sabia que ali o modelo falhou.
        _anotar_resposta(texto="", erro=str(last_error)[:500], tipos=list(tipos_das_falhas),
                         complexidade=complexity, perfil=profile)
        raise FalhaDaCadeia(f"Todos os provedores de LLM falharam: {last_error}", tipos_das_falhas) from last_error

    async def _descrever_imagens(self, messages: List[Dict], candidatos: List, complexity: Optional[str],
                                 profile: Optional[str]) -> List[Dict]:
        """As mensagens com as imagens trocadas pela descrição de quem enxerga
        no Router. Sem ninguém que enxergue, erro que diz o porquê."""
        selector = getattr(self.router, "selection", None)
        livre = selector("router") if callable(selector) else None
        try:
            enxergam = self.router.order(candidatos, complexity, profile=profile, selection=livre,
                                         requires={"vision"})
        except TypeError:
            enxergam = [p for p in candidatos if "vision" in _capacidades(self.router, p)]
        if not enxergam:
            raise RuntimeError(
                "O modelo escolhido no Dedicado não lê imagem, e nenhum provedor do Router lê para descrevê-la.")
        saida: List[Dict] = []
        for mensagem in messages:
            urls = _imagens_da_mensagem(mensagem)
            if not urls:
                saida.append(mensagem)
                continue
            texto = _texto_da_mensagem(mensagem)
            descricao, quem = await self._descrever(
                _PEDIDO_DE_DESCRICAO,
                f"Pedido da pessoa, para você saber o que importa: {texto or '(sem texto)'}",
                urls, enxergam, complexity, profile,
            )
            nova = {k: v for k, v in mensagem.items() if k != "imagens"}
            nova["content"] = (
                (texto + "\n\n" if texto else "")
                + f"[{len(urls)} imagem(ns) anexada(s). O modelo escolhido não lê imagem; "
                + f"{quem} descreveu:]\n{descricao}"
            )
            saida.append(nova)
        return saida

    async def descrever_com_quem_ve(self, pedido: str, urls: List[str],
                                    complexity: Optional[str] = None) -> Optional[str]:
        """Só a descrição, por quem enxerga no Router, fora da conta escolhida.
        Para quem precisa descrever uma imagem (o print do computer use) com o
        Dedicado ativo e a conta dele sem visão. None sem ninguém que enxergue."""
        candidatos = [p for p in self.providers
                      if getattr(p, "name", type(p).__name__) not in {"ultra", "ultra_max"}]
        selector = getattr(self.router, "selection", None)
        livre = selector("router") if callable(selector) else None
        try:
            enxergam = self.router.order(candidatos, complexity, selection=livre, requires={"vision"})
        except TypeError:
            enxergam = [p for p in candidatos if "vision" in _capacidades(self.router, p)]
        if not enxergam:
            return None
        try:
            descricao, _quem = await self._descrever("", pedido, urls, enxergam, complexity, None)
        except RuntimeError:
            return None
        return descricao

    async def _descrever(self, sistema: str, texto: str, urls: List[str], enxergam: List,
                         complexity: Optional[str], profile: Optional[str]):
        chave = hashlib.sha256("\n".join([sistema, texto, *urls]).encode("utf-8")).hexdigest()
        if chave in _DESCRICOES:
            _DESCRICOES.move_to_end(chave)
            return _DESCRICOES[chave]
        pedido = _para_provedor([
            *([{"role": "system", "content": sistema}] if sistema else []),
            {"role": "user", "content": texto,
             "imagens": [{"nome": f"imagem-{i + 1}", "data_url": url} for i, url in enumerate(urls)]},
        ])
        ultimo = None
        for provider in enxergam:
            pname = getattr(provider, "name", type(provider).__name__)
            inicio = time.perf_counter()
            try:
                resposta = str(await provider.complete(pedido, 0.1) or "").strip()
                if not resposta:
                    raise RuntimeError("descrição vazia")
            except Exception as exc:
                ultimo = exc
                failure = getattr(self.router, "record_failure", None)
                if callable(failure):
                    failure(pname, classify_error(exc), complexity=complexity, detail=str(exc), profile=profile)
                logger.warning("Descrição de imagem por %s falhou: %s", pname, exc)
                continue
            success = getattr(self.router, "record_success", None)
            if callable(success):
                success(pname, (time.perf_counter() - inicio) * 1000.0,
                        model=getattr(provider, "last_model", None), complexity=complexity, profile=profile)
            _somar_uso(getattr(provider, "last_usage", None))
            quem = getattr(provider, "last_model", None) or pname
            _DESCRICOES[chave] = (resposta, quem)
            while len(_DESCRICOES) > _DESCRICOES_TETO:
                _DESCRICOES.popitem(last=False)
            return resposta, quem
        raise RuntimeError(f"Ninguém no Router conseguiu descrever a imagem para o Dedicado: {ultimo}") from ultimo
