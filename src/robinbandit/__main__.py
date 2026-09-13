"""Entrada de `python -m robinbandit`.

A linha de comando em si mora em `cli.py`: ela cresceu de dois para cinco
comandos, e um arquivo chamado `__main__` é o lugar errado para procurar por
ela. Aqui fica só o que faz `python -m` funcionar.
"""
from .cli import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
