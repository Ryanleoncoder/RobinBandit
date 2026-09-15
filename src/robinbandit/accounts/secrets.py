"""Cofre local de segredos do RobinBandit."""
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
_PATH_ENV = "ROBINBANDIT_VAULT_PATH"

def _padrao() -> Path:
    """Caminho padrão do cofre na casa do usuário."""
    home = os.environ.get("ROBINBANDIT_HOME") or str(Path.home() / ".robinbandit")
    return Path(home) / "cofre.json"


def configure(metadata: Optional[Dict[str, Any]] = None) -> None:
    """Aplica a referência de caminho declarada no YAML, nunca um segredo."""
    global _PATH_ENV
    configured = str((metadata or {}).get("vault_path_env") or "").strip()
    _PATH_ENV = configured or "ROBINBANDIT_VAULT_PATH"


def caminho_do_cofre() -> Path:
    """Caminho efetivo do cofre."""
    bruto = (os.environ.get(_PATH_ENV)
             or os.environ.get("ROBINBANDIT_VAULT_PATH")
             or os.environ.get("SENTURY_VAULT_PATH") or "").strip()
    return Path(bruto).expanduser() if bruto else _padrao()


def _carregar() -> Dict[str, str]:
    caminho = caminho_do_cofre()
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}
    # Mantém compatibilidade com string, CSV, lista e lista de objetos.
    return {str(k): v for k, v in dados.items()} if isinstance(dados, dict) else {}


def _gravar(dados: Dict[str, str]) -> None:
    caminho = caminho_do_cofre()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(
        f".{caminho.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(json.dumps(dados, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)   # no-op prático no Windows, correto no Linux
    except OSError:
        pass
    tmp.replace(caminho)       # troca atômica: nunca existe cofre pela metade


def _entradas(bruto: Any) -> List[Dict[str, Any]]:
    """Normaliza formatos antigos e atuais de chaves no cofre."""
    saida: List[Dict[str, Any]] = []
    for item in (bruto if isinstance(bruto, list) else _partes(bruto)):
        if isinstance(item, dict):
            valor = str(item.get("valor") or "").strip()
            if valor:
                saida.append({
                    "valor": valor,
                    "nome": str(item.get("nome") or "").strip(),
                    "paga": bool(item.get("paga")),
                })
        else:
            for parte in _partes(item):
                saida.append({"valor": parte, "nome": "", "paga": False})
    return saida


def _partes(bruto: Any) -> List[str]:
    """Quebra o CSV da forma antiga."""
    if isinstance(bruto, str):
        return [p.strip() for p in bruto.split(",") if p.strip()]
    return [str(bruto).strip()] if bruto else []


def _lista(bruto: Any) -> List[str]:
    """Só os valores, que é o que os provedores consomem."""
    return [e["valor"] for e in _entradas(bruto)]


def _lista_legada(bruto: Any) -> List[str]:
    """Aceita forma antiga string/CSV e forma nova em lista."""
    if isinstance(bruto, list):
        itens = bruto
    else:
        itens = str(bruto or "").split(",")
    return [str(k).strip() for k in itens if str(k).strip()]


def listar(nome: str) -> List[str]:
    """As chaves de uma variável, uma a uma."""
    return _lista(_carregar().get(str(nome or "").strip()))


def ler(nome: str) -> str:
    """O valor no formato que os provedores consomem: CSV, que o `parse_keys`
    já sabe dividir."""
    return ",".join(listar(nome))


def guardar(nome: str, valor: str, permitidos: Optional[List[str]] = None,
            adicionar: bool = False, semente: str = "",
            rotulo: str = "", paga: bool = False) -> List[str]:
    """Grava uma chave e devolve a lista resultante."""
    chave = str(nome or "").strip()
    if not chave:
        raise ValueError("nome da variável vazio.")
    if permitidos is not None and chave not in permitidos:
        raise ValueError(f"variável '{chave}' não pertence a nenhum provedor conhecido.")
    novas = _lista(valor)
    if not novas:
        raise ValueError("valor vazio. Para remover, use a remoção explícita.")

    with _LOCK:
        dados = _carregar()
        atuais = _entradas(dados.get(chave)) if adicionar else []
        if adicionar and not atuais:
            atuais = _entradas(semente)   # preserva o que o ambiente já tinha
        conhecidos = {e["valor"] for e in atuais}
        # Evita duplicar a mesma chave.
        for k in novas:
            if k in conhecidos:
                continue
            atuais.append({"valor": k, "nome": str(rotulo or "").strip(), "paga": bool(paga)})
            conhecidos.add(k)
        dados[chave] = atuais
        _gravar(dados)
        return [e["valor"] for e in atuais]


def remover_chave(nome: str, indice: int) -> bool:
    """Remove uma chave por índice, sem expor o valor."""
    chave = str(nome or "").strip()
    with _LOCK:
        dados = _carregar()
        atuais = _entradas(dados.get(chave))
        if not (0 <= indice < len(atuais)):
            return False
        atuais.pop(indice)
        if atuais:
            dados[chave] = atuais
        else:
            dados.pop(chave, None)
        _gravar(dados)
        return True


def descrever_chave(nome: str, indice: int, rotulo: Optional[str] = None,
                    paga: Optional[bool] = None) -> bool:
    """Dá nome a uma chave ou marca que ela é crédito pago."""
    chave = str(nome or "").strip()
    with _LOCK:
        dados = _carregar()
        atuais = _entradas(dados.get(chave))
        if not (0 <= indice < len(atuais)):
            return False
        if rotulo is not None:
            atuais[indice]["nome"] = str(rotulo).strip()
        if paga is not None:
            atuais[indice]["paga"] = bool(paga)
        dados[chave] = atuais
        _gravar(dados)
        return True


def remover(nome: str) -> bool:
    with _LOCK:
        dados = _carregar()
        if str(nome or "").strip() not in dados:
            return False
        dados.pop(str(nome).strip())
        _gravar(dados)
        return True


def dica(valor: str) -> str:
    """Parte segura para exibir de um segredo."""
    v = str(valor or "").strip()
    return f"...{v[-4:]}" if len(v) >= 12 else ("..." if v else "")


def situacao(nome: str, do_ambiente: str = "") -> Dict[str, Any]:
    """Visão segura de uma variável, sem retornar o valor."""
    do_cofre = _entradas(_carregar().get(str(nome or "").strip()))
    entradas, origem = (
        (do_cofre, "cofre") if do_cofre
        else (_entradas(do_ambiente), "ambiente" if do_ambiente else "")
    )
    chaves = [e["valor"] for e in entradas]
    return {
        "configurada": bool(chaves),
        "origem": origem,
        "dica": dica(chaves[0]) if chaves else "",
        "chaves": [
            {"i": i, "dica": dica(e["valor"]), "nome": e["nome"], "paga": e["paga"]}
            for i, e in enumerate(entradas)
        ],
    }
