"""Arranque do servidor: config, env, provedores, app e navegador."""
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


# Procurados nesta ordem, a partir do diretório atual e subindo.
NOMES = (
    "robinbandit.yaml",
    "robinbandit.yml",
    ".robinbandit.yaml",
    "config/robinbandit.yaml",
)


def carregar_env(partida: Optional[Path] = None, explicito: Optional[str] = None) -> Optional[Path]:
    """Lê um `.env` do projeto, sem sobrescrever variáveis já exportadas."""
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
    """Escreve mesmo em consoles legados com encoding limitado."""
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

    # Instalado por pip: tenta a configuração do usuário.
    from .config import caminho_do_catalogo, caminho_do_usuario

    do_usuario = caminho_do_usuario()
    if do_usuario.is_file():
        return do_usuario

    # Último caso: catálogo de fábrica empacotado.
    return caminho_do_catalogo()


def ordenar(config: RobinConfig, montados: Dict[str, Any]) -> List[Any]:
    """Ordena provedores montados, mantendo o último recurso por último."""
    from .accounts import account_config

    ultimo = (config.last_resort or "").strip().lower()
    escolhida = account_config.cadeia()

    if escolhida:
        escolhidos = [k for k in escolhida if k in montados and k != ultimo]
    else:
        escolhidos = [k for k in config.chain_order if k in montados and k != ultimo]
        escolhidos += [k for k in montados if k not in escolhidos and k != ultimo]

    # Último recurso fica fora da escolha normal.
    if ultimo in montados:
        escolhidos.append(ultimo)
    return [montados[k] for k in escolhidos]


def montar(config: RobinConfig, settings: Any = None) -> Tuple[Any, List[Any], RobinGateway]:
    """Devolve (app, provedores, gateway) prontos para servir."""
    from .providers import build_provider_set
    from .server import create_app

    gateway = RobinGateway(config)
    # Reaproveita aprendizado local antes do primeiro pedido.
    if gateway.recuperar_aprendizado():
        logger.info("RobinBandit: aprendizado anterior recuperado")

    # Janelas conhecidas de assinatura.
    from .state import janela

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
    """Linhas de status impressas ao iniciar o servidor."""
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
    """URL local usada para abrir o painel no navegador."""
    alvo = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    return f"http://{alvo}:{port}/painel"


def tem_tela() -> bool:
    """Detecta se faz sentido abrir navegador automaticamente."""
    if os.environ.get("ROBINBANDIT_SEM_NAVEGADOR"):
        return False
    # CI não deve abrir navegador.
    if os.environ.get("CI"):
        return False
    if sys.platform.startswith(("win", "darwin")):
        return True
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False


def abrir_quando_subir(host: str, port: int, espera: float = 15.0) -> None:
    """Abre o painel quando a porta começar a aceitar conexão."""
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

    from .ui._banner import _write_banner

    env = carregar_env(explicito=arquivo_env)
    caminho = achar_config(config)
    carregada = RobinConfig.from_yaml(caminho)
    app, provedores, gateway = montar(carregada)

    _write_banner(enabled=banner, color=color)
    if env:
        escrever(f"ambiente   {env}")
    for linha in resumo_da_partida(carregada, provedores, host, port, caminho):
        escrever(linha)

    # `--no-browser` continua tendo precedência.
    if navegador and tem_tela():
        abrir_quando_subir(host, port)

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        # Preserva aprendizado local inclusive no Ctrl+C.
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
