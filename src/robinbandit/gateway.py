"""Fachada configurável para agentes universais e para o Sentury."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import RobinConfig
from .router import ProviderRouter
from .selection import RouteSelection


class RobinGateway:
    """API estável do plug-in, sem conceitos de UI vazando para o router."""

    backend_name = "robinbandit"

    def __init__(self, config: RobinConfig, router: Optional[ProviderRouter] = None):
        self.config = config
        self.router = router or ProviderRouter(
            providers=config.providers,
            weights=config.weights,
            last_resort=config.last_resort,
            strategy=config.strategy,
            cost_penalties=config.cost_penalties,
            profiles=config.profiles,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RobinGateway":
        return cls(RobinConfig.from_yaml(path))

    def context(self, complexity: Optional[str] = None,
                profile: Optional[str] = None,
                context: Optional[str] = None) -> str:
        if self.config.agent_mode == "sentury":
            complexity_key = str(complexity or context or "STANDARD").upper()
            profile_key = str(profile or "").strip().lower()
            return f"{profile_key}:{complexity_key}" if profile_key else complexity_key
        return str(context or complexity or "default")

    def selection(self, mode: str = "router", target: Optional[str] = None) -> RouteSelection:
        normalized = str(mode or "router").strip().lower()
        if normalized in {"auto", "router"}:
            return RouteSelection.router()
        if not target:
            raise ValueError(f"modo {mode} exige provider ou provider:model")
        if normalized in {"hybrid", "reinforced", "reforcado", "reforçado"}:
            return RouteSelection.hybrid(target)
        if normalized in {"strict", "dedicated", "dedicado"}:
            return RouteSelection.strict(target)
        raise ValueError(f"modo de seleção desconhecido: {mode}")

    def order(self, providers: List[Any], complexity: Optional[str] = None,
              profile: Optional[str] = None, *, context: Optional[str] = None,
              selection=None, requires: Optional[Any] = None) -> List[Any]:
        return self.router.order(
            providers,
            context=self.context(complexity, profile, context),
            selection=selection,
            requires=requires,
        )

    def record_success(self, key: str, latency_ms: float, model: Optional[str] = None,
                       complexity: Optional[str] = None,
                       profile: Optional[str] = None, *,
                       context: Optional[str] = None) -> None:
        self.router.record_success(
            key, latency_ms, model=model,
            context=self.context(complexity, profile, context),
        )

    def record_failure(self, key: str, kind: str,
                       complexity: Optional[str] = None,
                       detail: Optional[str] = None,
                       profile: Optional[str] = None, *,
                       context: Optional[str] = None,
                       model: Optional[str] = None) -> None:
        self.router.record_failure(
            key, kind, context=self.context(complexity, profile, context),
            detail=detail, model=model,
        )

    def reward_quality(self, key: str, complexity: Optional[str], good: bool,
                       profile: Optional[str] = None, *,
                       context: Optional[str] = None,
                       model: Optional[str] = None) -> None:
        self.router.reward_quality(
            key, self.context(complexity, profile, context), good, model=model
        )

    def order_models(self, key: str, models: List[str],
                     complexity: Optional[str] = None,
                     profile: Optional[str] = None, *,
                     context: Optional[str] = None,
                     preferred_model: Optional[str] = None,
                     strict: bool = False) -> List[str]:
        return self.router.order_models(
            key, models, self.context(complexity, profile, context),
            preferred_model=preferred_model, strict=strict,
        )

    def record_quota(self, key: str, rpm_remaining: Optional[int] = None,
                     rpd_remaining: Optional[int] = None) -> None:
        self.router.record_quota(key, rpm_remaining, rpd_remaining)

    def record_model_failure(self, key: str, model: str) -> None:
        self.router.record_model_failure(key, model)

    def begin(self, key: str) -> None:
        self.router.begin(key)

    def end(self, key: str) -> None:
        self.router.end(key)

    def reset(self) -> None:
        self.router.reset()

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return self.router.snapshot()

    def dump(self) -> Dict[str, Any]:
        return self.router.dump()

    def load(self, data: Dict[str, Any]) -> None:
        self.router.load(data)

    # --- Persistencia do aprendizado ---------------------------------------
    # O host nao precisa saber ONDE isto mora. Antes ele sabia, e o resultado
    # foi o aprendizado depender de um Redis que a instalacao local nao tem.

    def gravar_aprendizado(self) -> bool:
        """Guarda o que foi medido nesta maquina."""
        from . import estado

        return estado.salvar(self.dump())

    def recuperar_aprendizado(self) -> bool:
        """Recarrega o que foi medido antes, se ainda valer. Devolve se achou."""
        from . import estado

        guardado = estado.carregar()
        if not guardado:
            return False
        self.load(guardado)
        return True

    def esquecer_aprendizado(self) -> bool:
        """Apaga o que foi medido. Para quando as chaves ou os planos mudaram
        e o que foi medido antes passou a descrever outro mundo."""
        from . import estado

        self.reset()
        return estado.esquecer()
