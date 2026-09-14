"""Sobe o RobinBandit como servidor: endpoint OpenAI, painel e configuração.

O pacote já tinha tudo — router, provedores, app FastAPI, painel — e nenhuma
porta de entrada. Quem clonava tinha que escrever o `uvicorn.run` à mão para
ver a própria página.

Chamava-se `servir.py`, ao lado de `server.py`, e ninguém tinha como adivinhar
qual era qual. A divisão é esta: `server.py` monta o app FastAPI, `__main__.py`
é a linha de comando, e aqui é o arranque — achar o YAML, carregar o `.env`,
montar os provedores e entregar tudo de pé.

Nada de caminho fixo aqui. O YAML é procurado a partir de onde a pessoa está,
porque cada instalação tem a sua própria disposição de pastas.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import RobinConfig
from .gateway import RobinGateway

logger = logging.getLogger(__name__)


# Procurados nesta ordem, a partir do diretório atual e subindo. Nomes do
# próprio RobinBandit, de propósito: um agente que queira ser encontrado assim
# chama o arquivo dele de `robinbandit.yaml`, e nenhum nome de agente
# específico entra aqui.
NOMES = (
    "robinbandit.yaml",
    "robinbandit.yml",
    ".robinbandit.yaml",
    "config/robinbandit.yaml",
)


def carregar_env(partida: Optional[Path] = None, explicito: Optional[str] = None) -> Optional[Path]:
    """Lê um `.env` do projeto, sem nunca escrever nele.

    Sozinho, o RobinBandit não tem quem carregue as chaves por ele: dentro do
    Sentury quem faz isso são as Settings do host. Rodado direto, sem isto,
    `serve` sobe com o punhado de provedores que não pede chave e a pessoa não
    entende por quê.

    O que já está no ambiente ganha do arquivo — quem exportou a variável na
    mão estava dizendo alguma coisa.
    """
    if explicito:
        alvo = Path(explicito).expanduser()
        if not alvo.is_file():
            raise FileNotFoundError(f".env não encontrado: {alvo}")
        return _aplicar_env(alvo)

    origem = (partida or Path.cwd()).resolve()
    for pasta in (origem, *origem.parents):
        alvo = pasta / ".env"
        if alvo.is_file():
            break
    else:
        return None
    return _aplicar_env(alvo)


def _aplicar_env(alvo: Path) -> Optional[Path]:
    try:
        linhas = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for linha in linhas:
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        nome, _, valor = limpa.partition("=")
        nome = nome.strip().removeprefix("export ").strip()
        if not nome or nome in os.environ:
            continue
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        os.environ[nome] = valor
    return alvo


def escrever(linha: str) -> None:
    """Console legado do Windows não encodes acento; trocar a frase por uma
    exceção seria pior do que trocar o acento por `?`."""
    try:
        print(linha)
    except UnicodeEncodeError:
        codificacao = getattr(sys.stdout, "encoding", None) or "ascii"
        print(linha.encode(codificacao, errors="replace").decode(codificacao))


def achar_config(explicito: Optional[str] = None) -> Path:
    """Descobre qual YAML usar, sem nunca supor a pasta de ninguém."""
    if explicito:
        alvo = Path(explicito).expanduser()
        if not alvo.exists():
            raise FileNotFoundError(f"config não encontrada: {alvo}")
        return alvo

    do_ambiente = os.environ.get("ROBINBANDIT_CONFIG")
    if do_ambiente:
        return achar_config(do_ambiente)

    partida = Path.cwd().resolve()
    for pasta in (partida, *partida.parents):
        for nome in NOMES:
            candidato = pasta / nome
            if candidato.is_file():
                return candidato

    # Instalado por pip: o repositório não está por perto, mas a config do
    # usuário pode bastar sozinha.
    from .config import caminho_do_catalogo, caminho_do_usuario

    do_usuario = caminho_do_usuario()
    if do_usuario.is_file():
        return do_usuario

    # Último caso: o catálogo de fábrica. `serve` sem nenhum arquivo tem que
    # subir — provedor sem chave no ambiente não é montado, então o padrão é
    # exatamente o que a máquina tem, e nada além.
    return caminho_do_catalogo()


def ordenar(config: RobinConfig, montados: Dict[str, Any]) -> List[Any]:
    """Põe os provedores na ordem da cadeia, com o último recurso por último.

    Há duas cadeias possíveis, e elas não significam a mesma coisa:

    * a do YAML (`chain_order`) diz **ordem**. Quem foi configurado e ficou de
      fora dela entra depois, em vez de sumir sem aviso — esquecer um nome na
      lista não pode desligar uma chave que a pessoa cadastrou.
    * a gravada pelo painel ou pela CLI diz **participação**. Ali alguém clicou
      em "tirar da cadeia", e quem foi tirado não pode voltar pela porta dos
      fundos.

    Sem essa distinção, `provedores desligar X` gravava o arquivo, respondia
    "vale no próximo arranque", e o provedor subia do mesmo jeito.
    """
    from . import account_config

    ultimo = (config.last_resort or "").strip().lower()
    escolhida = account_config.cadeia()

    if escolhida:
        escolhidos = [k for k in escolhida if k in montados and k != ultimo]
    else:
        escolhidos = [k for k in config.chain_order if k in montados and k != ultimo]
        escolhidos += [k for k in montados if k not in escolhidos and k != ultimo]

    # O último recurso não participa dessa escolha: ele existe para o caso de
    # todo o resto falhar, e ficar sem ele é ficar sem resposta nenhuma.
    if ultimo in montados:
        escolhidos.append(ultimo)
    return [montados[k] for k in escolhidos]


def montar(config: RobinConfig, settings: Any = None) -> Tuple[Any, List[Any], RobinGateway]:
    """Devolve (app, provedores, gateway) prontos para servir."""
    from .providers import build_provider_set
    from .server import create_app

    gateway = RobinGateway(config)
    # O que foi medido nesta máquina volta antes do primeiro pedido; sem isto
    # a exploração inicial é paga de novo a cada restart.
    if gateway.recuperar_aprendizado():
        logger.info("RobinBandit: aprendizado anterior recuperado")

    # Quem tem bloco de uso por assinatura, e de quantas horas.
    from . import janela

    gateway.router.declarar_janelas(janela.de_assinatura(config))

    provedores = ordenar(config, build_provider_set(config, settings))
    app = create_app(provedores, gateway.router, config=config)
    return app, provedores, gateway


def resumo_da_partida(
    config: RobinConfig,
    provedores: List[Any],
    host: str,
    port: int,
    caminho: Path,
) -> List[str]:
    """O que subiu, e por que a lista não é o catálogo inteiro.

    Provedor sem chave não é montado — silenciosamente, o que é certo em
    runtime e péssimo na primeira vez. Quem acabou de instalar precisa ver que
    faltou a variável, não uma lista curta sem explicação.
    """
    dentro = [getattr(p, "name", "?") for p in provedores]
    de_fora = [k for k in config.providers if k not in dentro]
    linhas = [
        f"config     {caminho}",
        f"no ar      {len(dentro)} de {len(config.providers)}: {', '.join(dentro)}",
    ]
    if de_fora:
        linhas.append(f"sem chave  {len(de_fora)}: {', '.join(sorted(de_fora))}")
    linhas += [
        "",
        f"painel     http://{host}:{port}/painel",
        f"chat       http://{host}:{port}/v1/chat/completions",
        f"responses  http://{host}:{port}/v1/responses",
        f"anthropic  http://{host}:{port}/v1/messages",
        "",
        "Para apontar seu agente para cá, a tela Conectar do painel gera a",
        "configuração pronta de Claude Code, Codex, Cline, OpenCode e curl.",
    ]
    return linhas


def endereco_do_painel(host: str, port: int) -> str:
    """A URL que se abre no navegador.

    `0.0.0.0` significa "escute em todas as interfaces" e não é um destino: o
    Windows recusa a conexão e o Linux só funciona por acidente. Quem expõe na
    rede ainda abre o painel na própria máquina.
    """
    alvo = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    return f"http://{alvo}:{port}/painel"


def tem_tela() -> bool:
    """Se existe alguém para ver um navegador abrir.

    Numa VPS, `robinbandit serve` deve subir e ficar quieto: tentar abrir
    navegador ali é, na melhor das hipóteses, ruído no log. Exigir que a pessoa
    lembre de `--no-browser` é passar para ela um trabalho que a máquina sabe
    fazer — dá para perguntar.

    Windows e macOS têm interface gráfica por definição. No resto, a sessão
    gráfica se anuncia por `DISPLAY` (X11) ou `WAYLAND_DISPLAY`; nenhum dos
    dois quer dizer terminal puro, que é o caso de ssh e container.
    """
    if os.environ.get("ROBINBANDIT_SEM_NAVEGADOR"):
        return False
    # CI abre navegador para ninguém e ainda deixa o processo pendurado.
    if os.environ.get("CI"):
        return False
    if sys.platform.startswith(("win", "darwin")):
        return True
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False


def abrir_quando_subir(host: str, port: int, espera: float = 15.0) -> None:
    """Abre o painel assim que a porta aceitar conexão.

    Abrir antes de o uvicorn atender daria "não foi possível conectar" na cara
    de quem acabou de rodar o comando — e o `uvicorn.run` é bloqueante, então
    não há um "depois" onde colocar isto. Uma thread espera a porta responder e
    só então chama o navegador.

    Falhar aqui nunca derruba o servidor: sem navegador (container, ssh, CI) o
    `webbrowser` só devolve False, e qualquer erro é engolido de propósito —
    o endereço já foi impresso, ninguém fica sem saída.
    """
    import socket
    import threading
    import webbrowser

    destino = ("127.0.0.1" if host in ("0.0.0.0", "::", "") else host, port)
    url = endereco_do_painel(host, port)

    def esperar() -> None:
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            with socket.socket() as s:
                s.settimeout(0.3)
                if s.connect_ex(destino) == 0:
                    try:
                        webbrowser.open(url)
                    except Exception:  # noqa: BLE001 - navegador nunca derruba o servidor
                        pass
                    return
            time.sleep(0.15)

    threading.Thread(target=esperar, daemon=True).start()


def servir(
    host: str = "127.0.0.1",
    port: int = 8000,
    config: Optional[str] = None,
    *,
    arquivo_env: Optional[str] = None,
    banner: bool = True,
    color: bool = True,
    navegador: bool = True,
) -> None:
    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "servir exige o extra: pip install 'robinbandit[server,yaml,providers]'"
        ) from None

    from ._banner import _write_banner

    env = carregar_env(explicito=arquivo_env)
    caminho = achar_config(config)
    carregada = RobinConfig.from_yaml(caminho)
    app, provedores, gateway = montar(carregada)

    _write_banner(enabled=banner, color=color)
    if env:
        escrever(f"ambiente   {env}")
    for linha in resumo_da_partida(carregada, provedores, host, port, caminho):
        escrever(linha)

    # `--no-browser` continua mandando; sem ele, a máquina responde sozinha se
    # há tela para abrir alguma coisa.
    if navegador and tem_tela():
        abrir_quando_subir(host, port)

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        # Inclusive no Ctrl+C: o que foi medido nesta sessao vale para a proxima.
        gateway.gravar_aprendizado()


__all__ = [
    "abrir_quando_subir",
    "tem_tela",
    "achar_config",
    "carregar_env",
    "endereco_do_painel",
    "montar",
    "ordenar",
    "resumo_da_partida",
    "servir",
]
