import asyncio
import contextvars
from collections import OrderedDict
import inspect
import logging
import time
from typing import Any, Dict, List, Optional

from .selection import coerce_selection

logger = logging.getLogger(__name__)

# Uso agregado do turno inteiro.
_USO_DO_TURNO: contextvars.ContextVar = contextvars.ContextVar("robin_uso_do_turno", default=None)

# O que o modelo respondeu, em ordem, no turno inteiro. Mesmo molde do uso
# acima, e pelo mesmo motivo: e o unico ponto por onde TODA chamada passa.
# O planner, o classificador, a compactacao e o conselho sao instancias
# diferentes de cadeia; so aqui elas se encontram.
#
# Guardar so o texto nao serve: em modo nativo a resposta do modelo NAO esta
# na string devolvida, esta em `last_tool_calls`. Um registro sem isso repete
# um turno nativo como "o modelo nao pediu ferramenta nenhuma".
_RESPOSTAS_DO_TURNO: contextvars.ContextVar = contextvars.ContextVar(
    "robin_respostas_do_turno", default=None,
)

# Teto por turno: um laco longo nao pode virar um registro de megabytes na
# memoria de um request.
MAX_RESPOSTAS = 40
MAX_TEXTO = 200_000


def suporta_ferramentas(provider) -> bool:
    """Diz se o adaptador preserva chamadas estruturadas de ferramenta."""
    declarado = getattr(provider, "supports_tools", None)
    if declarado is not None:
        return bool(declarado)
    try:
        parametros = inspect.signature(provider.complete).parameters.values()
    except (TypeError, ValueError):
        return False
    # So o parametro com nome prova suporte. `**kwargs` aceita qualquer coisa
    # e descarta em silencio: o provedor do Claude Code engolia `tools=`.
    return any(parametro.name == "tools" for parametro in parametros)


# Grude por conversa: o provedor e o modelo que responderam vao na frente nas
# chamadas seguintes, e o grude solta quando ele falha. A mesma conversa fica
# no mesmo modelo. Escolha explicita do painel vence o grude.
_CONVERSA: contextvars.ContextVar = contextvars.ContextVar("robin_conversa", default="")
_GRUDE: "OrderedDict[str, tuple]" = OrderedDict()
_GRUDE_MAX = 500


def iniciar_conversa(conversa: str) -> None:
    _CONVERSA.set(str(conversa or ""))


def grude_da_conversa() -> Optional[tuple]:
    conversa = _CONVERSA.get()
    return _GRUDE.get(conversa) if conversa else None


def _grudar(provedor: str, modelo: Optional[str]) -> None:
    conversa = _CONVERSA.get()
    if not conversa:
        return
    modelo = str(modelo or "")
    if modelo.startswith(f"{provedor}:"):
        modelo = modelo.split(":", 1)[1]
    _GRUDE[conversa] = (provedor, modelo)
    _GRUDE.move_to_end(conversa)
    while len(_GRUDE) > _GRUDE_MAX:
        _GRUDE.popitem(last=False)


def _soltar(provedor: str) -> None:
    conversa = _CONVERSA.get()
    if conversa and (_GRUDE.get(conversa) or ("",))[0] == provedor:
        _GRUDE.pop(conversa, None)


# Quem recusou o pedido neste turno por política de conteúdo. A cadeia passa
# ao próximo provedor; o turno avisa a pessoa de que houve troca.
_RECUSAS_DO_TURNO: contextvars.ContextVar = contextvars.ContextVar("robin_recusas_do_turno", default=None)


def recusas_do_turno() -> List[Dict[str, Any]]:
    return list(_RECUSAS_DO_TURNO.get() or [])


def iniciar_contagem() -> None:
    _RECUSAS_DO_TURNO.set([])
    _USO_DO_TURNO.set({
        "entrada": 0, "saida": 0, "total": 0, "cacheado": 0,
        "chamadas": 0, "custo_usd": 0.0, "chamadas_com_custo": 0,
    })


def iniciar_gravacao() -> None:
    """Liga a captura para este turno. Sem chamar isto, nada e guardado.

    Desligado por padrao de proposito: quem grava e o turno, e um processo que
    nunca comeca um turno (um script, um teste) nao deve acumular nada.
    """
    _RESPOSTAS_DO_TURNO.set([])


