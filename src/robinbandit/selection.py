"""Política explícita de seleção por request."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


_MODE_ALIASES = {
    # `auto` existia nas primeiras versões. Continua aceito somente para
    # compatibilidade; o nome canônico da seleção de provedores é Router.
    "auto": "router",
    "router": "router",
    "hybrid": "hybrid",
    "reinforced": "hybrid",
    "reforcado": "hybrid",
    "reforçado": "hybrid",
    "strict": "strict",
    "dedicated": "strict",
    "dedicado": "strict",
}


@dataclass(frozen=True)
class RouteSelection:
    """Escolha de provedor/modelo sem esconder a política de fallback."""

    mode: str = "router"
    provider: Optional[str] = None
    model: Optional[str] = None

    def __post_init__(self) -> None:
        normalized = _MODE_ALIASES.get(str(self.mode or "router").strip().lower())
        if normalized is None:
            raise ValueError(
                "selection mode deve ser router, hybrid/reinforced ou strict/dedicated"
            )
        object.__setattr__(self, "mode", normalized)
        provider = str(self.provider or "").strip().lower() or None
        model = str(self.model or "").strip() or None
        if normalized != "router" and provider is None:
            raise ValueError("seleção hybrid/strict exige provider")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)

    @classmethod
    def router(cls) -> "RouteSelection":
        return cls("router")

    @classmethod
    def auto(cls) -> "RouteSelection":
        """Alias legado; seleção automática de provedor se chama Router."""
        return cls.router()

    @classmethod
    def hybrid(cls, target: str) -> "RouteSelection":
        provider, model = cls._split_target(target)
        return cls("hybrid", provider, model)

    @classmethod
    def strict(cls, target: str) -> "RouteSelection":
        provider, model = cls._split_target(target)
        return cls("strict", provider, model)

    @staticmethod
    def _split_target(target: str):
        raw = str(target or "").strip()
        if not raw:
            raise ValueError("target não pode ser vazio")
        provider, sep, model = raw.partition(":")
        return provider, model if sep else None


def coerce_selection(value=None) -> RouteSelection:
    if value is None:
        return RouteSelection.router()
    if isinstance(value, RouteSelection):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw.lower() in {"auto", "router"}:
            return RouteSelection.router()
        return RouteSelection.hybrid(raw)
    if isinstance(value, dict):
        target = value.get("target")
        provider = value.get("provider")
        model = value.get("model")
        if target and not provider:
            provider, model_from_target = RouteSelection._split_target(target)
            model = model or model_from_target
        return RouteSelection(value.get("mode", "router"), provider, model)
    raise TypeError("selection deve ser RouteSelection, string, dict ou None")
