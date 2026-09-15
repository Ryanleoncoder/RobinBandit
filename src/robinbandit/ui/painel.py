"""Painel do RobinBandit: uma página, servida pelo próprio pacote.

Sete telas, porque tudo junto vira parede: o que está acontecendo, os provedores
por tier, os modelos de cada provedor, as contas e credenciais, as janelas de
assinatura, os tokens gastos e como plugar uma ferramenta.

A configuração mora aqui porque o RobinBandit roteia para qualquer agente. Se
ela vivesse na tela de quem o hospeda, só quem usasse aquele agente poderia
configurar.

Uma página HTML em vez de um app Node: o RobinBandit é um pacote Python, e pedir
uma toolchain JS para ver e ajustar um roteador seria trocar o problema de
lugar. Isso continua valendo — o que mudou é que o CSS e o JS deixaram de morar
dentro de uma string aqui e viraram arquivos em `assets/painel/`, do lado das
logos. Eram 64 KB que o editor tratava como texto, sem realce, sem linter e sem
teste possível; agora `painel.js` é um arquivo `.js`, e o erro aparece antes do
browser.

A página servida continua sendo uma só: o CSS e o JS são embutidos aqui, e
`GET /painel` responde o mesmo HTML de sempre, numa requisição só.
"""
from __future__ import annotations

from pathlib import Path

PALETA = {
    "bege": "#EFE3D2",
    "verde": "#5E7A61",
    "ambar": "#E0AF43",
    "preto": "#000000",
}

# Os marcadores ficam colados nas tags no `pagina.html`; quem monta repõe as
# quebras de linha das bordas. São comentários para o arquivo continuar sendo
# HTML válido de abrir no browser enquanto se edita.
_ESTILO = "/*ESTILO*/"
_TEXTOS = "/*TEXTOS*/"
_SCRIPT = "/*SCRIPT*/"


def pasta_do_painel() -> Path:
    """Os arquivos da página, dentro do pacote — não ao lado dele.

    Mesmo caminho das logos (`server.pasta_das_logos`): quem instala pelo pip
    precisa receber a página junto, e `package-data` no pyproject é o que
    carrega os dois.
    """
    return Path(__file__).resolve().parent.parent / "assets" / "painel"


def _ler(nome: str) -> str:
    """Lê um arquivo do painel.

    O `encoding` é explícito de propósito. Sem ele, `read_text()` usa a
    codificação da máquina — cp1252 no Windows, UTF-8 no Linux — e os bytes de
    `ç`, `é` e `—` são decodificáveis nas duas: não estoura exceção, só entrega
    "histÃ³rico" para quem abrir a página. Só o JS tem 125 acentos.
    """
    return (pasta_do_painel() / nome).read_text(encoding="utf-8")


def _embutir(template: str, marcador: str, conteudo: str, fechamento: str) -> str:
    """Coloca CSS ou JS dentro da página.

    `replace` e não `format`: o CSS e o JS têm 375 chaves entre os dois, e
    qualquer uma delas faria `format` explodir ou, pior, comer o conteúdo.
    """
    if template.count(marcador) != 1:
        raise RuntimeError(
            f"{marcador} aparece {template.count(marcador)}x em pagina.html; "
            "precisa ser exatamente uma."
        )
    # Dentro da string do módulo era impossível escrever a tag de fechamento no
    # meio do conteúdo. Em arquivo separado passou a ser possível, e o JS já
    # monta HTML concatenando string. O sintoma seria o bloco terminar cedo:
    # metade da página morta, resposta 200 e nenhum teste reclamando.
    if fechamento in conteudo.lower():
        raise RuntimeError(f"{fechamento!r} dentro do conteudo encerraria o bloco antes da hora")
    return template.replace(marcador, "\n" + conteudo.strip("\n") + "\n", 1)


def _montar() -> str:
    pagina = _ler("pagina.html")
    pagina = _embutir(pagina, _ESTILO, _ler("estilo.css"), "</style")
    # O dicionário vem antes do script que o usa: são dois <script> separados
    # para a tradução ficar num arquivo próprio, onde uma chave sem par salta
    # aos olhos.
    pagina = _embutir(pagina, _TEXTOS, _ler("textos.js"), "</script")
    pagina = _embutir(pagina, _SCRIPT, _ler("painel.js"), "</script")
    return pagina


PAGINA = _montar()


__all__ = ["PAGINA", "PALETA", "pasta_do_painel"]
