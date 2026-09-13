"""Deixa a arte dos provedores legível no escuro, sem repintar a marca.

O painel e a landing são fundo escuro. Uma logo baixada de banco de ícones
costuma vir preta — e preto sobre `#0B0F14` não é uma cor discreta, é uma
mancha invisível. O mesmo vale para as cores de marca muito escuras: o roxo da
Fireworks tem contraste 2.09 contra o fundo, então a logo inteira some.

A regra aqui é uma só: **o que não se enxerga vira `currentColor`**. Assim a
peça herda a cor do texto de quem a coloca — creme no painel, creme na
landing — e as cores de marca que já aparecem bem ficam intocadas. Repintar a
logo colorida da Hugging Face de creme seria vandalismo; apagar o rosto dela
por ser cinza-escuro é só conserto.

    python scripts/normalizar-logos.py            # mostra o que faria
    python scripts/normalizar-logos.py --aplicar  # grava

Rode depois de soltar arquivos novos em src/robinbandit/assets/providers/.
É idempotente: rodar duas vezes não muda nada na segunda.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent / "src" / "robinbandit" / "assets" / "providers"

# O fundo contra o qual a arte é vista, nos dois lugares que a mostram.
FUNDO = "#0B0F14"

# Abaixo disto a forma deixa de ser distinguível do fundo. Não é o 4.5 de texto
# da WCAG: isto é arte, não parágrafo — 3.0 é o limite usado para componentes
# gráficos, e é onde o olho começa a reclamar.
MINIMO = 3.0

PRETO = re.compile(r"#000000\b|#000\b|\bblack\b|rgb\(\s*0\s*,\s*0\s*,\s*0\s*\)", re.I)
COR = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
DESENHO = ("path", "circle", "rect", "polygon", "ellipse", "polyline", "line")


def luminancia(hexa: str) -> float:
    h = hexa.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    canais = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contraste(a: str, b: str) -> float:
    la, lb = luminancia(a), luminancia(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def normalizar(texto: str) -> tuple[str, list[str]]:
    """Devolve o SVG corrigido e a lista do que foi feito."""
    notas: list[str] = []

    # 1. Preto declarado, em fill/stroke ou dentro de um style.
    if PRETO.search(texto):
        texto = PRETO.sub("currentColor", texto)
        notas.append("preto -> currentColor")

    # 2. Preto por omissão: sem fill no elemento e sem fill na raiz <svg>,
    #    o SVG pinta de preto. É o caso que não aparece em nenhuma busca por
    #    "#000" e mesmo assim entrega uma silhueta invisível.
    raiz_pinta = re.search(r"<svg[^>]*\bfill=", texto)
    orfas = [
        m for m in re.finditer(r"<(" + "|".join(DESENHO) + r")\b([^>]*?)(/?)>", texto)
        if "fill" not in m.group(2) and "class" not in m.group(2)
    ]
    if orfas and not raiz_pinta:
        texto = re.sub(
            r"<svg\b", '<svg fill="currentColor"', texto, count=1
        )
        notas.append(f"{len(orfas)} elemento(s) sem fill -> fill=currentColor na raiz")

    # 3. Cor de marca escura demais para o fundo em que ela vive.
    for cor in sorted(set(COR.findall(texto))):
        razao = contraste(cor, FUNDO)
        if razao < MINIMO:
            texto = re.sub(re.escape(cor) + r"\b", "currentColor", texto)
            notas.append(f"{cor} (contraste {razao:.2f}) -> currentColor")

    return texto, notas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aplicar", action="store_true", help="grava; sem isto só mostra")
    args = ap.parse_args()

    if not PASTA.is_dir():
        print(f"não encontrei {PASTA}", file=sys.stderr)
        return 1

    tocados = 0
    for arquivo in sorted(PASTA.glob("*.svg")):
        original = arquivo.read_text(encoding="utf-8")
        novo, notas = normalizar(original)

        if not notas or novo == original:
            continue

        tocados += 1
        print(f"\n{arquivo.name}")
        for nota in notas:
            print(f"   {nota}")

        if args.aplicar:
            arquivo.write_text(novo, encoding="utf-8")

    if not tocados:
        print("Nada a corrigir: toda a arte já aparece no escuro.")
        return 0

    if args.aplicar:
        print(f"\n{tocados} arquivo(s) gravado(s).")
    else:
        print(f"\n{tocados} arquivo(s) seriam alterados. Rode com --aplicar para gravar.")
        print("(`git diff` mostra o que mudou; `git checkout` desfaz.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
