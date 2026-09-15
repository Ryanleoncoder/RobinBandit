"""Infraestrutura minima para preservar imports anteriores a versao 0.5."""

from importlib import import_module
import sys


def alias(current_name: str, target_name: str):
    """Faz um modulo legado ser a mesma instancia do modulo reorganizado."""
    target = import_module(target_name, package=__package__)
    sys.modules[current_name] = target
    return target
