"""Como se sobe isto.

O pacote tinha router, painel e app FastAPI e nenhuma porta de entrada: quem
clonava precisava escrever o `uvicorn.run` a mao para ver a propria pagina.
"""
import os
import time
from pathlib import Path

import pytest

from robinbandit import RobinConfig
from robinbandit import bootstrap as mod

RAIZ = Path(__file__).resolve().parents[1]


def test_acha_a_config_subindo_a_partir_da_pasta_atual(monkeypatch, tmp_path):
    """Sem caminho fixo: cada instalacao tem a sua propria disposicao de pastas."""
    fundo = tmp_path / "a" / "b"
    fundo.mkdir(parents=True)
    (tmp_path / "robinbandit.yaml").write_text("version: 1\n", encoding="utf-8")
    monkeypatch.chdir(fundo)

    assert mod.achar_config() == tmp_path / "robinbandit.yaml"


def test_config_explicita_ganha_do_que_foi_descoberto(monkeypatch, tmp_path):
    escolhida = tmp_path / "outra.yaml"
    escolhida.write_text("version: 1\n", encoding="utf-8")
    (tmp_path / "robinbandit.yaml").write_text("version: 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert mod.achar_config(str(escolhida)) == escolhida


def test_config_inexistente_falha_alto(tmp_path):
    with pytest.raises(FileNotFoundError):
        mod.achar_config(str(tmp_path / "nao-existe.yaml"))


def test_sem_arquivo_nenhum_cai_no_catalogo_de_fabrica(monkeypatch, tmp_path):
    """`pip install robinbandit && robinbandit serve` tem que subir.

    O catalogo mora dentro do pacote justamente para isto. Provedor sem chave
    no ambiente nao e montado, entao o padrao e o que a maquina tem.
    """
    from robinbandit.config import caminho_do_catalogo

    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ROBINBANDIT_CONFIG", raising=False)
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    monkeypatch.chdir(vazia)

    assert mod.achar_config() == caminho_do_catalogo()


def test_nenhum_nome_de_agente_na_descoberta():
    """A busca usa nomes do proprio RobinBandit. `config/sentury.yaml` aqui
    dentro seria um agente especifico embutido na ferramenta universal."""
    assert all("sentury" not in nome for nome in mod.NOMES)


def test_partida_diz_quem_ficou_de_fora_e_por_que():
    """Provedor sem chave nao e montado — em silencio, o que e certo em runtime
    e pessimo na primeira vez que alguem sobe isto."""
    config = RobinConfig.from_yaml(RAIZ / "config" / "sentury.yaml")
    linhas = mod.resumo_da_partida(config, [], "127.0.0.1", 8000, Path("x.yaml"))
    texto = chr(10).join(linhas)

    assert "sem chave" in texto
    assert "groq" in texto
    assert "/painel" in texto


def test_catalogo_de_fabrica_nao_tem_nome_de_agente():
    """O catalogo e do RobinBandit. Ele nasceu dentro de `config/sentury.yaml`,
    e enquanto estava la nenhum outro agente tinha catalogo nenhum."""
    from robinbandit.config import caminho_do_catalogo

    texto = caminho_do_catalogo().read_text(encoding="utf-8")
    assert "sentury" not in texto.lower()


def test_sentury_herda_o_catalogo_em_vez_de_copia_lo():
    """O YAML do agente e o que MUDA. Como copia de 700 linhas, ele envelhecia
    em ritmo proprio."""
    from robinbandit.config import caminho_do_catalogo

    overlay = RAIZ / "config" / "sentury.yaml"
    assert len(overlay.read_text(encoding="utf-8").splitlines()) < 40

    fabrica = RobinConfig.from_yaml(caminho_do_catalogo())
    sentury = RobinConfig.from_yaml(overlay)
    assert set(sentury.providers) == set(fabrica.providers)
    assert sentury.agent_mode == "sentury" and fabrica.agent_mode == "universal"


def test_heranca_circular_falha_alto(tmp_path):
    arquivo = tmp_path / "loop.yaml"
    arquivo.write_text("herda: loop.yaml" + chr(10) + "version: 1" + chr(10), encoding="utf-8")
    with pytest.raises(ValueError, match="proprio arquivo"):
        RobinConfig.from_yaml(arquivo)


def test_logos_vao_dentro_do_pacote():
    """Estavam em `assets/` na raiz: quem clonava via as imagens e quem
    instalava pelo pip abria o painel com tudo quebrado."""
    from robinbandit.server import pasta_das_logos

    pasta = pasta_das_logos()
    assert pasta.is_dir()
    assert (pasta / "groq.svg").is_file()
    assert "robinbandit" in str(pasta.parent.name) or pasta.parent.parent.name == "robinbandit"


def test_a_pagina_do_painel_vai_dentro_do_pacote():
    """Mesma historia das logos, um andar ao lado: o CSS e o JS sairam de dentro
    de uma string em `painel.py` e viraram arquivos. Se escaparem do
    `package-data`, `pip install` entrega painel sem estilo — e isto aqui nao
    pega, porque a suite le o codigo-fonte. Quem pega e o job `pacote` do CI;
    este teste garante so que o layout esperado existe."""
    from robinbandit.painel import pasta_do_painel

    pasta = pasta_do_painel()
    assert pasta.is_dir()
    for nome in ("pagina.html", "estilo.css", "painel.js"):
        assert (pasta / nome).is_file(), f"{nome} sumiu de assets/painel/"
    assert pasta.parent.parent.name == "robinbandit"


def test_arquivo_de_contas_nao_nasce_com_nome_de_outro_agente(monkeypatch, tmp_path):
    """Nascia em `./.sentury/contas.json`: qualquer agente que usasse o
    RobinBandit ganhava uma pasta com o nome de outro, e mudar de terminal
    mudava a configuracao lida."""
    from robinbandit import account_config

    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path / "casa"))
    for nome in ("ROBINBANDIT_ACCOUNTS_PATH", "SENTURY_ACCOUNTS_PATH"):
        monkeypatch.delenv(nome, raising=False)
    vazia = tmp_path / "outro-agente"
    vazia.mkdir()
    monkeypatch.chdir(vazia)

    caminho = account_config._padrao()
    assert caminho == tmp_path / "casa" / "contas.json"
    assert ".sentury" not in str(caminho)


