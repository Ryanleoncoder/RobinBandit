"""Linha de comando do RobinBandit."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from .ui._banner import _write_banner
from .ui.idioma import t
from .routing.router import ProviderRouter

SUBCOMANDOS = ("serve", "key", "providers", "state", "language")


# --------------------------------------------------------------------------
# apoio
# --------------------------------------------------------------------------

def _carregar_config(caminho: Optional[str] = None):
    """Carrega o mesmo YAML que o servidor usaria."""
    from .bootstrap import achar_config, carregar_env
    from .config import RobinConfig

    carregar_env()
    return RobinConfig.from_yaml(achar_config(caminho))


def _diga(texto: str = "", destino=None) -> None:
    """Imprime sem quebrar em consoles legados do Windows."""
    saida = destino or sys.stdout
    try:
        print(texto, file=saida)
    except UnicodeEncodeError:
        codificacao = getattr(saida, "encoding", None) or "ascii"
        print(texto.encode(codificacao, errors="replace").decode(codificacao), file=saida)


def _erro(mensagem: str) -> int:
    _diga(f"erro: {mensagem}", sys.stderr)
    return 1


def _linha(esquerda: str, direita: str = "", largura: int = 22) -> None:
    _diga(f"  {esquerda.ljust(largura)}{direita}")


# --------------------------------------------------------------------------
# key
# --------------------------------------------------------------------------

def _key_add(args) -> int:
    from .accounts import secrets as _secrets
    from .accounts import variaveis_conhecidas

    try:
        config = _carregar_config(args.config)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de YAML vira mensagem
        return _erro(t("msg.config_erro", erro=exc))

    valor = args.valor
    if valor == "-":
        # Colar a chave no comando deixa ela no histórico do shell. Ler da
        # entrada padrão permite `cat chave.txt | robinbandit key add ... -`.
        valor = sys.stdin.read().strip()
    if not valor:
        return _erro(t("msg.valor_vazio"))

    import os

    try:
        chaves = _secrets.guardar(
            args.variavel,
            valor,
            permitidos=variaveis_conhecidas(None, config),
            # Uma conta pode ter várias chaves, e o rotador alterna quando uma
            # bate a cota: acrescentar é o caso normal, substituir é a exceção.
            adicionar=not args.substituir,
            semente=os.environ.get(args.variavel, ""),
            rotulo=args.nome or "",
            paga=args.paga,
        )
    except ValueError as exc:
        return _erro(str(exc))

    _diga(t("msg.guardada", onde=_secrets.caminho_do_cofre()))
    _linha(args.variavel, t("msg.n_chaves", n=len(chaves)))
    _diga()
    _diga(t("msg.reinicie"))
    return 0


def _key_list(args) -> int:
    from .accounts import secrets as _secrets
    from .accounts import variaveis_conhecidas

    try:
        config = _carregar_config(args.config)
    except Exception as exc:  # noqa: BLE001
        return _erro(t("msg.config_erro", erro=exc))

    import os

    nomes = sorted(set(variaveis_conhecidas(None, config)))
    mostradas = 0
    _diga(t("msg.cofre", onde=_secrets.caminho_do_cofre()))
    _diga()
    for nome in nomes:
        situacao = _secrets.situacao(nome, os.environ.get(nome, ""))
        if not situacao["configurada"] and not args.todas:
            continue
        mostradas += 1
        if not situacao["configurada"]:
            _linha(nome, "—")
            continue
        # O valor nunca é impresso: só a dica que `secrets` já produz para o
        # painel, com os últimos caracteres.
        partes = []
        for k in situacao["chaves"]:
            marca = " (paga)" if k["paga"] else ""
            apelido = f"{k['nome']}: " if k["nome"] else ""
            partes.append(f"{apelido}{k['dica']}{marca}")
        _linha(nome, f"[{situacao['origem']}] " + ", ".join(partes))

    if not mostradas:
        _diga(t("msg.sem_chaves"))
        _diga()
        _diga(t("msg.exemplo_add"))
    elif not args.todas:
        _diga()
        _diga(t("msg.sem_chave_resto", n=len(nomes) - mostradas))
    return 0


def _key_rm(args) -> int:
    from .accounts import secrets as _secrets

    if args.indice is None:
        apagou = _secrets.remover(args.variavel)
        alvo = args.variavel
    else:
        apagou = _secrets.remover_chave(args.variavel, args.indice)
        alvo = f"{args.variavel}[{args.indice}]"

    if not apagou:
        return _erro(t("msg.nao_estava", alvo=alvo))
    _diga(t("msg.removida", alvo=alvo))
    _diga(t("msg.reinicie_curto"))
    return 0


# --------------------------------------------------------------------------
# providers
# --------------------------------------------------------------------------

def _providers(args) -> int:
    try:
        config = _carregar_config(args.config)
    except Exception as exc:  # noqa: BLE001
        return _erro(t("msg.config_erro", erro=exc))

    from .accounts import account_config

    catalogo = sorted((config.providers or {}).keys())
    ultimo = (config.last_resort or "").strip().lower()

    # Sem escolha gravada, a cadeia de partida é o `chain_order` MAIS o resto do
    # catálogo. Parece demais, e não é: estar na cadeia não é o mesmo que subir
    # — provedor sem chave não é montado de qualquer jeito. Partir só do
    # `chain_order` desligaria, na primeira edição, todo provedor que hoje entra
    # sem estar listado, e a pessoa só descobriria no próximo arranque.
    gravada = account_config.cadeia()
    if gravada:
        cadeia = gravada
    else:
        declarada = [c for c in (config.chain_order or []) if c != ultimo]
        cadeia = declarada + [c for c in catalogo if c not in declarada and c != ultimo]

    if args.acao in ("on", "off"):
        nome = args.provedor
        if not nome:
            return _erro(t("msg.falta_nome", acao=args.acao))
        if nome not in catalogo:
            return _erro(t("msg.nao_existe", nome=nome))

        if args.acao == "on":
            if nome in cadeia:
                _diga(t("msg.ja_dentro", nome=nome))
                return 0
            nova = cadeia + [nome]
        else:
            if nome not in cadeia:
                _diga(t("msg.ja_fora", nome=nome))
                return 0
            nova = [c for c in cadeia if c != nome]

        try:
            # A mesma função que o `PUT /config/cadeia` do painel chama.
            nova = account_config.definir_cadeia(nova, catalogo or None)
        except ValueError as exc:
            return _erro(str(exc))

        _diga(t("msg.cadeia_ok", onde=account_config.caminho_da_config()))
        _diga(f"  {' -> '.join(nova)}")
        _diga()
        _diga(t("msg.proximo_arranque"))
        return 0

    # sem ação: só mostra
    _diga(t("msg.na_cadeia", n=len(cadeia), t=len(catalogo)))
    _diga()
    for nome in cadeia:
        spec = (config.providers or {}).get(nome) or {}
        _linha(nome, f"tier {spec.get('tier', '—')}  {spec.get('cost_class', '')}")
    fora = [c for c in catalogo if c not in cadeia]
    if args.todos:
        if fora:
            _diga()
            _diga(t("msg.fora_titulo"))
            for nome in fora:
                spec = (config.providers or {}).get(nome) or {}
                _linha("  " + nome, str(spec.get("cost_class", "")))
    elif fora:
        _diga()
        _diga(t("msg.fora_resto", n=len(fora)))
    return 0


# --------------------------------------------------------------------------
# language
# --------------------------------------------------------------------------

def _language(args) -> int:
    from .ui import idioma as _idioma

    if not args.qual:
        _diga(t("msg.idioma_atual", qual=_idioma.escolhido()))
        _diga()
        _diga("  robinbandit language " + " | ".join(_idioma.IDIOMAS))
        return 0

    try:
        escolhido = _idioma.definir(args.qual)
    except ValueError:
        return _erro(t("msg.idioma_invalido", qual=args.qual,
                       opcoes=", ".join(_idioma.IDIOMAS)))

    # Já no idioma novo: confirmar a troca na língua antiga seria a última coisa
    # que a pessoa quer ler depois de pedir para trocar.
    _diga(t("msg.idioma_trocado", idioma=escolhido, qual=escolhido))
    _diga(t("msg.idioma_painel", idioma=escolhido))
    return 0


# --------------------------------------------------------------------------
# comandos que já existiam
# --------------------------------------------------------------------------

def _servir(args) -> None:
    from .bootstrap import servir

    servir(
        host=args.host,
        port=args.port,
        config=args.config,
        arquivo_env=args.env,
        banner=not args.no_banner,
        color=not args.no_color,
        navegador=not args.sem_navegador,
    )


def _estado(args) -> None:
    with open(args.dump, encoding="utf-8") as f:
        data = json.load(f)

    router = ProviderRouter()
    router.load(data)
    snap = router.snapshot()
    _write_banner(enabled=not args.no_banner, color=not args.no_color)
    if not snap:
        _diga(t("msg.dump_vazio"))
        return

    # Cooldown, status e cota não entram no dump (são voláteis do processo),
    # então só as colunas de aprendizado aparecem aqui.
    w = max(len(k) for k in snap)
    _diga(f"{'provider'.ljust(w)}  {'ok':>5} {'err':>5} {'lat_ms':>7} {'quality':>10} {'health':>8} {'q_samples':>9} {'h_samples':>9}")
    for key in sorted(snap, key=lambda k: snap[k]["quality_mean"] or 0.0, reverse=True):
        s = snap[key]
        lat = "-" if s["latency_ms"] is None else s["latency_ms"]
        q = "-" if s["quality_mean"] is None else f"{s['quality_mean']:.3f}"
        h = "-" if s["health_mean"] is None else f"{s['health_mean']:.3f}"
        _diga(f"{key.ljust(w)}  {s['ok']:>5} {s['err']:>5} {str(lat):>7} {q:>10} {h:>8} {s['quality_samples']:>9} {s['health_samples']:>9}")

    _diga()
    for key in sorted(data):
        for channel in ("health", "quality"):
            for c, ab in sorted((data[key].get(channel) or {}).items()):
                alpha, beta = float(ab[0]), float(ab[1])
                _diga(f"{key} {channel}/{c}: alpha={alpha:.2f} beta={beta:.2f} mean={alpha / (alpha + beta):.3f}")


# --------------------------------------------------------------------------
# montagem
# --------------------------------------------------------------------------

def _opcoes_de_banner(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-banner", action="store_true", help=t("cli.no_banner"))
    parser.add_argument("--no-color", action="store_true", help=t("cli.no_color"))


def _opcao_de_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help=t("cli.config"))


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robinbandit", description=t("cli.desc"))
    sub = parser.add_subparsers(dest="comando")

    # --- serve ---
    servidor = sub.add_parser("serve", help=t("cli.serve"))
    servidor.add_argument("--host", default="127.0.0.1", help=t("cli.host"))
    servidor.add_argument("--port", type=int, default=8000)
    _opcao_de_config(servidor)
    servidor.add_argument("--env", default=None, help=t("cli.env"))
    servidor.add_argument("--no-browser", dest="sem_navegador", action="store_true",
                          help=t("cli.no_browser"))
    _opcoes_de_banner(servidor)
    servidor.set_defaults(func=_servir)

    # --- key ---
    chave = sub.add_parser("key", help=t("cli.key"))
    acoes = chave.add_subparsers(dest="acao")

    add = acoes.add_parser("add", help=t("cli.key.add"))
    add.add_argument("variavel", metavar="VARIABLE", help=t("cli.key.var"))
    add.add_argument("valor", metavar="VALUE", help=t("cli.key.value"))
    add.add_argument("--label", dest="nome", default="", help=t("cli.key.label"))
    add.add_argument("--paid", dest="paga", action="store_true", help=t("cli.key.paid"))
    add.add_argument("--replace", dest="substituir", action="store_true",
                     help=t("cli.key.replace"))
    _opcao_de_config(add)
    add.set_defaults(func=_key_add)

    lista = acoes.add_parser("list", help=t("cli.key.list"))
    lista.add_argument("--all", dest="todas", action="store_true", help=t("cli.key.all"))
    _opcao_de_config(lista)
    lista.set_defaults(func=_key_list)

    rm = acoes.add_parser("rm", help=t("cli.key.rm"))
    rm.add_argument("variavel", metavar="VARIABLE")
    rm.add_argument("--index", dest="indice", type=int, default=None,
                    help=t("cli.key.index"))
    rm.set_defaults(func=_key_rm)

    # --- providers ---
    prov = sub.add_parser("providers", help=t("cli.providers"))
    prov.add_argument("acao", nargs="?", choices=("on", "off"), default=None,
                      metavar="[on|off]")
    prov.add_argument("provedor", nargs="?", default=None, metavar="PROVIDER")
    prov.add_argument("--all", dest="todos", action="store_true", help=t("cli.providers.all"))
    _opcao_de_config(prov)
    prov.set_defaults(func=_providers)

    # --- language ---
    lingua = sub.add_parser("language", help=t("cli.language"))
    lingua.add_argument("qual", nargs="?", default=None, metavar="[pt|en]",
                        help=t("cli.language.which"))
    lingua.set_defaults(func=_language)

    # --- state ---
    leitor = sub.add_parser("state", help=t("cli.state"))
    leitor.add_argument("dump", help=t("cli.state.dump"))
    _opcoes_de_banner(leitor)
    leitor.set_defaults(func=_estado)

    return parser


def main(argv: Optional[List[str]] = None) -> Any:
    parser = construir_parser()

    # `robinbandit dump.json` continua valendo: o visualizador existia antes dos
    # subcomandos e quebrá-lo não compra nada.
    bruto = list(sys.argv[1:] if argv is None else argv)
    if bruto and bruto[0] not in SUBCOMANDOS and not bruto[0].startswith("-"):
        bruto = ["state", *bruto]

    args = parser.parse_args(bruto)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    # `key` sem ação nenhuma: mostrar a ajuda do próprio subcomando ajuda mais
    # que um traceback ou um silêncio.
    if args.comando == "key" and not getattr(args, "acao", None):
        parser.parse_args(["key", "--help"])
        return 0

    saida = args.func(args)
    return saida if isinstance(saida, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
