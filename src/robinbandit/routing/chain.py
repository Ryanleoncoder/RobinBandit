import asyncio
import contextvars
import inspect
import logging
import time
from typing import Any, Dict, List, Optional

from .selection import coerce_selection

logger = logging.getLogger(__name__)

# Uso agregado do turno inteiro.
_USO_DO_TURNO: contextvars.ContextVar = contextvars.ContextVar("robin_uso_do_turno", default=None)


def suporta_ferramentas(provider) -> bool:
    """Diz se o adaptador preserva chamadas estruturadas de ferramenta."""
    declarado = getattr(provider, "supports_tools", None)
    if declarado is not None:
        return bool(declarado)
    try:
        parametros = inspect.signature(provider.complete).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parametro.name == "tools" or parametro.kind is parametro.VAR_KEYWORD
        for parametro in parametros
    )


def iniciar_contagem() -> None:
    _USO_DO_TURNO.set({
        "entrada": 0, "saida": 0, "total": 0, "cacheado": 0,
        "chamadas": 0, "custo_usd": 0.0, "chamadas_com_custo": 0,
    })


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
                    if tipo == "rate_limit" and tentativa < self._RATE_LIMIT_RETRIES:
                        espera = self._RATE_LIMIT_BACKOFF * (tentativa + 1)
                        logger.warning("Provedor %s em rate-limit (429); aguardando %.1fs e 1 retry...", pname, espera)
                        await asyncio.sleep(espera)
                        continue
                    self.router.record_failure(
                        pname, tipo, context=context, detail=str(exc),
                        model=None if failed_models else getattr(provider, "last_attempted_model", None),
                    )
                    logger.warning("Provedor %s falhou (%s), tentando o próximo: %s", pname, tipo, exc)
                    break
                finally:
                    self.router.end(pname)
        raise RuntimeError(f"Todos os provedores de LLM falharam: {last_error}")