def anotar_resposta(**campos: Any) -> None:
    """Uma resposta do modelo, na ordem em que ela chegou.

    A prova de falha: observabilidade que derruba o turno que ela observa e
    pior que observabilidade nenhuma.
    """
    fila = _RESPOSTAS_DO_TURNO.get()
    if fila is None or len(fila) >= MAX_RESPOSTAS:
        return
    try:
        texto = campos.get("texto")
        if isinstance(texto, str) and len(texto) > MAX_TEXTO:
            campos["texto"] = texto[:MAX_TEXTO]
            campos["truncado"] = True
        fila.append(dict(campos))
    except Exception:  # pragma: no cover - captura nunca derruba o turno
        logger.debug("Nao consegui anotar a resposta do turno.", exc_info=True)


def respostas_do_turno() -> Optional[List[Dict[str, Any]]]:
    """O que o modelo respondeu neste turno, em ordem, ou None se nao grava."""
    fila = _RESPOSTAS_DO_TURNO.get()
    return list(fila) if fila is not None else None


def custo_estimado(modelo, uso, catalogo=None):
    """Custo em dolares quando ha preco publicado para o modelo.

    Sem preco conhecido devolve ``None``: zero significaria gratuito e seria
    uma informacao falsa para modelos cujo valor apenas nao foi catalogado.
    """
    if not uso or not modelo:
        return None
    chave = str(modelo).split(":", 1)[-1]
    precos = (catalogo or {}).get(chave)
    if not precos:
        return None
    entrada = precos.get("prompt_per_million")
    saida = precos.get("completion_per_million")
    if entrada is None and saida is None:
        return None
    total = 0.0
    total += (uso.get("entrada") or 0) / 1_000_000 * float(entrada or 0)
    total += (uso.get("saida") or 0) / 1_000_000 * float(saida or 0)
    return round(total, 6)


def contagem_do_turno():
    uso = _USO_DO_TURNO.get()
    # Omite campos que o provedor não informou.
    if isinstance(uso, dict):
        ocultos = set()
        if not uso.get("cacheado"):
            ocultos.add("cacheado")
        if not uso.get("chamadas_com_custo"):
            ocultos.update({"custo_usd", "chamadas_com_custo"})
        return {chave: valor for chave, valor in uso.items() if chave not in ocultos}
    return uso


def _somar(uso) -> None:
    atual = _USO_DO_TURNO.get()
    if not atual or not isinstance(uso, dict):
        return
    entrada = int(uso.get("entrada") or 0)
    saida = int(uso.get("saida") or 0)
    atual["entrada"] += entrada
    atual["saida"] += saida
    atual["total"] += int(uso.get("total") or 0) or (entrada + saida)
    # Parte da entrada que veio do cache do provedor (cobrada a 10% no Gemini).
    atual["cacheado"] = int(atual.get("cacheado") or 0) + int(uso.get("cacheado") or 0)
    atual["chamadas"] += 1
    if uso.get("custo_usd") is not None:
        try:
            atual["custo_usd"] += float(uso["custo_usd"])
            atual["chamadas_com_custo"] += 1
        except (TypeError, ValueError):
            pass


def _anotar_o_gasto(provedor: str, uso) -> None:
    """Persiste uso agregado para o painel."""
    try:
        from ..state import uso as _uso

        _uso.registrar(provedor, uso)
    except Exception:
        # Contabilidade nunca derruba o turno que ela está medindo.
        pass


def classify_error(exc: Exception) -> str:
    """Classifica o erro do provedor para decidir o retry.

    A tabela vive em `erros.py` e vem do YAML; aqui fica so o encaminhamento,
    para o nome antigo continuar valendo em quem ja importava daqui.
    """
    from .erros import classificar

    return classificar(exc)


class FalhaDaCadeia(RuntimeError):
    """Nenhum provedor respondeu, com o TIPO de cada falha.

    Continua sendo `RuntimeError` para quem ja capturava assim. O tipo e o que
    permite reagir certo: contexto estourado em todos pede compactar e tentar
    de novo, nao "o servico caiu".
    """

    def __init__(self, mensagem: str, tipos: List[str]):
        super().__init__(mensagem)
        self.tipos = list(tipos)
        self.tipo = self.tipos[-1] if self.tipos else "other"

    @property
    def da_requisicao(self) -> bool:
        """Todos recusaram o PEDIDO: trocar de provedor nao resolve, mudar o pedido sim."""
        from .erros import da_requisicao

        return bool(self.tipos) and all(da_requisicao(t) for t in self.tipos)