def test_contas_ja_existentes_sao_migradas_sem_perder_nada(monkeypatch, tmp_path):
    """Padronizar o caminho por baixo de quem ja configurou apagaria a
    configuracao da tela sem apagar arquivo nenhum. Entao: copia uma vez para a
    casa nova e segue de la — e o original fica onde esta."""
    from robinbandit import account_config

    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path / "casa"))
    for nome in ("ROBINBANDIT_ACCOUNTS_PATH", "SENTURY_ACCOUNTS_PATH"):
        monkeypatch.delenv(nome, raising=False)
    antigo = tmp_path / "projeto" / ".sentury"
    antigo.mkdir(parents=True)
    conteudo = '{"contas": [], "tiers": {"ultra": "x"}}'
    (antigo / "contas.json").write_text(conteudo, encoding="utf-8")
    monkeypatch.chdir(tmp_path / "projeto")

    usado = account_config._padrao()
    assert usado == tmp_path / "casa" / "contas.json"
    assert usado.read_text(encoding="utf-8") == conteudo
    # Nada e apagado: o arquivo de origem continua la.
    assert (antigo / "contas.json").is_file()


def test_cofre_nunca_nasce_dentro_de_um_projeto(monkeypatch, tmp_path):
    """Nascia em `./.sentury/cofre.json`. Um arquivo de segredos dentro de um
    repositorio espera por um `git add .` distraido, e trocar de terminal abria
    outro cofre."""
    from robinbandit import secrets

    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path / "casa"))
    for nome in ("ROBINBANDIT_VAULT_PATH", "SENTURY_VAULT_PATH"):
        monkeypatch.delenv(nome, raising=False)
    projeto = tmp_path / "projeto" / ".sentury"
    projeto.mkdir(parents=True)
    (projeto / "cofre.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "projeto")

    assert secrets._padrao() == tmp_path / "casa" / "cofre.json"


def test_ultimo_recurso_fica_por_ultimo():
    """Quem foi configurado e ficou fora da `chain_order` entra depois, em vez
    de sumir sem aviso — mas nunca depois do ultimo recurso."""
    config = RobinConfig.from_yaml(RAIZ / "config" / "sentury.yaml")
    montados = {"fallback": "F", "groq": "G", "gemini": "E", "sem_ordem": "S"}

    assert mod.ordenar(config, montados) == ["G", "E", "S", "F"]


def test_montar_devolve_um_app_que_serve_o_painel():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = RobinConfig.from_yaml(RAIZ / "config" / "sentury.yaml")
    app, provedores, gateway = mod.montar(config)

    assert provedores, "nenhum provedor montado a partir do YAML"
    cliente = TestClient(app)
    assert cliente.get("/painel").status_code == 200
    assert cliente.get("/painel/dados").status_code == 200


def test_dump_sem_subcomando_continua_valendo(monkeypatch, tmp_path, capsys):
    """`robinbandit dump.json` existia antes dos subcomandos."""
    import sys

    from robinbandit import __main__ as cli

    dump = tmp_path / "state.json"
    dump.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["robinbandit", str(dump), "--no-banner"])
    cli.main()

    assert capsys.readouterr().out == "dump sem provedores\n"


