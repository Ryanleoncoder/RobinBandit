"""Idioma usado nas respostas da CLI e do painel."""
from __future__ import annotations

import locale
import os
from typing import Dict, Optional

IDIOMAS = ("pt", "en")
PADRAO = "en"

# Traduções pequenas ficam em dicionário para evitar etapa de compilação.
TEXTOS: Dict[str, Dict[str, str]] = {
    # --- linha de comando: ajuda ---
    "cli.desc": {
        "pt": "Roteador adaptativo de provedores de LLM.",
        "en": "Adaptive LLM provider router.",
    },
    "cli.serve": {
        "pt": "sobe o endpoint e o painel",
        "en": "bring up the endpoint and the panel",
    },
    "cli.host": {
        "pt": "padrão 127.0.0.1; use 0.0.0.0 para expor na rede",
        "en": "defaults to 127.0.0.1; use 0.0.0.0 to expose on the network",
    },
    "cli.config": {
        "pt": "YAML a usar; sem isto, procura a partir da pasta atual",
        "en": "YAML to use; without it, searches upward from the current folder",
    },
    "cli.env": {
        "pt": ".env com as chaves; sem isto, procura a partir da pasta atual",
        "en": ".env with the keys; without it, searches upward from the current folder",
    },
    "cli.no_browser": {
        "pt": "não abre o painel no navegador (para servidor, container ou ssh)",
        "en": "do not open the panel in a browser (for servers, containers or ssh)",
    },
    "cli.no_banner": {
        "pt": "não mostra a logo no terminal",
        "en": "do not print the logo",
    },
    "cli.no_color": {
        "pt": "mostra a logo sem cores ANSI",
        "en": "print the logo without ANSI colors",
    },
    "cli.key": {
        "pt": "as chaves de API, no cofre desta máquina",
        "en": "API keys, in this machine's vault",
    },
    "cli.key.add": {
        "pt": "grava uma chave no cofre",
        "en": "store a key in the vault",
    },
    "cli.key.var": {
        "pt": "nome da variável, ex.: GROQ_API_KEY",
        "en": "variable name, e.g. GROQ_API_KEY",
    },
    "cli.key.value": {
        "pt": "o valor da chave; use - para ler da entrada padrão",
        "en": "the key value; use - to read from standard input",
    },
    "cli.key.label": {
        "pt": "apelido desta chave, ex.: 'conta pessoal'",
        "en": "a label for this key, e.g. 'personal account'",
    },
    "cli.key.paid": {
        "pt": "marca como crédito pago",
        "en": "mark as paid credit",
    },
    "cli.key.replace": {
        "pt": "troca as chaves existentes em vez de acrescentar",
        "en": "replace the existing keys instead of adding",
    },
    "cli.key.list": {
        "pt": "o que está configurado (nunca mostra o valor)",
        "en": "what is configured (never shows the value)",
    },
    "cli.key.all": {
        "pt": "inclui as variáveis sem chave",
        "en": "include variables with no key",
    },
    "cli.key.rm": {
        "pt": "remove uma chave do cofre",
        "en": "remove a key from the vault",
    },
    "cli.key.index": {
        "pt": "remove só a chave nesta posição; sem isto, remove a variável inteira",
        "en": "remove only the key at this position; without it, removes the whole variable",
    },
    "cli.providers": {
        "pt": "quem está na cadeia",
        "en": "who is in the chain",
    },
    "cli.providers.all": {
        "pt": "mostra também quem está fora",
        "en": "also show who is out",
    },
    "cli.state": {
        "pt": "mostra o que o router aprendeu, a partir de um dump",
        "en": "show what the router learned, from a dump",
    },
    "cli.state.dump": {
        "pt": "arquivo JSON no formato de ProviderRouter.dump()",
        "en": "JSON file in ProviderRouter.dump() format",
    },
    "cli.language": {
        "pt": "em que língua o RobinBandit responde",
        "en": "which language RobinBandit answers in",
    },
    "cli.language.which": {
        "pt": "pt ou en; sem isto, mostra o atual",
        "en": "pt or en; without it, shows the current one",
    },

    # --- linha de comando: mensagens ---
    "msg.config_erro": {
        "pt": "não consegui ler a configuração: {erro}",
        "en": "could not read the configuration: {erro}",
    },
    "msg.valor_vazio": {"pt": "valor vazio", "en": "empty value"},
    "msg.guardada": {"pt": "guardada em {onde}", "en": "stored in {onde}"},
    "msg.n_chaves": {
        "pt": "{n} chave(s) nesta variável",
        "en": "{n} key(s) in this variable",
    },
    "msg.reinicie": {
        "pt": "O servidor lê o cofre ao subir: reinicie o `serve` para valer.",
        "en": "The server reads the vault at startup: restart `serve` to apply.",
    },
    "msg.cofre": {"pt": "cofre: {onde}", "en": "vault: {onde}"},
    "msg.sem_chaves": {
        "pt": "  nenhuma chave configurada.",
        "en": "  no keys configured.",
    },
    "msg.exemplo_add": {
        "pt": "  robinbandit key add GROQ_API_KEY <valor>",
        "en": "  robinbandit key add GROQ_API_KEY <value>",
    },
    "msg.sem_chave_resto": {
        "pt": "  ({n} variáveis sem chave; use --all para ver)",
        "en": "  ({n} variables with no key; use --all to see them)",
    },
    "msg.nao_estava": {
        "pt": "{alvo} não estava no cofre",
        "en": "{alvo} was not in the vault",
    },
    "msg.removida": {"pt": "removida: {alvo}", "en": "removed: {alvo}"},
    "msg.reinicie_curto": {
        "pt": "Reinicie o `serve` para valer.",
        "en": "Restart `serve` to apply.",
    },
    "msg.na_cadeia": {
        "pt": "{n} na cadeia, {t} no catálogo",
        "en": "{n} in the chain, {t} in the catalog",
    },
    "msg.fora_resto": {
        "pt": "  ({n} fora da cadeia; use --all para ver)",
        "en": "  ({n} out of the chain; use --all to see them)",
    },
    "msg.fora_titulo": {"pt": "  fora da cadeia:", "en": "  out of the chain:"},
    "msg.falta_nome": {
        "pt": "falta o nome do provedor: robinbandit providers {acao} groq",
        "en": "missing the provider name: robinbandit providers {acao} groq",
    },
    "msg.nao_existe": {
        "pt": "'{nome}' não existe no catálogo",
        "en": "'{nome}' is not in the catalog",
    },
    "msg.ja_dentro": {
        "pt": "{nome} já estava na cadeia",
        "en": "{nome} was already in the chain",
    },
    "msg.ja_fora": {
        "pt": "{nome} já estava fora da cadeia",
        "en": "{nome} was already out of the chain",
    },
    "msg.cadeia_ok": {
        "pt": "cadeia atualizada em {onde}",
        "en": "chain updated in {onde}",
    },
    "msg.proximo_arranque": {
        "pt": "Vale para os provedores montados no próximo arranque.",
        "en": "Applies to the providers built on the next start.",
    },
    "msg.dump_vazio": {"pt": "dump sem provedores", "en": "dump has no providers"},
    "msg.idioma_atual": {
        "pt": "idioma: {qual}",
        "en": "language: {qual}",
    },
    "msg.idioma_trocado": {
        "pt": "idioma alterado para {qual}.",
        "en": "language changed to {qual}.",
    },
    "msg.idioma_invalido": {
        "pt": "idioma '{qual}' não existe. Use: {opcoes}",
        "en": "language '{qual}' does not exist. Use: {opcoes}",
    },
    "msg.idioma_painel": {
        "pt": "O painel também passa a abrir neste idioma.",
        "en": "The panel will open in this language too.",
    },
}


