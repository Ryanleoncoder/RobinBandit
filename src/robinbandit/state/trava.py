"""O bloqueio entre processos evita perder contadores compartilhados."""
import os
import time
from contextlib import contextmanager


@contextmanager
def bloquear(caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho.with_suffix(caminho.suffix + ".lock"), "a+b") as arquivo:
        if arquivo.seek(0, 2) == 0:
            arquivo.write(b"0")
            arquivo.flush()
        arquivo.seek(0)
        if os.name == "nt":
            import msvcrt
            prazo = time.monotonic() + 3
            while True:
                try:
                    msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= prazo:
                        raise
                    time.sleep(0.02)
        else:
            import fcntl
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            arquivo.seek(0)
            if os.name == "nt":
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)
