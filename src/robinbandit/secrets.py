"""Cofre de segredos do RobinBandit.

O catálogo de contas ([accounts.py](accounts.py)) guarda o NOME da variável. Isso
resolve metade do problema: dá pra falar de conta sem falar de segredo. A outra
metade é a pergunta do usuário — *como eu ponho a chave sem vazar nada?* Pedir
JSON no `.env` não serve: obriga a editar arquivo no servidor, e o `.env` é
território do deploy.

Então o cofre é um arquivo próprio, separado do `.env`, com três regras que o
código inteiro respeita:

  1. **O valor nunca sai.** Nenhum endpoint, log, payload ou repr devolve a
     chave. Só devolve se existe, de onde veio e os 4 últimos caracteres — o
     suficiente pra você reconhecer qual chave está lá, inútil pra quem rouba.
  2. **Só nome conhecido entra.** Gravar variável arbitrária a partir de um
     POST viraria porta pra sobrescrever config do processo. O cofre aceita
     apenas as variáveis que o catálogo declara.
  3. **Arquivo só do dono** (0600 onde o SO suporta), fora do controle de versão.

Precedência de leitura: **cofre > ambiente > settings**. O cofre vem primeiro
porque é a ação humana mais recente e explícita — se o painel gravasse e o env
antigo continuasse vencendo, o usuário mudaria a chave e nada aconteceria, que
é o pior tipo de falha: silenciosa. Em troca, o painel sempre mostra a origem.
"""
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
_PATH_ENV = "ROBINBANDIT_VAULT_PATH"

def _padrao() -> Path:
    """A casa do usuário, e só ela.

    Nasceu em `./.sentury/cofre.json`: relativo ao diretório de onde o processo
    subiu, dentro do projeto. Um arquivo de segredos dentro de um repositório
    espera por um `git add .` distraído — e mudar de terminal abria outro
    cofre. Aqui não há caminho relativo nenhum: quem quiser outro lugar aponta
    `ROBINBANDIT_VAULT_PATH`, que é como se faz em container.

    Função, não constante, porque o `HOME` do processo pode mudar entre o
    import e o uso (teste, serviço, troca de usuário).
    """
    home = os.environ.get("ROBINBANDIT_HOME") or str(Path.home() / ".robinbandit")
    return Path(home) / "cofre.json"


def configure(metadata: Optional[Dict[str, Any]] = None) -> None:
    """Aplica a referência de caminho declarada no YAML, nunca um segredo."""
    global _PATH_ENV
    configured = str((metadata or {}).get("vault_path_env") or "").strip()
    _PATH_ENV = configured or "ROBINBANDIT_VAULT_PATH"


def caminho_do_cofre() -> Path:
    """Onde o cofre vive. `ROBINBANDIT_VAULT_PATH` é o nome universal;
    `SENTURY_VAULT_PATH` permanece compatível com instalações existentes.
    montado, que é como se faz em container."""
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
        # Cofre corrompido não pode derrubar o boot: o resto do sistema ainda
        # lê do ambiente. O painel mostra "não configurada" e o usuário regrava.
        return {}
    # Valor pode ser string (formato antigo, uma chave ou CSV) ou lista (formato
    # novo, várias chaves). Converter para str aqui transformaria a lista no
    # texto "['k1', 'k2']" e o segredo viraria lixo.
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
    """Cada chave com o que se sabe dela: valor, apelido e se é crédito pago.

    Três formas convivem no disco, e todas precisam continuar sendo lidas:
    a antiga (uma string, possivelmente CSV), a lista de strings, e esta —
    lista de objetos. Rotacionar chave era adivinhar qual das quatro era a
    paga olhando quatro dicas iguais de quatro caracteres.
    """
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
    """Quebra o CSV da forma antiga. O CSV existe porque é assim que o
    KeyRotator recebe várias chaves da mesma conta."""
    if isinstance(bruto, str):
        return [p.strip() for p in bruto.split(",") if p.strip()]
    return [str(bruto).strip()] if bruto else []


def _lista(bruto: Any) -> List[str]:
    """Só os valores, que é o que os provedores consomem."""
    return [e["valor"] for e in _entradas(bruto)]


def _lista_legada(bruto: Any) -> List[str]:
    """Aceita a forma antiga (uma string, possivelmente CSV) e a nova (lista).
    O CSV existe porque é assim que o KeyRotator recebe várias chaves da mesma
    conta; quebrar isso na leitura invalidaria cofres já gravados."""
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
    """Grava a chave e devolve as chaves resultantes.

    `adicionar` acrescenta em vez de substituir: uma conta pode ter várias
    chaves e o rotador alterna entre elas quando uma bate a cota.

    `semente` é o que essa variável vale HOJE no ambiente. Sem ela, adicionar a
    terceira chave a uma variável que vem do `.env` com duas apagaria as duas:
    o cofre vence o ambiente, então gravar só a nova deixaria a conta com uma
    chave só, em silêncio.
    """
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
        # Sem duplicar: a mesma chave duas vezes faria o rotador alternar entre
        # ela e ela mesma depois de bater a cota.
        for k in novas:
            if k in conhecidos:
                continue
            atuais.append({"valor": k, "nome": str(rotulo or "").strip(), "paga": bool(paga)})
            conhecidos.add(k)
        dados[chave] = atuais
        _gravar(dados)
        return [e["valor"] for e in atuais]


def remover_chave(nome: str, indice: int) -> bool:
    """Tira UMA das chaves da variável. Índice em vez do valor porque o valor
    nunca sai daqui — o painel só conhece a posição e a dica."""
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
    """Dá nome a uma chave, ou marca que ela é crédito pago.

    Quatro chaves do mesmo provedor apareciam como quatro dicas de quatro
    caracteres. Sem nome, rotacionar era adivinhar qual sair — e a paga era
    indistinguível das gratuitas na hora de decidir.
    """
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
    """A parte mostrável de um segredo: só o fim, e só se sobrar o que esconder.

    Chave curta demais não ganha dica — mostrar 4 de 8 caracteres entrega
    metade do segredo."""
    v = str(valor or "").strip()
    return f"...{v[-4:]}" if len(v) >= 12 else ("..." if v else "")


def situacao(nome: str, do_ambiente: str = "") -> Dict[str, Any]:
    """Visão segura de uma variável: existe? veio de onde? quantas chaves tem e
    como cada uma termina? O valor nunca entra aqui."""
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
        # Várias chaves da mesma conta é o caso normal: o rotador alterna entre
        # elas quando uma bate a cota.
        # Nome e marca por chave: sem eles, rotacionar e escolher a paga era
        # comparar quatro dicas de quatro caracteres.
        "chaves": [
            {"i": i, "dica": dica(e["valor"]), "nome": e["nome"], "paga": e["paga"]}
            for i, e in enumerate(entradas)
        ],
    }
