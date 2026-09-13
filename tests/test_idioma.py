"""Em que lingua o RobinBandit responde.

A suite fixa `pt` no conftest para ser determinista — sem isso ela passava aqui
e quebrava no Linux do CI, onde nao ha locale portugues e as mensagens saiam em
ingles. Este arquivo e o contrapeso: e o unico que troca de idioma de proposito,
para o ingles nao ficar sem nenhuma cobertura.
"""
import pytest

from robinbandit import idioma


def test_mesma_chave_responde_nas_duas_linguas():
    assert idioma.t("cli.serve", "pt") == "sobe o endpoint e o painel"
    assert idioma.t("cli.serve", "en") == "bring up the endpoint and the panel"


def test_chave_que_nao_existe_volta_como_ela_mesma():
    """Traducao faltando e defeito de acabamento, nao motivo para derrubar um
    comando no meio."""
    assert idioma.t("isto.nao.existe") == "isto.nao.existe"


def test_campos_entram_no_texto_das_duas():
    assert "/tmp/x" in idioma.t("msg.guardada", "pt", onde="/tmp/x")
    assert "/tmp/x" in idioma.t("msg.guardada", "en", onde="/tmp/x")


def test_campo_faltando_nao_estoura():
    """Melhor a frase com `{onde}` cru do que um KeyError subindo de dentro de
    uma mensagem de erro."""
    assert idioma.t("msg.guardada", "pt")


def test_toda_chave_tem_as_duas_linguas():
    faltando = [
        chave for chave, valores in idioma.TEXTOS.items()
        if not valores.get("pt") or not valores.get("en")
    ]
    assert not faltando, f"sem par pt/en: {faltando}"


def test_todo_texto_com_campo_usa_o_mesmo_nome_nas_duas():
    """`{n}` em portugues e `{count}` em ingles faria a versao inglesa sair com
    o marcador cru na tela."""
    import re

    divergentes = []
    for chave, valores in idioma.TEXTOS.items():
        campos = {lang: set(re.findall(r"\{(\w+)\}", texto))
                  for lang, texto in valores.items()}
        if len(set(map(frozenset, campos.values()))) > 1:
            divergentes.append((chave, campos))
    assert not divergentes, f"campos diferentes entre linguas: {divergentes}"


@pytest.mark.parametrize("escolhido", ["pt", "en"])
def test_a_escolha_grava_e_volta(escolhido, monkeypatch):
    """O `idioma` ja sumiu uma vez na leitura: `account_config.carregar()` tem
    lista branca, e o que nao esta nela e descartado sem aviso."""
    monkeypatch.delenv("ROBINBANDIT_IDIOMA", raising=False)

    assert idioma.definir(escolhido) == escolhido
    assert idioma.escolhido() == escolhido


def test_idioma_invalido_e_recusado():
    with pytest.raises(ValueError):
        idioma.definir("klingon")


def test_a_variavel_de_ambiente_ganha_do_sistema(monkeypatch):
    monkeypatch.setenv("ROBINBANDIT_IDIOMA", "en")
    assert idioma.escolhido() == "en"
