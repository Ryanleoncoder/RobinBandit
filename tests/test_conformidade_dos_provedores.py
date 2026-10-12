"""Todo provedor cumpre o mesmo contrato, para a troca de um por outro não
mudar o turno sem ninguém ver.

O contrato é o que a cadeia usa: `complete` assíncrono que recebe `messages`;
quem diz suportar ferramentas recebe `tools` pelo nome e devolve a escolha em
`last_tool_calls`. Um provedor que engolia `tools=` num `**kwargs` respondia
em texto e o turno inteiro mudava de caminho sem erro nenhum.
"""
import importlib
import inspect
import pkgutil

import pytest

import robinbandit.providers as pacote
from robinbandit.routing.chain import suporta_ferramentas


def _provedores():
    achados = []
    for modulo in pkgutil.iter_modules(pacote.__path__):
        mod = importlib.import_module(f"{pacote.__name__}.{modulo.name}")
        for nome, classe in inspect.getmembers(mod, inspect.isclass):
            if classe.__module__ == mod.__name__ and nome.endswith("Provider") and hasattr(classe, "complete"):
                achados.append(classe)
    return achados


PROVEDORES = _provedores()


def test_a_lista_acha_os_provedores():
    nomes = {c.__name__ for c in PROVEDORES}
    assert {"CodexProvider", "ClaudeCodeProvider", "OpenAICompatProvider", "ChatGPTProvider"} <= nomes


@pytest.mark.parametrize("classe", PROVEDORES, ids=lambda c: c.__name__)
def test_complete_e_assincrono_e_recebe_mensagens(classe):
    assert inspect.iscoroutinefunction(classe.complete)
    parametros = list(inspect.signature(classe.complete).parameters)
    assert parametros[:2] == ["self", "messages"]


@pytest.mark.parametrize("classe", PROVEDORES, ids=lambda c: c.__name__)
def test_quem_suporta_ferramentas_recebe_tools_pelo_nome(classe):
    if not suporta_ferramentas(classe):
        pytest.skip("sem ferramentas nativas")
    assert "tools" in inspect.signature(classe.complete).parameters


@pytest.mark.parametrize("classe", PROVEDORES, ids=lambda c: c.__name__)
def test_quem_suporta_ferramentas_devolve_a_escolha(classe):
    if not suporta_ferramentas(classe):
        pytest.skip("sem ferramentas nativas")
    # A escolha pode vir de uma classe mãe (o OpenRouter herda do compatível).
    fontes = "".join(inspect.getsource(c) for c in classe.__mro__ if c.__module__.startswith(pacote.__name__))
    assert hasattr(classe, "last_tool_calls") or "self.last_tool_calls" in fontes
