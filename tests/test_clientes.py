"""Quem esta do outro lado, e ha quanto tempo falou.

A tela Conectar entregava a configuracao e parava ai: quem copiou nao
descobria se colou no lugar certo ate o agente dar erro. Os User-Agent aqui
foram capturados do que as ferramentas realmente enviam.
"""
import pytest

from robinbandit.api.clientes import Clientes, JANELA_ATIVA, detectar


def test_reconhece_o_claude_code_pelo_user_agent_real():
    """Capturado do claude 2.1.269 apontado para um servidor de teste."""
    ua = "claude-cli/2.1.269 (external, claude-vscode, agent-sdk/0.3.269)"
    assert detectar(ua) == "claude-code"


def test_reconhece_o_codex_apesar_do_underscore():
    """`codex_cli_rs` nao casa com `\bcodex\b`: `_` conta como caractere de
    palavra, entao a fronteira nunca aparece depois de `codex`."""
    assert detectar("codex_cli_rs/0.20.0") == "codex"


@pytest.mark.parametrize("ua,esperado", [
    ("Cline/3.2.0 vscode-extension", "cline"),
    ("opencode/0.4.1", "opencode"),
    ("curl/8.4.0", "curl"),
    ("OpenAI/Python 1.55.0", "openai-sdk"),
    ("python-httpx/0.27.0", "openai-sdk"),
])
def test_reconhece_as_outras_ferramentas(ua, esperado):
    assert detectar(ua) == esperado


def test_quem_nao_casa_vira_outro_em_vez_de_sumir():
    """Errar um padrao nao pode esconder o cliente: a tela mostra `outro` com o
    User-Agent cru do lado, e continua util."""
    assert detectar("AgenteCaseiro/1.0") == "outro"
    assert detectar("") == "outro"


def test_guarda_quantas_vezes_e_com_que_contextos():
    relogio = [1000.0]
    c = Clientes(agora=lambda: relogio[0])

    c.anotar("claude-cli/2.1", "codigo")
    c.anotar("claude-cli/2.1", "revisao")
    c.anotar("claude-cli/2.1", "codigo")  # repetido nao duplica o contexto

    visto = c.de("claude-code")
    assert visto["chamadas"] == 3
    assert visto["contextos"] == ["codigo", "revisao"]
    assert visto["ativo"] is True


def test_para_de_dizer_conectado_depois_da_janela():
    """A pergunta que a tela responde e 'esta conectado agora', nao 'ja
    conectou algum dia'."""
    relogio = [1000.0]
    c = Clientes(agora=lambda: relogio[0])
    c.anotar("curl/8.4.0", "teste")
    assert c.de("curl")["ativo"] is True

    relogio[0] += JANELA_ATIVA + 1
    assert c.de("curl")["ativo"] is False
    # continua listado: sumir esconderia que a ferramenta ja funcionou um dia
    assert c.de("curl")["chamadas"] == 1


def test_o_mais_recente_vem_primeiro():
    relogio = [1000.0]
    c = Clientes(agora=lambda: relogio[0])
    c.anotar("curl/8.4.0")
    relogio[0] += 60
    c.anotar("claude-cli/2.1")
    assert [i["id"] for i in c.status()] == ["claude-code", "curl"]


def test_a_chave_do_usuario_nunca_entra_no_registro():
    """O User-Agent e guardado; o header de autorizacao nem chega aqui."""
    c = Clientes()
    c.anotar("claude-cli/2.1 Bearer-nao-deveria-estar-aqui", "codigo")
    guardado = c.de("claude-code")["user_agent"]
    assert len(guardado) <= 120
