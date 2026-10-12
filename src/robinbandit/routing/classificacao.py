"""O contrato de classificação aceita apenas um nível declarado, sem inferir intenção."""
import json
from pathlib import Path


def contrato():
    pasta = Path(__file__).resolve().parent.parent / "assets" / "painel"
    niveis = json.loads((pasta / "niveis.json").read_text(encoding="utf-8"))
    dados = json.loads((pasta / "classificacao-llm.json").read_text(encoding="utf-8"))
    definicoes = "\n".join(f"{n['id']}: {n['criterio']}" for n in niveis)
    return {"instrucao": dados["instrucao"].format(niveis=definicoes),
            "rotulos": [n["id"] for n in niveis], "formato": "rotulo", "gemini": dados["gemini"]}


def validar_contextos(contextos):
    rotulos = contrato()["rotulos"]
    if not isinstance(contextos, dict) or set(contextos) != set(rotulos):
        raise ValueError("Informe um contexto para cada nível declarado.")
    if any(not isinstance(v, str) or len(v) > 2000
           or any(ord(c) < 32 and c not in "\n\r\t" for c in v) for v in contextos.values()):
        raise ValueError("Cada contexto aceita até 2000 caracteres de texto.")
    return dict(contextos)


def mensagens(pedido, contexto="", contextos=None):
    if not isinstance(pedido, str) or not pedido.strip() or not isinstance(contexto, str):
        raise ValueError("Informe o pedido e seu contexto como texto.")
    preferencias = validar_contextos(contextos) if contextos is not None else {n: "" for n in contrato()["rotulos"]}
    return [{"role": "system", "content": contrato()["instrucao"]},
            {"role": "user", "content": json.dumps({"pedido": pedido, "contexto": contexto,
                                                     "contextos_dos_niveis": preferencias}, ensure_ascii=False)}]


def validar_saida(texto):
    if not isinstance(texto, str) or texto.strip() not in contrato()["rotulos"]:
        raise ValueError("O classificador deve devolver somente um rótulo de nível válido.")
    return texto.strip()