def test_env_do_projeto_e_lido_sozinho(monkeypatch, tmp_path):
    """Sozinho o RobinBandit nao tem host para carregar as chaves por ele.
    Sem isto, `serve` sobe so com quem nao pede chave e ninguem entende por que
    a lista ficou curta."""
    monkeypatch.delenv("CHAVE_DE_TESTE_RB", raising=False)
    projeto = tmp_path / "projeto"
    (projeto / "fundo").mkdir(parents=True)
    (projeto / ".env").write_text(
        'CHAVE_DE_TESTE_RB="valor-do-arquivo"' + chr(10), encoding="utf-8"
    )

    achado = mod.carregar_env(projeto / "fundo")

    assert achado == projeto / ".env"
    assert os.environ["CHAVE_DE_TESTE_RB"] == "valor-do-arquivo"


def test_quem_exportou_na_mao_ganha_do_arquivo(monkeypatch, tmp_path):
    """Exportar a variavel e dizer alguma coisa; o arquivo nao passa por cima."""
    monkeypatch.setenv("CHAVE_DE_TESTE_RB", "valor-exportado")
    (tmp_path / ".env").write_text("CHAVE_DE_TESTE_RB=do-arquivo" + chr(10), encoding="utf-8")

    mod.carregar_env(tmp_path)

    assert os.environ["CHAVE_DE_TESTE_RB"] == "valor-exportado"


def test_ler_env_nunca_escreve_nele(tmp_path):
    """Leitura e permitida; escrever no `.env` de alguem, nunca."""
    alvo = tmp_path / ".env"
    conteudo = "A=1" + chr(10) + "# comentario" + chr(10)
    alvo.write_text(conteudo, encoding="utf-8")
    antes = alvo.stat().st_mtime_ns

    mod.carregar_env(tmp_path)

    assert alvo.read_text(encoding="utf-8") == conteudo
    assert alvo.stat().st_mtime_ns == antes


def test_o_painel_abre_no_endereco_certo():
    """`0.0.0.0` e instrucao de escuta, nao destino: o Windows recusa conexao
    para ele. Quem expoe na rede ainda abre o painel na propria maquina."""
    assert mod.endereco_do_painel("127.0.0.1", 8000) == "http://127.0.0.1:8000/painel"
    assert mod.endereco_do_painel("0.0.0.0", 8771) == "http://127.0.0.1:8771/painel"
    assert mod.endereco_do_painel("192.168.0.10", 80) == "http://192.168.0.10:80/painel"


def test_navegador_so_abre_depois_que_a_porta_responde(monkeypatch):
    """Abrir antes do uvicorn atender daria 'nao foi possivel conectar' na cara
    de quem acabou de rodar o comando."""
    import socket
    import threading

    abertos = []
    monkeypatch.setattr("webbrowser.open", lambda url: abertos.append(url))

    ouvinte = socket.socket()
    ouvinte.bind(("127.0.0.1", 0))
    porta = ouvinte.getsockname()[1]
    # Ainda nao aceitou ninguem: o navegador nao pode ter sido chamado.
    mod.abrir_quando_subir("127.0.0.1", porta, espera=5.0)
    assert abertos == []

    ouvinte.listen(1)
    pronto = threading.Event()

    def esperar():
        for _ in range(100):
            if abertos:
                pronto.set()
                return
            time.sleep(0.05)

    t = threading.Thread(target=esperar)
    t.start()
    t.join(timeout=6)
    ouvinte.close()

    assert abertos == [f"http://127.0.0.1:{porta}/painel"]


