"""Decide qual provedor de LLM tentar primeiro.

O inimigo aqui não é custo, é COTA (429). A ordenação combina quatro sinais:

- Cooldown: provedor que deu 429/erro vai pro fim da fila por um tempo (TTL que
  cresce com reincidência). Não fica batendo em porta fechada.
- Saúde: taxa de sucesso e latência (Peak EWMA — pico entra na hora, recuperação
  decai devagar), mais as requisições abertas contra cada provedor.
- Bandit: Thompson sampling Beta por célula (contexto, provedor), aprendendo
  qual provedor rende melhor em cada contexto. O contexto é uma string opaca
  escolhida por quem chama — tipo de tarefa, tier do modelo, tenant, o que
  fizer sentido no seu agente.
- Cota: penaliza quem está quase sem requests quando o provedor expõe isso no
  header, evitando o 429 antes de ele acontecer.

Estado em memória, com dump/load para sobreviver a restart.

Registro passivo: o estado só muda com o resultado de requests REAIS — nunca
cutucamos a LLM só pra medir. É o que preserva a cota.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .selection import coerce_selection

# Quanto tempo cada tipo de falha tira o provedor do jogo vem de `erros.py`,
# que le a tabela do YAML. O que fica aqui e o algoritmo — media de latencia,
# bandit, ordenacao — que e aprendido, nao configurado.
from .erros import cooldown_de  # noqa: E402  (re-export: o router e quem aplica)


# Peak EWMA (Envoy contrib / Finagle): a latência é assimétrica de propósito —
# um pico entra no score na hora, e a recuperação decai devagar. Degradar custa
# caro imediatamente; voltar ao normal precisa se provar em várias amostras.
# _LAT_RECOVERY é o peso da amostra nova SÓ na descida.
_LAT_RECOVERY = 0.3
_LAT_FLOOR_MS, _LAT_CEIL_MS = 150.0, 8000.0

# Requisições abertas contra o provedor (o termo `active` do LEAST_REQUEST do
# Envoy). Penalidade limitada: com _INFLIGHT_HALF abertas ela é metade do teto,
# e satura em _INFLIGHT_PENALTY_MAX. A escala do score inteiro fica em ~0..1.2,
# então 0.15 pesa sem dominar.
_INFLIGHT_PENALTY_MAX = 0.15
_INFLIGHT_HALF = 2.0

_COLD_START_MASS = 6.0                  # ~6 observações reais já movem o prior
_SAMPLE_CAP = 400.0                     # teto de (alpha+beta) por célula
# Decaimento (recência): a cada atualização o histórico encolhe um tico, então
# dado velho pesa menos e o roteador se readapta se um provedor piora/melhora.
# É o que evita "acumular = engessar num provedor rápido-porém-fraco".
_DECAY = 0.99
# Recompensa de QUALIDADE: aprovou → +alpha forte; corrigiu → +beta. Assim
# "sucesso" passa a significar RESPOSTA BOA, não só "não deu erro".
_QUALITY_WEIGHT = 3.0

_DEFAULT_QUALITY = 0.6
_DEFAULT_TIER = 2
_DEFAULT_CONTEXT = "default"
# (qualidade, latência, sucesso) — equilibrado. Quem quiser privilegiar
# qualidade ou velocidade em certos contextos passa a própria tabela.
_DEFAULT_WEIGHTS = (0.40, 0.30, 0.30)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class _Cell:
    """Posterior Beta(alpha,beta) de uma célula (contexto, provedor)."""
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        t = self.alpha + self.beta
        return self.alpha / t if t > 0 else 0.5

    @property
    def samples(self) -> int:
        return max(0, int(self.alpha + self.beta - _COLD_START_MASS))


@dataclass
class _Stat:
    """Estado de runtime de um provedor."""
    ok: int = 0
    err: int = 0
    latency_ms: Optional[float] = None       # EWMA
    consecutive_429: int = 0
    cooldown_until: float = 0.0
    last_status: str = "idle"                 # idle|ok|rate_limit|credit|error
    last_detail: Optional[str] = None
    last_model: Optional[str] = None
    last_ts: float = 0.0
    rpm_remaining: Optional[int] = None
    rpd_remaining: Optional[int] = None
    # Operational health and answer quality are independent evidence channels.
    health: Dict[str, _Cell] = field(default_factory=dict)
    quality: Dict[str, _Cell] = field(default_factory=dict)
    request_timestamps: List[float] = field(default_factory=list)


@dataclass
class _ModelStat:
    """Sinais que pertencem ao modelo, não à conta/provedor."""
    ok: int = 0
    err: int = 0
    latency_ms: Optional[float] = None
    quality: Dict[str, _Cell] = field(default_factory=dict)


class ProviderRouter:
    """Estado + lógica de ordenação dos provedores. Thread-safe.

    `priors` mapeia a chave do provedor para `{"tier": int, "quality": float}`.
    `quality` (0..1) vira o prior do bandit e `tier` (1 = preferencial) um bônus
    pequeno no score; provedor ausente usa 0.6 e tier 2.

    `last_resort` é a chave do provedor que deve ficar sempre por último e que
    nunca acumula evidência de qualidade — tipicamente um fallback local cuja
    resposta não diz nada sobre qualidade de LLM.

    `weights` mapeia contexto para o peso de (qualidade, latência, sucesso) no
    score, permitindo que um contexto privilegie resposta boa e outro,
    velocidade. Contexto sem entrada usa (0.40, 0.30, 0.30).
    """

    def __init__(self, priors: Optional[Dict[str, Dict[str, Any]]] = None,
                 last_resort: Optional[str] = None,
                 weights: Optional[Dict[str, Tuple[float, float, float]]] = None,
                 providers: Optional[Dict[str, Dict[str, Any]]] = None,
                 strategy: str = "adaptive",
                 cost_penalties: Optional[Dict[str, float]] = None,
                 profiles: Optional[Dict[str, List[Dict[str, str]]]] = None,
                 seed: Optional[int] = None) -> None:
        if priors is not None and providers is not None:
            raise ValueError("use apenas providers; priors é o alias legado")
        # provedor -> horas da janela; vazio significa "ninguem tem".
        self._janelas: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._stats: Dict[str, _Stat] = {}
        self._model_stats: Dict[str, _ModelStat] = {}
        # Thompson sorteia: sem semente, a mesma situacao pode dar ordens
        # diferentes. Em producao e assim que se quer (e o que faz explorar);
        # num teste ou num replay, `seed` torna a decisao reproduzivel.
        self._rng = random.Random(seed)
        self._priors = providers if providers is not None else (priors or {})
        self._last_resort = last_resort
        self._weights_by_context = weights or {}
        self._inflight: Dict[str, int] = {}
        self._strategy = str(strategy or "adaptive").lower()
        if self._strategy not in {"adaptive", "tier"}:
            raise ValueError("strategy deve ser adaptive ou tier")
        self._cost_penalties = dict(cost_penalties or {})
        self._profiles = dict(profiles or {})

    def _stat(self, key: str) -> _Stat:
        s = self._stats.get(key)
        if s is None:
            s = _Stat()
            self._stats[key] = s
        return s

    def _quality_prior(self, key: str) -> float:
        return float(self._priors.get(key, {}).get("quality", _DEFAULT_QUALITY))

    def _tier(self, key: str) -> int:
        base = int(self._priors.get(key, {}).get("tier", _DEFAULT_TIER))
        if key == self._last_resort:
            return base
        try:
            from .account_config import overrides_de_tier
            return int(overrides_de_tier().get(key, base))
        except Exception:
            return base

    @staticmethod
    def _model_key(provider: str, model: Optional[str]) -> Optional[str]:
        raw = str(model or "").strip()
        if not raw:
            return None
        return raw if raw.startswith(f"{provider}:") else f"{provider}:{raw}"

    def _model_config(self, provider: str, model: str) -> Dict[str, Any]:
        raw = self._priors.get(provider, {}).get("models") or {}
        bare = model.split(":", 1)[1] if model.startswith(f"{provider}:") else model
        if isinstance(raw, dict):
            return dict(raw.get(bare) or {})
        models = [str(item) for item in raw]
        try:
            return {"priority": models.index(bare) + 1}
        except ValueError:
            return {}

    def _model_quality_cell(self, provider: str, model: str,
                            context: Optional[str]) -> _Cell:
        stat = self._model_stats.setdefault(model, _ModelStat())
        key = context or _DEFAULT_CONTEXT
        cell = stat.quality.get(key)
        if cell is None:
            config = self._model_config(provider, model)
            mean = _clamp(float(config.get("quality", self._quality_prior(provider))), 0.05, 0.95)
            cell = _Cell(mean * _COLD_START_MASS, (1 - mean) * _COLD_START_MASS)
            stat.quality[key] = cell
        return cell

    def _quality_cell(self, s: _Stat, key: str, context: Optional[str]) -> _Cell:
        c = context or _DEFAULT_CONTEXT
        cell = s.quality.get(c)
        if cell is None:
            mean = _clamp(self._quality_prior(key), 0.05, 0.95)
            cell = _Cell(alpha=mean * _COLD_START_MASS, beta=(1 - mean) * _COLD_START_MASS)
            s.quality[c] = cell
        return cell

    def _health_cell(self, s: _Stat, context: Optional[str]) -> _Cell:
        c = context or _DEFAULT_CONTEXT
        cell = s.health.get(c)
        if cell is None:
            cell = _Cell(alpha=0.7 * _COLD_START_MASS, beta=0.3 * _COLD_START_MASS)
            s.health[c] = cell
        return cell

    def _bump(self, cell: _Cell, d_alpha: float, d_beta: float) -> None:
        """Aplica decaimento (recência) e soma o reforço. Piso baixo pra não
        colapsar; teto pelo SAMPLE_CAP."""
        cell.alpha = max(0.2, cell.alpha * _DECAY) + d_alpha
        cell.beta = max(0.2, cell.beta * _DECAY) + d_beta
        if cell.alpha + cell.beta > _SAMPLE_CAP:  # normaliza mantendo a média
            fator = _SAMPLE_CAP / (cell.alpha + cell.beta)
            cell.alpha *= fator
            cell.beta *= fator

    @staticmethod
    def _register_request_timestamp(s: _Stat) -> None:
        now = time.time()
        s.request_timestamps.append(now)
        s.request_timestamps = [stamp for stamp in s.request_timestamps if now - stamp <= 60.0]

    def record_success(self, key: str, latency_ms: float, model: Optional[str] = None,
                       context: Optional[str] = None) -> None:
        self._anotar_no_dia(key, ok=True)
        self._anotar_na_janela(key, ok=True)
        with self._lock:
            s = self._stat(key)
            self._register_request_timestamp(s)
            s.ok += 1
            s.consecutive_429 = 0
            s.cooldown_until = 0.0
            s.last_status = "ok"
            s.last_detail = None
            s.last_model = model or s.last_model
            s.last_ts = time.time()
            if s.latency_ms is None or latency_ms > s.latency_ms:
                s.latency_ms = latency_ms
            else:
                s.latency_ms = _LAT_RECOVERY * latency_ms + (1 - _LAT_RECOVERY) * s.latency_ms
            self._bump(self._health_cell(s, context), 1.0, 0.0)
            model_key = self._model_key(key, model)
            if model_key:
                model_stat = self._model_stats.setdefault(model_key, _ModelStat())
                model_stat.ok += 1
                if model_stat.latency_ms is None or latency_ms > model_stat.latency_ms:
                    model_stat.latency_ms = latency_ms
                else:
                    model_stat.latency_ms = (
                        _LAT_RECOVERY * latency_ms
                        + (1 - _LAT_RECOVERY) * model_stat.latency_ms
                    )

    def reward_quality(self, key: str, context: Optional[str], good: bool,
                       model: Optional[str] = None) -> None:
        """Sinal de QUALIDADE vindo de quem avaliou a resposta: aprovou
        (good=True) reforça alpha forte; corrigiu (good=False) reforça beta.

        Ignora o provedor de último recurso: a resposta dele é um aviso fixo, e
        avaliá-la só criaria evidência sem sentido.
        """
        if key == self._last_resort:
            return
        with self._lock:
            provider_stat = self._stat(key)
            model_key = self._model_key(key, model)
            cell = (
                self._model_quality_cell(key, model_key, context)
                if model_key else self._quality_cell(provider_stat, key, context)
            )
            if good:
                self._bump(cell, _QUALITY_WEIGHT, 0.0)
            else:
                self._bump(cell, 0.0, _QUALITY_WEIGHT)

    def _anotar_na_janela(self, key: str, *, ok: bool, bloqueado: bool = False) -> None:
        """As assinaturas têm bloco de uso com hora para virar.

        Só conta quem de fato tem janela: contar todo provedor gravaria 40
        linhas para responder uma pergunta que só existe para assinatura.
        """
        horas = self._janelas.get(str(key or "").strip().lower())
        if not horas:
            return
        try:
            from . import janela

            janela.registrar(key, horas=horas, ok=ok, bloqueado=bloqueado)
        except Exception:
            pass

    def declarar_janelas(self, janelas: Dict[str, float]) -> None:
        """Quais provedores têm janela de assinatura, e de quantas horas."""
        self._janelas = {str(k).strip().lower(): float(v) for k, v in (janelas or {}).items()}

    @staticmethod
    def _anotar_no_dia(key: str, *, ok: bool, motivo: str = "") -> None:
        """Um contador por dia, à parte do bandit.

        O bandit decide com o agora — é o certo para rotear. Isto responde
        outra pergunta: quem passou mais tempo no vermelho no mês. Sem os dois,
        um provedor bom que caiu um dia fica indistinguível de um ruim.
        """
        try:
            from . import historico

            historico.registrar(key, ok=ok, motivo=motivo)
        except Exception:
            pass

    def _janela_estourada(self, key: str, kind: str) -> float:
        """Segundos até a janela virar, se foi ela que acabou. Senão, `0`.

        Assinatura não tem cota por token: tem bloco. Bater o limite dela não é
        o provedor degradando — é o bloco acabando, com hora marcada para
        voltar inteiro. Quem não tem janela declarada não entra aqui: num
        provedor por chave, `429` recorrente é informação de verdade sobre
        disponibilidade, e apagar isso cegaria o bandit.
        """
        if str(kind or "") != "rate_limit":
            return 0.0
        if not self._janelas.get(str(key or "").strip().lower()):
            return 0.0
        try:
            from . import janela

            estado = janela.estado(key)
            return float(estado.get("falta_s") or 0.0) if estado.get("aberta") else 0.0
        except Exception:
            return 0.0

    def record_failure(self, key: str, kind: str, context: Optional[str] = None,
                       detail: Optional[str] = None, model: Optional[str] = None) -> None:
        self._anotar_no_dia(key, ok=False, motivo=str(detail or kind or ""))
        # `rate_limit` numa assinatura é a janela tendo acabado, não lentidão.
        self._anotar_na_janela(key, ok=False, bloqueado=str(kind or "") == "rate_limit")
        # Fora do lock: lê o arquivo da janela, e segurar o router para isso
        # atrasaria toda decisão concorrente.
        falta = self._janela_estourada(key, kind)
        with self._lock:
            s = self._stat(key)
            self._register_request_timestamp(s)
            s.err += 1
            s.last_detail = (detail or "")[:160] or None
            now = time.time()
            s.last_ts = now
            if kind == "rate_limit":
                s.consecutive_429 += 1
                # Com janela, espera-se a virada: o cooldown exponencial
                # mandaria tentar de novo antes da hora, gastando chamada para
                # ouvir o mesmo `429`, ou muito depois dela, desperdiçando
                # bloco pago que já tinha voltado.
                espera = falta or cooldown_de("rate_limit", s.consecutive_429)
                s.cooldown_until = now + espera
                s.last_status = "rate_limit"
            else:
                s.cooldown_until = now + cooldown_de(kind)
                s.last_status = "credit" if kind == "credit" else "error"
            if not falta:
                # A saúde só registra o que diz respeito ao provedor. Bloco
                # esgotado ensinaria o bandit a desconfiar de quem estava
                # apenas esperando a hora — e a desconfiança sobreviveria à
                # virada da janela, porque o posterior não esquece sozinho.
                self._bump(self._health_cell(s, context), 0.0, 1.0)
            model_key = self._model_key(key, model)
            if model_key:
                self._model_stats.setdefault(model_key, _ModelStat()).err += 1

    def record_quota(self, key: str, rpm_remaining: Optional[int] = None,
                     rpd_remaining: Optional[int] = None) -> None:
        with self._lock:
            s = self._stat(key)
            if rpm_remaining is not None:
                s.rpm_remaining = rpm_remaining
            if rpd_remaining is not None:
                s.rpd_remaining = rpd_remaining

    def record_model_failure(self, key: str, model: str) -> None:
        """Falha de um modelo sem contaminar a saúde da conta/provedor."""
        with self._lock:
            model_key = self._model_key(key, model)
            if model_key:
                self._stat(key)
                self._model_stats.setdefault(model_key, _ModelStat()).err += 1

    def begin(self, key: str) -> None:
        """Marca uma chamada aberta contra o provedor, para que ele perca
        prioridade enquanto está ocupado. Parear sempre com `end()` num
        `finally` — um `begin` sem `end` penaliza o provedor para sempre."""
        with self._lock:
            self._inflight[key] = self._inflight.get(key, 0) + 1

    def end(self, key: str) -> None:
        with self._lock:
            restantes = self._inflight.get(key, 0) - 1
            if restantes > 0:
                self._inflight[key] = restantes
            else:
                self._inflight.pop(key, None)

    def inflight(self, key: str) -> int:
        with self._lock:
            return self._inflight.get(key, 0)

    def cooldown_remaining(self, key: str) -> float:
        with self._lock:
            s = self._stats.get(key)
            if not s:
                return 0.0
            return max(0.0, s.cooldown_until - time.time())

    def _latency_norm(self, s: _Stat) -> float:
        if s.latency_ms is None:
            return 0.5
        return _clamp((s.latency_ms - _LAT_FLOOR_MS) / (_LAT_CEIL_MS - _LAT_FLOOR_MS), 0.0, 1.0)

    def _weights(self, context: Optional[str]) -> Tuple[float, float, float]:
        return self._weights_by_context.get(context or _DEFAULT_CONTEXT, _DEFAULT_WEIGHTS)

    @staticmethod
    def _quota_penalty(s: _Stat) -> float:
        """Penaliza quem está quase sem cota, pra EVITAR o provedor ANTES do 429
        (não esperar bater). Só quando o header expôs o restante."""
        rem = s.rpm_remaining
        if rem is None:
            return 0.0
        if rem <= 0:
            return 0.5
        if rem <= 2:
            return 0.25
        if rem <= 5:
            return 0.1
        return 0.0

    def _inflight_penalty(self, key: str) -> float:
        n = self._inflight.get(key, 0)
        return _INFLIGHT_PENALTY_MAX * (n / (n + _INFLIGHT_HALF))

    def _profile_bonus(self, key: str, context: Optional[str]) -> float:
        profile = str(context or "").split(":", 1)[0].lower()
        targets = self._profiles.get(profile) or []
        providers: List[str] = []
        for target in targets:
            provider = str(target.get("provider") or "").lower()
            if provider and provider not in providers:
                providers.append(provider)
        if key not in providers:
            return 0.0
        index = providers.index(key)
        return (0.20, 0.12, 0.06)[index] if index < 3 else 0.02

    def _profile_bucket(self, key: str, context: Optional[str]) -> int:
        profile = str(context or "").split(":", 1)[0].lower()
        targets = self._profiles.get(profile) or []
        providers: List[str] = []
        for target in targets:
            provider = str(target.get("provider") or "").lower()
            if provider and provider not in providers:
                providers.append(provider)
        if not providers:
            return 0
        return providers.index(key) if key in providers else len(providers) + 1

    def _score(self, key: str, s: _Stat, context: Optional[str]) -> float:
        quality = self._quality_cell(s, key, context)
        health = self._health_cell(s, context)
        q = self._rng.betavariate(max(quality.alpha, 1e-3), max(quality.beta, 1e-3))
        lat = 1.0 - self._latency_norm(s)
        succ = self._rng.betavariate(max(health.alpha, 1e-3), max(health.beta, 1e-3))
        wq, wl, ws = self._weights(context)
        tier = self._tier(key)
        tier_bonus = (4 - min(tier, 3)) * 0.05
        priority = max(1, int(self._priors.get(key, {}).get("priority", 10)))
        priority_bonus = 0.04 / priority
        cost_class = str(self._priors.get(key, {}).get("cost_class", ""))
        cost_penalty = float(self._cost_penalties.get(cost_class, 0.0))
        return (wq * q + wl * lat + ws * succ + tier_bonus + priority_bonus
                + self._profile_bonus(key, context) - cost_penalty
                - self._quota_penalty(s) - self._inflight_penalty(key))

    def order_models(self, provider: str, models: List[str],
                     context: Optional[str] = None,
                     preferred_model: Optional[str] = None,
                     strict: bool = False) -> List[str]:
        """Ordena modelos do mesmo provedor por qualidade/latência aprendidas."""
        available = [str(model) for model in models if str(model)]
        if preferred_model and strict:
            return [preferred_model]
        if preferred_model and preferred_model not in available:
            available.insert(0, preferred_model)

        def score(model: str) -> Tuple[int, float]:
            model_key = self._model_key(provider, model) or model
            stat = self._model_stats.setdefault(model_key, _ModelStat())
            cell = self._model_quality_cell(provider, model_key, context)
            quality = self._rng.betavariate(max(cell.alpha, 1e-3), max(cell.beta, 1e-3))
            latency = 0.5 if stat.latency_ms is None else 1.0 - _clamp(
                (stat.latency_ms - _LAT_FLOOR_MS) / (_LAT_CEIL_MS - _LAT_FLOOR_MS), 0.0, 1.0
            )
            config = self._model_config(provider, model_key)
            priority = max(1, int(config.get("priority", 10)))
            pinned = 0 if preferred_model == model else 1
            health = (stat.ok + 2.8) / (stat.ok + stat.err + 4.0)
            return pinned, -(0.60 * quality + 0.20 * latency + 0.15 * health + 0.05 / priority)

        return sorted(available, key=score)

    def _capabilities(self, key: str) -> set:
        bruto = (self._priors.get(key) or {}).get("capabilities") or []
        if isinstance(bruto, str):
            bruto = [bruto]
        return {str(item).strip().lower() for item in bruto if str(item).strip()}

    def order(self, providers: List[Any], context: Optional[str] = None,
              selection=None, requires: Optional[Any] = None) -> List[Any]:
        """Ordena os provedores por score (melhor primeiro). Quem está em
        cooldown vai pro fim — não some, porque se todo mundo cair ainda
        tentamos. O `last_resort` fica sempre por último.

        `requires` remove de vez quem não declara a capacidade que o turno
        exige (uma imagem anexada, por exemplo): tentar quem não enxerga só
        gasta uma rodada e volta erro no meio da resposta.

        Identifica cada provedor por `.name`, caindo no nome da classe.
        """
        exigidas = {str(item).strip().lower() for item in (requires or []) if str(item).strip()}
        if exigidas:
            capazes = [
                p for p in providers
                if exigidas <= self._capabilities(getattr(p, "name", type(p).__name__))
            ]
            # Sem ninguém capaz, o host precisa decidir o que dizer — melhor
            # devolver vazio do que fingir que qualquer um serve.
            providers = capazes
        with self._lock:
            now = time.time()
            selected = coerce_selection(selection)

            def rank(p) -> Tuple[int, int, int, int, float]:
                key = getattr(p, "name", type(p).__name__)
                if key == self._last_resort:
                    return (2, 99, 99, 1, 0.0)
                s = self._stat(key)
                cooled = 1 if s.cooldown_until > now else 0
                pinned = 0 if selected.provider == key else 1
                tier = self._tier(key)
                tier_bucket = tier if self._strategy == "tier" and selected.provider is None else 0
                profile_bucket = self._profile_bucket(key, context)
                # score negativo pra ordenar desc num sort asc
                return (cooled, pinned, tier_bucket, profile_bucket, -self._score(key, s, context))

            ordered = sorted(providers, key=rank)
            if selected.mode == "strict":
                return [
                    p for p in ordered
                    if getattr(p, "name", type(p).__name__) == selected.provider
                ]
            return ordered

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()
            self._model_stats.clear()
            self._inflight.clear()

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            now = time.time()
            out: Dict[str, Dict[str, Any]] = {}
            for key, s in self._stats.items():
                cd = max(0.0, s.cooldown_until - now)
                s.request_timestamps = [stamp for stamp in s.request_timestamps if now - stamp <= 60.0]
                out[key] = {
                    "status": s.last_status,
                    "ok": s.ok,
                    "err": s.err,
                    "latency_ms": round(s.latency_ms) if s.latency_ms else None,
                    "cooldown": round(cd, 1) if cd > 0 else 0,
                    "last_model": s.last_model,
                    "detail": s.last_detail,
                    "seconds_ago": round(now - s.last_ts, 1) if s.last_ts else None,
                    "inflight": self._inflight.get(key, 0),
                    "rpm_remaining": s.rpm_remaining,
                    "rpd_remaining": s.rpd_remaining,
                    "rpm_used": len(s.request_timestamps),
                    "quality_mean": round(sum(c.mean for c in s.quality.values()) / len(s.quality), 3) if s.quality else None,
                    "health_mean": round(sum(c.mean for c in s.health.values()) / len(s.health), 3) if s.health else None,
                    "quality_samples": sum(c.samples for c in s.quality.values()),
                    "health_samples": sum(c.samples for c in s.health.values()),
                    # Compatibilidade temporária com consumidores antigos.
                    "samples": sum(c.samples for c in s.quality.values()),
                    "models": {
                        model_key.split(":", 1)[1]: {
                            "ok": model_stat.ok,
                            "err": model_stat.err,
                            "latency_ms": round(model_stat.latency_ms) if model_stat.latency_ms else None,
                            "quality_mean": round(
                                sum(cell.mean for cell in model_stat.quality.values())
                                / len(model_stat.quality), 3
                            ) if model_stat.quality else None,
                            "quality_samples": sum(cell.samples for cell in model_stat.quality.values()),
                        }
                        for model_key, model_stat in self._model_stats.items()
                        if model_key.startswith(f"{key}:")
                    },
                }
            return out

    def dump(self) -> Dict[str, Any]:
        """Estado compacto pra persistir: só o que vale reaprender. Cooldown,
        status e cota ficam de fora porque são voláteis do processo."""
        with self._lock:
            providers = {
                key: {
                    "ok": s.ok, "err": s.err, "latency_ms": s.latency_ms,
                    "health": {c: [cell.alpha, cell.beta] for c, cell in s.health.items()},
                    "quality": {c: [cell.alpha, cell.beta] for c, cell in s.quality.items()},
                }
                for key, s in self._stats.items()
            }
            if self._model_stats:
                providers["__models__"] = {
                    key: {
                        "ok": stat.ok, "err": stat.err,
                        "latency_ms": stat.latency_ms,
                        "quality": {c: [cell.alpha, cell.beta] for c, cell in stat.quality.items()},
                    }
                    for key, stat in self._model_stats.items()
                }
            return providers

    def load(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            model_data = data.get("__models__") or {}
            for key, d in data.items():
                if key == "__models__":
                    continue
                if not isinstance(d, dict):
                    continue
                s = self._stat(key)
                s.ok = int(d.get("ok", 0))
                s.err = int(d.get("err", 0))
                s.latency_ms = d.get("latency_ms")
                # Dumps 0.1 usavam `cells` para uma mistura dominada por saúde.
                # Na migração, esse sinal vai para health; qualidade fica vazia.
                health_data = d.get("health")
                if health_data is None:
                    health_data = d.get("cells") or {}
                for c, ab in health_data.items():
                    try:
                        s.health[c] = _Cell(alpha=float(ab[0]), beta=float(ab[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
                for c, ab in (d.get("quality") or {}).items():
                    try:
                        s.quality[c] = _Cell(alpha=float(ab[0]), beta=float(ab[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
            for model_key, d in model_data.items():
                if not isinstance(d, dict):
                    continue
                stat = self._model_stats.setdefault(str(model_key), _ModelStat())
                stat.ok = int(d.get("ok", 0))
                stat.err = int(d.get("err", 0))
                stat.latency_ms = d.get("latency_ms")
                for context, ab in (d.get("quality") or {}).items():
                    try:
                        stat.quality[str(context)] = _Cell(float(ab[0]), float(ab[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