class ChainProvider:
    """Encadeia provedores e tenta cada um até obter resposta."""

    _RATE_LIMIT_RETRIES = 1
    _RATE_LIMIT_BACKOFF = 1.5  # segundos

    def __init__(self, providers: List, router, cache=None, activity=None):
        self.providers = [p for p in providers if p is not None]
        if not self.providers:
            raise ValueError("ChainProvider precisa de pelo menos um provedor")
        self.router = router
        self.activity = activity
        self._last_model = contextvars.ContextVar(f"robin_last_model_{id(self)}", default=None)
        self._last_provider = contextvars.ContextVar(f"robin_last_provider_{id(self)}", default=None)
        self._last_usage = contextvars.ContextVar(f"robin_last_usage_{id(self)}", default=None)
        self._last_tool_calls = contextvars.ContextVar(
            f"robin_last_tool_calls_{id(self)}", default=None,
        )
        self.cache = cache

    @property
    def last_model(self):
        return self._last_model.get()

    @last_model.setter
    def last_model(self, value):
        self._last_model.set(value)

    @property
    def last_usage(self):
        return self._last_usage.get()

    @last_usage.setter
    def last_usage(self, value):
        self._last_usage.set(value)

    @property
    def last_provider(self):
        return self._last_provider.get()

    @last_provider.setter
    def last_provider(self, value):
        self._last_provider.set(value)

    @property
    def last_tool_calls(self):
        return self._last_tool_calls.get()

    @last_tool_calls.setter
    def last_tool_calls(self, value):
        self._last_tool_calls.set(value)

    @staticmethod
    def exigencias(messages: List[Dict[str, Any]]) -> set:
        """Lê do conteúdo o que o turno exige do provedor."""
        for mensagem in messages or []:
            if mensagem.get("imagens"):
                return {"vision"}
            conteudo = mensagem.get("content")
            if not isinstance(conteudo, list):
                continue
            for parte in conteudo:
                if isinstance(parte, dict) and str(parte.get("type") or "").startswith("image"):
                    return {"vision"}
        return set()

    @staticmethod
    def para_provedor(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Converte anexos locais para payload multimodal do provedor."""
        saida: List[Dict[str, Any]] = []
        for mensagem in messages or []:
            imagens = mensagem.get("imagens")
            if not imagens:
                saida.append(mensagem)
                continue
            partes: List[Dict[str, Any]] = []
            texto = mensagem.get("content")
            if isinstance(texto, list):
                partes.extend(texto)
            elif texto:
                partes.append({"type": "text", "text": str(texto)})
            for imagem in imagens:
                url = str((imagem or {}).get("data_url") or "")
                if url:
                    partes.append({"type": "image_url", "image_url": {"url": url}})
            limpa = {k: v for k, v in mensagem.items() if k != "imagens"}
            limpa["content"] = partes
            saida.append(limpa)
        return saida

    async def complete(self, messages: List[Dict[str, Any]], temperature: float = 0.2,
                       context: Optional[str] = None, selection=None,
                       tools: Optional[list] = None,
                       reasoning_effort: Optional[str] = None) -> str:
        # Uma entrada com ferramentas não pode reutilizar só o texto em cache:
        # a chamada estruturada e seu id também fazem parte da resposta.
        if self.cache is not None and not tools:
            cached = await self.cache.get(messages, temperature, context)
            if cached is not None:
                self.last_model = "cache"
                return cached
        last_error = None
        tipos_das_falhas: List[str] = []
        selected = coerce_selection(selection)
        self.last_model = None
        self.last_provider = None
        self.last_usage = None
        self.last_tool_calls = None
        exigidas = self.exigencias(messages)
        messages = self.para_provedor(messages)
        candidatos = self.providers
        if tools:
            candidatos = [
                provider for provider in candidatos
                if suporta_ferramentas(provider)
            ]
            if not candidatos:
                raise RuntimeError(
                    "Nenhum provedor configurado aceita ferramentas neste turno."
                )
        ordered = self.router.order(candidatos, context, selection=selected, requires=exigidas)
        if not ordered and exigidas:
            raise RuntimeError(
                "Nenhum provedor configurado consegue ler imagem neste turno."
            )
        if not ordered:
            raise RuntimeError(
                f"Provedor selecionado não está disponível: {selected.provider}"
            )
        grude = None if selected.provider else grude_da_conversa()
        if grude:
            ordered = sorted(ordered, key=lambda p: getattr(p, "name", type(p).__name__) != grude[0])
        for provider in ordered:
            pname = getattr(provider, "name", type(provider).__name__)
            for tentativa in range(self._RATE_LIMIT_RETRIES + 1):
                inicio = time.perf_counter()
                evento = self.activity.abrir(
                    pname, context, modo=selected.mode, tentativa=tentativa + 1,
                ) if self.activity is not None else None
                self.router.begin(pname)
                try:
                    # Evita repetir chamada por TypeError interno do provedor.
                    parametros = inspect.signature(provider.complete).parameters
                    accepts_any = any(p.kind is p.VAR_KEYWORD for p in parametros.values())
                    kwargs = {}
                    if "context" in parametros or accepts_any:
                        kwargs["context"] = context
                    if tools and ("tools" in parametros or accepts_any):
                        kwargs["tools"] = tools
                    if reasoning_effort and ("reasoning_effort" in parametros or accepts_any):
                        kwargs["reasoning_effort"] = reasoning_effort
                    if pname == selected.provider and selected.model:
                        if "preferred_model" in parametros or accepts_any:
                            kwargs["preferred_model"] = selected.model
                        if "strict_model" in parametros or accepts_any:
                            kwargs["strict_model"] = selected.mode == "strict"
                    elif (grude and pname == grude[0] and grude[1] in (getattr(provider, "models", None) or [])
                          and ("preferred_model" in parametros or accepts_any)):
                        kwargs["preferred_model"] = grude[1]
                    elif getattr(provider, "models", None):
                        order_models = getattr(self.router, "order_models", None)
                        if callable(order_models):
                            ranked = order_models(pname, list(provider.models), context)
                            if ranked and ("preferred_model" in parametros or accepts_any):
                                kwargs["preferred_model"] = ranked[0]
                    result = await provider.complete(messages, temperature, **kwargs)
                    latency_ms = (time.perf_counter() - inicio) * 1000.0
                    self.last_model = getattr(provider, "last_model", type(provider).__name__)
                    # Preserva a conta real que respondeu dentro do Reforçado.
                    efetivo = getattr(provider, "last_provider", None) or pname
                    self.last_provider = efetivo
                    self.last_usage = getattr(provider, "last_usage", None)
                    self.last_tool_calls = getattr(provider, "last_tool_calls", None)
                    _somar(self.last_usage)
                    _anotar_o_gasto(efetivo, self.last_usage)
                    for failed_model in dict.fromkeys(getattr(provider, "model_failures", []) or []):
                        self.router.record_model_failure(pname, failed_model)
                    self.router.record_success(pname, latency_ms, model=self.last_model, context=context)
                    if not selected.provider:
                        _grudar(pname, self.last_model)
                    quota = getattr(provider, "last_quota", None)
                    if isinstance(quota, dict):
                        self.router.record_quota(pname, quota.get("rpm"), quota.get("rpd"))
                    if self.cache is not None and not tools:
                        await self.cache.set(messages, temperature, context, result)
                    if evento:
                        self.activity.concluir(
                            evento,
                            status="sucesso",
                            provedor=efetivo,
                            modelo=self.last_model,
                            duracao_ms=latency_ms,
                            uso=self.last_usage,
                        )
                    return result
                except Exception as exc:
                    latency_ms = (time.perf_counter() - inicio) * 1000.0
                    last_error = exc
                    failed_models = list(dict.fromkeys(getattr(provider, "model_failures", []) or []))
                    for failed_model in failed_models:
                        self.router.record_model_failure(pname, failed_model)
                    tipo = classify_error(exc)
                    if evento:
                        self.activity.concluir(
                            evento,
                            status="falha",
                            modelo=getattr(provider, "last_attempted_model", None),
                            duracao_ms=latency_ms,
                            motivo=tipo,
                        )
                    from .erros import da_requisicao, transitorio

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
                        # O pedido nao cabe ou nao passa AQUI; outro provedor
                        # pode aceitar. Nada de saude nem de cooldown: este
                        # provedor segue otimo para o proximo pedido normal, e
                        # castiga-lo ensinaria o bandit a desconfiar dele.
                        logger.warning("Provedor %s recusou o pedido (%s), tentando o próximo: %s",
                                       pname, tipo, exc)
                        break
                    self.router.record_failure(
                        pname, tipo, context=context, detail=str(exc),
                        model=None if failed_models else getattr(provider, "last_attempted_model", None),
                    )
                    logger.warning("Provedor %s falhou (%s), tentando o próximo: %s", pname, tipo, exc)
                    break
                finally:
                    self.router.end(pname)
        raise FalhaDaCadeia(f"Todos os provedores de LLM falharam: {last_error}", tipos_das_falhas)
