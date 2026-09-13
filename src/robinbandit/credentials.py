"""Pool de credenciais do RobinBandit: várias chaves do MESMO provedor,
rotacionadas pra multiplicar a cota grátis.

Ex.: GEMINI_API_KEY="k1,k2,k3" → quando k1 bate RPM/RPD, o provider tenta k2, k3.
3 chaves grátis = ~3x a cota. Round-robin entre chamadas espalha a carga (não
sobrecarrega uma chave só). Compartilhado pra não duplicar em cada provider e
sem importar chain.py (evita ciclo)."""
import itertools
import threading
from typing import List


def parse_keys(value) -> List[str]:
    """Aceita 1 chave ou CSV de chaves; retorna a lista limpa (sem vazios)."""
    return [k.strip() for k in str(value or "").split(",") if k.strip()]


def is_quota_error(exc: Exception) -> bool:
    """True quando o erro é de cota/crédito (429/quota/402/crédito) — o sinal pra
    PULAR pra próxima chave em vez de insistir na mesma."""
    s = str(exc).lower()
    return any(t in s for t in (
        "429", "too many requests", "rate limit", "rate_limit", "quota",
        "402", "insufficient", "credit", "payment", "balance", "billing",
    ))


class KeyRotator:
    """Guarda as chaves e um cursor round-robin thread-safe. `order()` devolve as
    chaves começando do próximo cursor — assim chamadas consecutivas usam chaves
    diferentes (espalha), mas todas continuam disponíveis pra failover."""

    def __init__(self, keys: List[str]):
        self.keys = keys or [""]
        self._counter = itertools.count()
        self._lock = threading.Lock()

    @property
    def has_multiple(self) -> bool:
        return len(self.keys) > 1

    def order(self) -> List[str]:
        if len(self.keys) == 1:
            return self.keys
        with self._lock:
            start = next(self._counter) % len(self.keys)
        return self.keys[start:] + self.keys[:start]
