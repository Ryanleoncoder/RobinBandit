"""A linha de comando, que e a interface de quem nao tem navegador.

Ate existir, cadastrar uma chave so era possivel pelo painel: configurar uma
maquina remota exigia tunelar a porta por ssh para colar uma API key. Cada
comando aqui chama a mesma funcao que a rota do painel chama.
"""
import json

import pytest

from robinbandit import cli


@pytest.fixture
def isolado(tmp_path, monkeypatch):
    """Cofre e config proprios: nenhum teste escreve no ~/.robinbandit de quem
    estiver rodando a suite."""
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "cofre.json"))
    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "contas.json"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_key_add_grava_e_list_nunca_mostra_o_valor(isolado, capsys):
    assert cli.main(["key", "add", "GROQ_API_KEY", "gsk_supersecreto_123456"]) == 0
    capsys.readouterr()

    assert cli.main(["key", "list"]) == 0
    saida = capsys.readouterr().out

    assert "GROQ_API_KEY" in saida
    # A chave inteira nao pode aparecer em lugar nenhum; so a dica do fim.
    assert "gsk_supersecreto_123456" not in saida
    assert "3456" in saida


def test_key_add_recusa_variavel_fora_do_catalogo(isolado, capsys):
    """Lista branca: sem ela, um comando gravaria qualquer configuracao no
    cofre, e o painel passaria a mostrar coisa que nenhum provedor le."""
    assert cli.main(["key", "add", "VARIAVEL_QUE_NAO_EXISTE", "x"]) == 1
    assert "não pertence" in capsys.readouterr().err


def test_key_add_acrescenta_em_vez_de_substituir(isolado, capsys):
    """Uma conta pode ter varias chaves, e o rotador alterna quando uma bate a
    cota: substituir por padrao apagaria as outras em silencio."""
    cli.main(["key", "add", "GROQ_API_KEY", "primeira_chave_aaa"])
    cli.main(["key", "add", "GROQ_API_KEY", "segunda_chave_bbb"])
    capsys.readouterr()

    from robinbandit import secrets

    assert len(secrets.listar("GROQ_API_KEY")) == 2


def test_replace_e_explicito(isolado, capsys):
    cli.main(["key", "add", "GROQ_API_KEY", "primeira_chave_aaa"])
    cli.main(["key", "add", "GROQ_API_KEY", "unica_chave_ccc", "--replace"])
    capsys.readouterr()

    from robinbandit import secrets

    assert len(secrets.listar("GROQ_API_KEY")) == 1


def test_key_rm_devolve_erro_quando_nao_existe(isolado, capsys):
    assert cli.main(["key", "rm", "GROQ_API_KEY"]) == 1
    assert "não estava no cofre" in capsys.readouterr().err


def test_providers_lista_a_cadeia(isolado, capsys):
    assert cli.main(["providers"]) == 0
    saida = capsys.readouterr().out
    assert "na cadeia" in saida
    assert "groq" in saida


def test_providers_desligar_e_ligar(isolado, capsys):
    assert cli.main(["providers", "off", "groq"]) == 0
    capsys.readouterr()

    from robinbandit import account_config

    assert "groq" not in account_config.cadeia()

    assert cli.main(["providers", "on", "groq"]) == 0
    capsys.readouterr()
    assert "groq" in account_config.cadeia()


def test_provider_inexistente_e_recusado(isolado, capsys):
    assert cli.main(["providers", "on", "batata"]) == 1
    assert "não existe no catálogo" in capsys.readouterr().err


def test_on_sem_nome_explica_em_vez_de_estourar(isolado, capsys):
    assert cli.main(["providers", "on"]) == 1
    assert "falta o nome" in capsys.readouterr().err


def test_dump_solto_ainda_vale_como_antes(isolado, capsys):
    """`robinbandit dump.json` existia antes dos subcomandos; quebrar isso nao
    compra nada. O subcomando virou `state`, e o atalho continua."""
    alvo = isolado / "estado.json"
    alvo.write_text(json.dumps({"groq": {"ok": 3, "err": 0, "latency_ms": 100.0,
                                         "health": {"x": [4.0, 1.0]}, "quality": {}}}),
                    encoding="utf-8")
    assert cli.main([str(alvo), "--no-banner"]) == 0
    assert "groq" in capsys.readouterr().out


def test_saida_sobrevive_a_console_sem_unicode(monkeypatch, capsys):
    """O console legado do Windows e cp1252: um caractere fora da tabela
    derrubava o comando depois de o trabalho ja ter sido feito."""
    class ConsoleAntigo:
        encoding = "cp1252"

        def write(self, texto):
            texto.encode("cp1252")  # estoura no que nao couber
            return len(texto)

        def flush(self):
            pass

    cli._diga("seta \u2192 e acento ç", ConsoleAntigo())  # nao pode levantar
