"""Cofre local de segredos do RobinBandit."""
import json
import os
import threading
import ctypes
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
_PATH_ENV = "ROBINBANDIT_VAULT_PATH"
_WINDOWS = os.name == "nt"
_CABECALHO = b"ROBINBANDIT-DPAPI-1\n"
_AVISOU = False


class CofreInvalido(ValueError):
    """Uma leitura inválida impede sobrescrever os segredos existentes."""


def _dpapi(conteudo: bytes, proteger: bool) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    funcao = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    funcao.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    funcao.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(conteudo)
    entrada = Blob(len(conteudo), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    saida = Blob()
    # Sem escopo de máquina: só a conta que gravou pode abrir o cofre.
    if not funcao(ctypes.byref(entrada), None, None, None, None, 1, ctypes.byref(saida)):
        raise CofreInvalido("Não foi possível proteger ou abrir o cofre com a conta do Windows.")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def _avisar_sem_protecao() -> None:
    global _AVISOU
    if not _AVISOU:
        logging.getLogger(__name__).warning("Cofre sem criptografia: DPAPI está disponível só no Windows.")
        _AVISOU = True


def _trocar(caminho: Path, conteudo: bytes) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(f".{caminho.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with tmp.open("wb") as arquivo:
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.chmod(tmp, 0o600)
        tmp.replace(caminho)
    finally:
        tmp.unlink(missing_ok=True)

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


def _carregar() -> Dict[str, Any]:
    with _LOCK:
        return _ler_cofre()


def _ler_cofre() -> Dict[str, Any]:
    caminho = caminho_do_cofre()
    if not caminho.exists():
        return {}
    try:
        bruto = caminho.read_bytes()
        protegido = bruto.startswith(_CABECALHO)
        if protegido:
            if not _WINDOWS:
                raise CofreInvalido("Este cofre usa DPAPI; abra-o na conta do Windows que o gravou.")
            conteudo = _dpapi(bruto[len(_CABECALHO):], False)
        else:
            conteudo = bruto
        dados = json.loads(conteudo.decode("utf-8"))
        if not isinstance(dados, dict):
            raise CofreInvalido("O cofre não contém um objeto de segredos válido.")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CofreInvalido("Não foi possível ler o cofre; o arquivo foi preservado.") from exc
    backup = caminho.with_name(caminho.name + ".bak")
    if protegido:
        backup.unlink(missing_ok=True)
    elif _WINDOWS:
        # A cópia fica até uma leitura posterior confirmar o arquivo protegido.
        if not backup.exists():
            _trocar(backup, bruto)
        _gravar(dados)
    else:
        _avisar_sem_protecao()
    return dados


def _gravar(dados: Dict[str, Any]) -> None:
    caminho = caminho_do_cofre()
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2).encode("utf-8")
    if _WINDOWS:
        conteudo = _CABECALHO + _dpapi(conteudo, True)
    else:
        _avisar_sem_protecao()
    _trocar(caminho, conteudo)


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
