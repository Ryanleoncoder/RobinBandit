"""Monta os assets da landing page dentro de `site/`, para o preview local.

O `index.html` referencia `imagens/`, `logos/` e a logo na raiz do site. Esses
arquivos não moram aqui: as capturas estão em `docs/imagens/` (as mesmas que o
README usa) e as logos dos provedores em `src/robinbandit/assets/providers/`
(as mesmas que o painel serve). Manter uma segunda cópia versionada
significaria PNG duplicado envelhecendo em silêncio.

Quem junta tudo na hora de publicar é o `.github/workflows/pages.yml`. Este
script faz a mesma junção na sua máquina, para o Live Server (ou qualquer
servidor estático apontado para `site/`) mostrar a página inteira.

    python site/preview.py

O que ele copia está no .gitignore. Rode de novo quando trocar uma captura.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
RAIZ = SITE.parent

# destino no site  ->  origem no repositório
COPIAS = [
    ("imagens", RAIZ / "docs" / "imagens", "*.png"),
    ("logos", RAIZ / "src" / "robinbandit" / "assets" / "providers", "*.svg"),
]


def main() -> int:
    faltando = []

    for destino_nome, origem, padrao in COPIAS:
        if not origem.is_dir():
            faltando.append(str(origem))
            continue

        destino = SITE / destino_nome
        destino.mkdir(exist_ok=True)

        arquivos = sorted(origem.glob(padrao))
        for arquivo in arquivos:
            shutil.copy2(arquivo, destino / arquivo.name)
        print(f"{destino_nome}/: {len(arquivos)} arquivos de {origem.name}/")

    logo = RAIZ / "assets" / "robinbandit_logo1.png"
    if logo.is_file():
        shutil.copy2(logo, SITE / logo.name)
        print(f"{logo.name}: copiada para a raiz do site")
    else:
        faltando.append(str(logo))

    if faltando:
        print("\nNão encontrei:", *faltando, sep="\n  ")
        print("\nRode a partir do repositório clonado.")
        return 1

    print(f"\nPronto. Aponte o servidor estático para {SITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