def test_navegador_quebrado_nao_derruba_o_servidor(monkeypatch):
    """Sem navegador — container, ssh, CI — o endereco ja foi impresso; quebrar
    a subida do servidor por causa disso seria trocar o problema de lugar."""
    import socket

    def explodir(url):
        raise RuntimeError("sem navegador aqui")

    monkeypatch.setattr("webbrowser.open", explodir)

    ouvinte = socket.socket()
    ouvinte.bind(("127.0.0.1", 0))
    ouvinte.listen(1)
    porta = ouvinte.getsockname()[1]

    mod.abrir_quando_subir("127.0.0.1", porta, espera=5.0)
    time.sleep(1.0)  # a thread ja tentou e engoliu o erro
    ouvinte.close()


def test_sem_tela_o_painel_nao_tenta_abrir(monkeypatch):
    """Numa VPS o `serve` deve subir e ficar quieto. Exigir que a pessoa lembre
    de `--no-browser` e passar para ela um trabalho que a maquina sabe fazer."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("ROBINBANDIT_SEM_NAVEGADOR", raising=False)

    assert mod.tem_tela() is False


def test_com_sessao_grafica_abre(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("ROBINBANDIT_SEM_NAVEGADOR", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")

    assert mod.tem_tela() is True


def test_windows_e_mac_tem_tela_por_definicao(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("ROBINBANDIT_SEM_NAVEGADOR", raising=False)
    for plataforma in ("win32", "darwin"):
        monkeypatch.setattr("sys.platform", plataforma)
        assert mod.tem_tela() is True, plataforma


def test_ci_nunca_abre_navegador(monkeypatch):
    """Abre para ninguem e ainda deixa o processo pendurado."""
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("CI", "true")
    assert mod.tem_tela() is False


def test_desligar_um_provedor_tira_ele_da_cadeia_de_verdade(monkeypatch, tmp_path):
    """O painel gravava a escolha, respondia "vale no proximo arranque", e o
    provedor subia do mesmo jeito: `ordenar()` so lia o `chain_order` do YAML e
    ainda punha de volta quem nao estivesse listado."""
    from robinbandit import account_config

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "contas.json"))
    config = RobinConfig.from_yaml(RAIZ / "config" / "sentury.yaml")
    montados = {"groq": object(), "gemini": object(), "claude_code": object()}

    account_config.definir_cadeia(["groq", "gemini"], list(config.providers))
    saida = mod.ordenar(config, montados)

    assert montados["claude_code"] not in saida, "desligado pelo painel, montado assim mesmo"
    assert saida == [montados["groq"], montados["gemini"]]


def test_sem_escolha_gravada_quem_tem_chave_entra_mesmo_fora_da_lista(monkeypatch, tmp_path):
    """Esquecer um nome no `chain_order` nao pode desligar uma chave que a
    pessoa cadastrou. A lista do YAML diz ORDEM; participacao so quando alguem
    escolhe explicitamente."""
    from robinbandit import account_config

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "vazio.json"))
    assert account_config.cadeia() == []

    config = RobinConfig.from_yaml(RAIZ / "config" / "sentury.yaml")
    fora_da_lista = object()
    montados = {"groq": object(), "llm7": fora_da_lista}

    saida = mod.ordenar(config, montados)

    assert fora_da_lista in saida, "provedor configurado sumiu por nao estar no chain_order"


def test_o_ultimo_recurso_nao_e_desligavel(monkeypatch, tmp_path):
    """Ele existe para o caso de todo o resto falhar: ficar sem ele e ficar sem
    resposta nenhuma."""
    from robinbandit import account_config

    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "contas.json"))
    config = RobinConfig.from_yaml(RAIZ / "config" / "sentury.yaml")
    ultimo = object()
    montados = {"groq": object(), config.last_resort: ultimo}

    account_config.definir_cadeia(["groq"], list(config.providers))
    saida = mod.ordenar(config, montados)

    assert saida[-1] is ultimo
