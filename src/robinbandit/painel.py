"""Compatibilidade para o caminho publico ``robinbandit.painel``.

O painel passou a viver em :mod:`robinbandit.ui.painel` na reorganizacao da
versao 0.5.0. Este modulo preserva o import usado por instalacoes existentes e
pela verificacao do wheel, sem duplicar a implementacao.
"""

from .ui.painel import PAGINA, PALETA, pasta_do_painel

__all__ = ["PAGINA", "PALETA", "pasta_do_painel"]
