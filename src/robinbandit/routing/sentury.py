import asyncio
import contextvars
import inspect
import logging
import time
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

# No modo Máxima, chamadas internas BARATAS (classificação/roteamento) NÃO devem
# gastar a chave Ultra — só as LLMs gratuitas. Este contextvar suprime o Ultra
# num escopo específico, mantendo-o ativo para o planner/responder pesados.
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


def classify_error(exc: Exception) -> str:
    """Classifica o erro do provedor para decidir o retry (padrão Hermes):
    credit (402/crédito esgotado) = fora por MUITO tempo (dinheiro acabou, só
    volta no ciclo de billing); rate_limit (429) merece espera+retry; auth não
    adianta insistir; o resto cascateia direto."""
    s = str(exc).lower()
    # Crédito/billing esgotado (HF $0.10, DeepInfra/Fireworks pay-per-use). Vem
    # ANTES do 429 porque às vezes a mensagem também cita "quota".
    if ("402" in s or "insufficient" in s or "payment required" in s or "billing" in s
            or "out of credit" in s or "credits" in s or "exceeded your current quota" in s
            or "not enough balance" in s or "spend limit" in s):
        return "credit"
    if "429" in s or "too many requests" in s or "rate limit" in s or "rate_limit" in s or "quota" in s:
        return "rate_limit"
    if "401" in s or "403" in s or "invalid api key" in s or "unauthorized" in s or "permission" in s:
        return "auth"
    if "timeout" in s or "timed out" in s or "connect" in s or "network" in s:
        return "network"
    return "other"


from .chain import ChainProvider as _ChainBase, _somar as _somar_uso

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

        for provider in ordered:

            pname = getattr(provider, "name", type(provider).__name__)

            # Modelo preferido do perfil PARA este provedor (ex.: coding+gemini →
            # antigravity). None fora de perfil = comportamento de hoje.
            if override_model and pname == pref_name:
                pref = override_model
            elif route_selection and pname == route_selection.provider and route_selection.model:
                pref = route_selection.model
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
                    # Fase 5 — cota (quando o provedor expõe no header da resposta).
                    quota = getattr(provider, "last_quota", None)
                    if isinstance(quota, dict):
                        self.router.record_quota(pname, quota.get("rpm"), quota.get("rpd"))
                    return result
                except Exception as exc:
                    last_error = exc
                    record_model_failure = getattr(self.router, "record_model_failure", None)
                    failed_models = list(dict.fromkeys(getattr(provider, "model_failures", []) or []))
                    if callable(record_model_failure):
                        for failed_model in failed_models:
                            record_model_failure(pname, failed_model)
                    tipo = classify_error(exc)
                    if tipo == "rate_limit" and tentativa < self._RATE_LIMIT_RETRIES:
                        espera = self._RATE_LIMIT_BACKOFF * (tentativa + 1)
                        logger.warning("Provedor %s em rate-limit (429); aguardando %.1fs e 1 retry...", pname, espera)
                        await asyncio.sleep(espera)
                        continue
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
        raise RuntimeError(f"Todos os provedores de LLM falharam: {last_error}")
