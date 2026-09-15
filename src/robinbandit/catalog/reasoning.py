"""Controles de raciocínio no nível do provedor.

O nível lógico de eficiência pertence ao agente consumidor. O Robin recebe o
valor já resolvido e traduz somente o payload/compatibilidade do provedor.
"""
from __future__ import annotations

from typing import Dict, Optional


_unsupported_control: set[str] = set()


def reasoning_control_allowed(model: str) -> bool:
    return model not in _unsupported_control


def mark_reasoning_control_rejected(model: str) -> None:
    _unsupported_control.add(model)


def is_reasoning_rejection(body: str) -> bool:
    text = (body or "").lower()
    if "reasoning" not in text and "thinking" not in text:
        return False
    return any(token in text for token in (
        "mandatory", "cannot be disabled", "not supported", "unsupported",
        "does not support", "invalid",
    ))


def build_reasoning_payload(effort: Optional[str]) -> Dict:
    if not effort:
        return {}
    if effort == "none":
        return {"reasoning": {"enabled": False, "exclude": True}}
    return {"reasoning": {"effort": effort, "exclude": False}}
