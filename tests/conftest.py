"""Os testes do RobinBandit nao leem — nem escrevem — nada da maquina.

Duas coisas moram em `~/.robinbandit/` e as duas envenenavam a suite:

`overrides_de_modelos()` le a configuracao, entao um modelo escolhido no painel
— ou gravado por outro teste — mudava o resultado aqui. Os testes passavam
sozinhos e falhavam na suite inteira, que e a pior forma de falhar.

E o cofre, que vence o ambiente por decisao de produto. Um teste que apaga
`CEREBRAS_API_KEY` do ambiente para provar que sem chave nao se monta provedor
so provava isso em maquina que nunca guardou essa chave: na de quem usa o
RobinBandit de verdade, a chave vinha do cofre e o teste falhava. Pior que
falhar: enquanto nao falhava, a suite estava lendo o segredo do dono da
maquina.
"""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def config_isolada(monkeypatch):
    from robinbandit import account_config

    casa = Path(tempfile.mkdtemp(prefix="robinbandit-testes-"))
    # `ROBINBANDIT_HOME` cobre ranking, historico, janelas e uso de uma vez.
    monkeypatch.setenv("ROBINBANDIT_HOME", str(casa))
    # O cofre e as contas tem variavel propria e precedencia sobre HOME: sem
    # apontar as duas, a do usuario continuaria valendo.
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(casa / "cofre.json"))
    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(casa / "contas.json"))
    for herdada in ("SENTURY_VAULT_PATH", "SENTURY_ACCOUNTS_PATH"):
        monkeypatch.delenv(herdada, raising=False)
    monkeypatch.setattr(account_config, "caminho_da_config", lambda: casa / "config.json")
    account_config._CACHE_MODELOS.update(mtime=None, valor={})
    yield
    account_config._CACHE_MODELOS.update(mtime=None, valor={})
