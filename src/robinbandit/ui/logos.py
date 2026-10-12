"""A versão escura clareia o traço neutro sem alterar cores da marca."""
import xml.etree.ElementTree as ET


def para_fundo_escuro(conteudo: bytes) -> bytes:
    svg = ET.fromstring(conteudo)
    svg.set("color", "#EFE3D2")
    if svg.get("fill") is None:
        svg.set("fill", "#EFE3D2")
    for elemento in svg.iter():
        for atributo in ("fill", "stroke"):
            if elemento.get(atributo, "").strip().lower() in {"currentcolor", "black", "#000", "#000000"}:
                elemento.set(atributo, "#EFE3D2")
    return ET.tostring(svg, encoding="utf-8")