def _do_sistema() -> str:
    """Idioma da máquina quando ninguém escolheu."""
    for variavel in ("ROBINBANDIT_IDIOMA", "LANGUAGE", "LC_ALL", "LANG"):
        valor = os.environ.get(variavel, "")
        if valor[:2].lower() in IDIOMAS:
            return valor[:2].lower()
    try:
        # getdefaultlocale está a caminho da remoção desde o 3.11.
        atual = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        atual = ""
    if atual[:2].lower() in IDIOMAS:
        return atual[:2].lower()
    if "portug" in atual.lower() or atual.lower().startswith("pt"):
        return "pt"
    return PADRAO


def _do_yaml() -> str:
    """`idioma:` declarado na configuração, se houver YAML legível."""
    try:
        from ..bootstrap import achar_config
        from ..config import RobinConfig

        valor = str(RobinConfig.from_yaml(achar_config()).idioma or "").strip().lower()
        return valor if valor in IDIOMAS else ""
    except Exception:  # noqa: BLE001 - sem YAML, sem PyYAML, ou arquivo inválido
        return ""


def escolhido() -> str:
    """Idioma efetivo: preferência gravada, YAML, sistema."""
    try:
        from ..accounts import account_config

        gravado = str(account_config.carregar().get("idioma") or "").strip().lower()
        if gravado in IDIOMAS:
            return gravado
    except Exception:  # noqa: BLE001 - sem configuração ainda, ou ilegível
        pass

    declarado = _do_yaml()
    if declarado:
        return declarado

    return _do_sistema()


def definir(qual: str) -> str:
    """Grava a escolha, no mesmo arquivo que guarda o resto da configuração."""
    valor = str(qual or "").strip().lower()
    if valor not in IDIOMAS:
        raise ValueError(f"idioma '{qual}' não existe. Use: {', '.join(IDIOMAS)}")

    from ..accounts import account_config

    dados = account_config.carregar()
    dados["idioma"] = valor
    account_config._gravar(dados)
    return valor


def t(chave: str, idioma: Optional[str] = None, **campos) -> str:
    """Texto traduzido; chave desconhecida volta como ela mesma."""
    entrada = TEXTOS.get(chave)
    if not entrada:
        return chave
    texto = entrada.get(idioma or escolhido()) or entrada.get(PADRAO) or chave
    if campos:
        try:
            return texto.format(**campos)
        except (KeyError, IndexError):
            return texto
    return texto


__all__ = ["IDIOMAS", "PADRAO", "TEXTOS", "definir", "escolhido", "t"]
