"""Filas declarativas da apresentação, separadas do roteamento ativo."""
import json
import os
import threading
from pathlib import Path

from .trava import bloquear
from ..routing.classificacao import validar_contextos


def niveis():
    arquivo = Path(__file__).resolve().parent.parent / "assets" / "painel" / "niveis.json"
    return json.loads(arquivo.read_text(encoding="utf-8"))


def caminho():
    return Path(os.environ.get("ROBINBANDIT_HOME") or Path.home() / ".robinbandit") / "classificacao.json"


def validar_classificador(escolha, catalogo=None):
    if not isinstance(escolha, dict) or set(escolha) not in ({"tipo", "provedor", "modelo"}, {"tipo", "provedor", "modelo", "reservas"}):
        raise ValueError("Informe o tipo, o provedor e o modelo do classificador.")
    tipo, provedor, modelo = (escolha[k] for k in ("tipo", "provedor", "modelo"))
    if not all(isinstance(v, str) for v in (tipo, provedor, modelo)):
        raise ValueError("Configuração de classificador inválida.")
    reservas = escolha.get("reservas", [])
    if not isinstance(reservas, list) or len(reservas) > 5:
        raise ValueError("O classificador aceita uma LLM principal e até cinco reservas.")
    if tipo == "nenhum" and not provedor and not modelo and not reservas:
        return {"tipo": tipo, "provedor": "", "modelo": ""}
    modelo = modelo.strip()
    if (tipo != "llm" or not provedor or len(provedor) > 128 or not modelo
            or len(modelo) > 256 or any(ord(c) < 32 for c in provedor + modelo)):
        raise ValueError("Escolha um provedor e um ID de modelo para a LLM.")
    if catalogo is not None and (provedor not in catalogo or provedor == "fallback"
                               or catalogo[provedor].get("conta_de")):
        raise ValueError("Provedor inválido para o classificador.")
    resultado = {"tipo": tipo, "provedor": provedor, "modelo": modelo}
    vistos = {(provedor, modelo)}
    normalizadas = []
    for alvo in reservas:
        if not isinstance(alvo, dict) or set(alvo) != {"provedor", "modelo"}:
            raise ValueError("Reserva de classificador inválida.")
        reserva = validar_classificador({"tipo": "llm", **alvo}, catalogo)
        chave = (reserva["provedor"], reserva["modelo"])
        if chave in vistos:
            raise ValueError("O mesmo modelo não pode se repetir no classificador.")
        vistos.add(chave)
        normalizadas.append({k: reserva[k] for k in ("provedor", "modelo")})
    if normalizadas:
        resultado["reservas"] = normalizadas
    return resultado


def carregar():
    filas = {nivel["id"]: [] for nivel in niveis()}
    classificador = {"tipo": "nenhum", "provedor": "", "modelo": ""}
    contextos = {nivel: "" for nivel in filas}
    if caminho().exists():
        try:
            dados = json.loads(caminho().read_text(encoding="utf-8"))
            if not isinstance(dados, dict) or not isinstance(dados.get("filas"), dict):
                raise ValueError
            bruto = dados["filas"]
            if set(bruto) != set(filas):
                raise ValueError
            for fila in bruto.values():
                if not isinstance(fila, list) or len(fila) > 50:
                    raise ValueError
                if any(not isinstance(a, dict) or set(a) != {"provedor", "modelo"}
                       or not all(isinstance(a[k], str) and a[k].strip() for k in a) for a in fila):
                    raise ValueError
            filas.update(bruto)
            classificador = validar_classificador(dados.get("classificador", classificador))
            contextos = validar_contextos(dados.get("contextos", contextos))
        except (OSError, ValueError) as exc:
            raise ValueError("Não foi possível ler as filas de classificação. O arquivo foi preservado.") from exc
    return {"niveis": niveis(), "filas": filas, "classificador": classificador, "contextos": contextos,
            "modo": "configuracao", "classificador_conectado": False,
            "classificador_configurado": classificador["tipo"] == "llm",
            "execucao_disponivel": True}


def guardar(filas, catalogo, classificador=None, contextos=None):
    permitidos = {n["id"] for n in niveis()}
    if set(filas) != permitidos:
        raise ValueError("Informe os níveis declarados no painel.")
    for fila in filas.values():
        if len(fila) > 50:
            raise ValueError("Cada nível aceita até 50 modelos.")
        vistos = set()
        for alvo in fila:
            provedor, modelo = alvo["provedor"], alvo["modelo"].strip()
            if (provedor not in catalogo or provedor == "fallback"
                    or catalogo[provedor].get("conta_de") or not modelo or any(ord(c) < 32 for c in modelo)):
                raise ValueError("Modelo ou provedor inválido para a fila.")
            chave = (provedor, modelo)
            if chave in vistos:
                raise ValueError("O mesmo modelo não pode se repetir dentro de um nível.")
            vistos.add(chave)
            alvo["modelo"] = modelo
    alvo = caminho()
    with bloquear(alvo):
        # Um arquivo ilegível não é substituído por uma configuração vazia.
        atual = carregar()
        # Clientes que só editam as caixas não apagam a escolha do classificador.
        escolha = atual["classificador"] if classificador is None else validar_classificador(classificador, catalogo)
        preferencias = atual["contextos"] if contextos is None else validar_contextos(contextos)
        tmp = alvo.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"filas": filas, "classificador": escolha, "contextos": preferencias}, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(alvo)
    return carregar()
