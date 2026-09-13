import asyncio
import contextvars
import inspect
import logging
import time
from typing import Any, Dict, List, Optional

from .selection import coerce_selection

logger = logging.getLogger(__name__)

# Tokens somados do turno inteiro. O host zera no comeco e le no fim: cada
# turno chama varios motores (classificador, planner, responder) e o custo e
# a soma deles, nao o da ultima chamada.
_USO_DO_TURNO: contextvars.ContextVar = contextvars.ContextVar("robin_uso_do_turno", default=None)


def iniciar_contagem() -> None:
    _USO_DO_TURNO.set({"entrada": 0, "saida": 0, "total": 0, "cacheado": 0, "chamadas": 0})


def custo_estimado(modelo, uso, catalogo=None):
    """Custo em dolares do turno, quando existe preco publicado do modelo.

    Sem preco conhecido devolve None: melhor nao mostrar custo nenhum do que
    mostrar um numero inventado.
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
    # `cacheado: 0` seria ambiguo: pode ser "nenhum acerto de cache" ou "o
    # provedor nao informa". Quando nao ha o que dizer, o campo nao aparece.
    if isinstance(uso, dict) and not uso.get("cacheado"):
        return {chave: valor for chave, valor in uso.items() if chave != "cacheado"}
    return uso


def _somar(uso) -> None:
    atual = _USO_DO_TURNO.get()
    if not atual or not isinstance(uso, dict):
        return
    atual["entrada"] += int(uso.get("entrada") or 0)
    atual["saida"] += int(uso.get("saida") or 0)
    atual["total"] += int(uso.get("total") or 0)
    # Parte da entrada que veio do cache do provedor (cobrada a 10% no Gemini).
    atual["cacheado"] = int(atual.get("cacheado") or 0) + int(uso.get("cacheado") or 0)
    atual["chamadas"] += 1


def _anotar_o_gasto(provedor: str, uso) -> None:
    """O token já estava contado; só não sobrevivia ao turno.

    Sem isto, "quanto gastei este mês e com quem" não tinha resposta em lugar
    nenhum — o número existia, era usado para decidir dentro do turno e jogado
    fora em seguida.
    """
    try:
        from . import uso as _uso

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
    """Encadeia provedores de LLM e tenta cada um até um responder.

    A ORDEM não é fixa: o router reordena a cada request por saúde, latência e
    qualidade-por-context, e joga quem está em cooldown pro fim. Num 429, faz
    UM retry curto no mesmo provedor antes de cascatear.

    Cada provedor precisa de um `complete(messages, temperature)` async, que
    pode aceitar `context` por keyword, e opcionalmente expor `name`,
    `last_model` e `last_quota`. `cache`, se passado, precisa de `get`/`set`
    async — mesma entrada devolve a mesma saída sem tocar em provedor nenhum.

    O contexto é uma string opaca sua: tipo de tarefa, tier do modelo, tenant.
    O router indexa o aprendizado por ela e o provedor a recebe se aceitar.

    Depois de `complete`, `last_provider` diz qual provedor respondeu — é a chave
    a passar para `reward_quality`. Como são atributos de instância, uma cadeia
    compartilhada entre requests concorrentes embaralha os dois; sob
    concorrência, use uma cadeia por request (a construção é barata).

    Se o último provedor da cadeia nunca lança (um fallback local), o chamador
    nunca vê exceção por falha de LLM.
    """

    _RATE_LIMIT_RETRIES = 1
    _RATE_LIMIT_BACKOFF = 1.5  # segundos

    def __init__(self, providers: List, router, cache=None):
        self.providers = [p for p in providers if p is not None]
        if not self.providers:
            raise ValueError("ChainProvider precisa de pelo menos um provedor")
        self.router = router
        self._last_model = contextvars.ContextVar(f"robin_last_model_{id(self)}", default=None)
        self._last_provider = contextvars.ContextVar(f"robin_last_provider_{id(self)}", default=None)
        self._last_usage = contextvars.ContextVar(f"robin_last_usage_{id(self)}", default=None)
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

    @staticmethod
    def exigencias(messages: List[Dict[str, Any]]) -> set:
        """Le do proprio conteudo o que o turno exige do provedor.

        Uma imagem no meio das mensagens ja e a declaracao de que so quem
        enxerga serve; nao depende de alguem lembrar de passar a flag.
        """
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
        """Ponto unico onde a imagem anexada vira conteudo multimodal.

        No historico a mensagem continua sendo texto com as imagens num campo
        proprio: titulo, busca e resumo continuam lendo string, e so o payload
        que sai para o provedor carrega o formato multimodal.
        """
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
                       context: Optional[str] = None, selection=None) -> str:
        if self.cache is not None:
            cached = await self.cache.get(messages, temperature, context)
            if cached is not None:
                self.last_model = "cache"
                return cached
        last_error = None
        selected = coerce_selection(selection)
        self.last_model = None
        self.last_provider = None
        self.last_usage = None
        exigidas = self.exigencias(messages)
        messages = self.para_provedor(messages)
        ordered = self.router.order(self.providers, context, selection=selected, requires=exigidas)
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
                self.router.begin(pname)
                try:
                    # Checar a assinatura em vez de tentar-e-cair-no-TypeError:
                    # um TypeError vindo de dentro do provedor faria a chamada
                    # ser repetida, gastando cota duas vezes.
                    parametros = inspect.signature(provider.complete).parameters
                    accepts_any = any(p.kind is p.VAR_KEYWORD for p in parametros.values())
                    kwargs = {}
                    if "context" in parametros or accepts_any:
                        kwargs["context"] = context
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
                    self.last_provider = pname
                    # Tokens de quem respondeu: quem chama nao precisa saber
                    # qual provedor foi para contar o custo do turno.
                    self.last_usage = getattr(provider, "last_usage", None)
                    _somar(self.last_usage)
                    _anotar_o_gasto(pname, self.last_usage)
                    for failed_model in dict.fromkeys(getattr(provider, "model_failures", []) or []):
                        self.router.record_model_failure(pname, failed_model)
                    self.router.record_success(pname, latency_ms, model=self.last_model, context=context)
                    quota = getattr(provider, "last_quota", None)
                    if isinstance(quota, dict):
                        self.router.record_quota(pname, quota.get("rpm"), quota.get("rpd"))
                    if self.cache is not None:
                        await self.cache.set(messages, temperature, context, result)
                    return result
                except Exception as exc:
                    last_error = exc
                    failed_models = list(dict.fromkeys(getattr(provider, "model_failures", []) or []))
                    for failed_model in failed_models:
                        self.router.record_model_failure(pname, failed_model)
                    tipo = classify_error(exc)
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
