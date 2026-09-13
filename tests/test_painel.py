"""Painel e ferramentas de CLI.

O painel nao calcula nada: tudo que ele mostra vem do router. Um painel que
faz sua propria conta mostra uma coisa enquanto o roteador decide por outra.
"""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from robinbandit import cli_tools  # noqa: E402
from robinbandit.router import ProviderRouter  # noqa: E402
from robinbandit.server import create_app  # noqa: E402


class _Fake:
    def __init__(self, nome):
        self.name = nome

    async def complete(self, messages, temperature=0.2):
        return "ok"


def _cliente():
    router = ProviderRouter(
        {"groq": {"tier": 1, "quality": 0.8}, "gemini": {"tier": 1, "quality": 0.7}},
        seed=3,
    )
    for _ in range(5):
        router.record_success("groq", 300.0, context="painel")
        router.record_success("gemini", 200.0, context="painel")
    router.record_failure("gemini", "quota", context="painel")
    # Com o config real o painel enxerga o catalogo inteiro — e o catalogo e
    # metade do que ele serve para mostrar.
    from pathlib import Path as _Path

    from robinbandit import RobinConfig

    config = RobinConfig.from_yaml(_Path(__file__).resolve().parents[1] / "config" / "sentury.yaml")
    return TestClient(create_app([_Fake("groq"), _Fake("gemini")], router, config=config))


def test_pagina_usa_a_paleta_da_marca():
    resposta = _cliente().get("/painel")
    assert resposta.status_code == 200
    for cor in ("#EFE3D2", "#5E7A61", "#E0AF43"):
        assert cor in resposta.text, f"{cor} nao esta na pagina"


def test_o_javascript_chega_junto_com_a_pagina():
    """Os hex da marca vivem so no CSS, entao o teste da paleta prova metade.

    Se o bloco do script virasse vazio, a suite inteira passava e o painel era
    uma pagina morta: desenha o cabecalho e nunca busca `painel/dados`.
    """
    corpo = _cliente().get("/painel").text
    for trecho in ("setInterval(atualizar", "carregarHistorico", "fetch('painel/dados')"):
        assert trecho in corpo, f"{trecho!r} nao esta na pagina"


def test_acento_sobrevive_a_leitura_dos_arquivos():
    """Canario de mojibake.

    O CSS e o JS sao lidos do disco. Sem `encoding="utf-8"` explicito, a
    codificacao da maquina decide — cp1252 no Windows, UTF-8 no Linux — e os
    bytes de `o` acentuado sao validos nas duas: ninguem estoura, e a pagina
    chega escrita errada. So o JS tem 125 acentos.
    """
    corpo = _cliente().get("/painel").text
    for palavra in ("histórico", "saúde", "Latência"):
        assert palavra in corpo, f"{palavra!r} chegou corrompida"


def test_a_pagina_e_montada_uma_vez_so():
    """Um marcador duplicado embutiria o JS duas vezes, e a pagina responderia
    200 do mesmo jeito."""
    from robinbandit.painel import PAGINA

    assert PAGINA.count("<style>") == 1
    # Dois scripts de proposito: o dicionario de traducao vem antes do codigo
    # que o usa, cada um no seu arquivo.
    assert PAGINA.count("<script>") == 2 and PAGINA.count("</script>") == 2
    for marcador in ("/*ESTILO*/", "/*TEXTOS*/", "/*SCRIPT*/"):
        assert marcador not in PAGINA, f"{marcador} sobrou na pagina"
    # A pagina nasce de arquivo agora; ler com newline errado traria CR junto.
    assert "\r" not in PAGINA


def test_ordem_vem_do_router_e_explica_o_motivo():
    dados = _cliente().get("/painel/dados").json()
    ordem = dados["ordem"]
    assert [linha["nome"] for linha in ordem] == ["groq", "gemini"]
    # Quem esta em cooldown diz isso, em vez de so aparecer mais abaixo.
    assert "espera" in ordem[-1]["motivo"]


def test_qualidade_sem_feedback_mostra_saude():
    """Qualidade so existe com feedback. Mostrar "—" nas duas esconderia que o
    router esta decidindo com alguma coisa."""
    dados = _cliente().get("/painel/dados").json()
    primeiro = dados["ordem"][0]["qualidade"]
    assert primeiro != "—"
    assert "saúde" in primeiro or primeiro.replace(".", "").isdigit()


def test_ferramentas_de_cli_apontam_para_este_servidor():
    dados = _cliente().get("/cli-tools").json()
    ids = {f["id"] for f in dados["ferramentas"]}
    assert {"claude-code", "codex", "cline", "opencode", "curl"} <= ids
    for ferramenta in dados["ferramentas"]:
        assert "testserver" in ferramenta["conteudo"], ferramenta["id"]


def test_config_do_codex_e_toml_valido():
    config = cli_tools.uma("codex", "http://localhost:9999")
    assert config["arquivo"] == "~/.codex/config.toml"
    assert 'base_url = "http://localhost:9999/v1"' in config["conteudo"]


def test_config_do_cline_e_json_valido():
    import json

    config = cli_tools.uma("cline", "http://localhost:9999")
    dados = json.loads(config["conteudo"])
    assert dados["cline.openAiBaseUrl"] == "http://localhost:9999/v1"


def test_ferramenta_desconhecida_falha_alto():
    with pytest.raises(KeyError):
        cli_tools.uma("nao-existe", "http://localhost:9999")


def test_logos_sao_servidas_pelo_robinbandit():
    """A arte dos provedores mora com o resto do que e deles; uma copia por
    agente hospedeiro envelhece em ritmos diferentes."""
    cliente = _cliente()
    listagem = cliente.get("/logos").json()["logos"]
    assert "groq.svg" in listagem
    assert cliente.get("/logos/groq.svg").status_code == 200


def test_logo_fora_da_pasta_e_recusada():
    cliente = _cliente()
    assert cliente.get("/logos/..%2f..%2fpyproject.toml").status_code == 404


def test_estrategia_diz_o_que_cada_uma_faz():
    """"adaptive" e "tier" nao explicam nada sozinhas. Quem escolhe precisa
    saber que uma deixa o aprendizado passar por cima do tier e a outra nao."""
    dados = _cliente().get("/config").json()
    assert set(dados["estrategias"]) == {"adaptive", "tier"}
    assert "bônus" in dados["estrategias"]["adaptive"]
    assert "barreira" in dados["estrategias"]["tier"]


def test_trocar_estrategia_vale_sem_reiniciar():
    """Trocar de estrategia e decisao que se toma no meio do dia, olhando a
    conta subir — nao na proxima vez que o servidor subir."""
    cliente = _cliente()
    assert cliente.put("/config/estrategia", json={"valor": "tier"}).json()["estrategia"] == "tier"
    assert cliente.get("/config").json()["estrategia"] == "tier"


def test_estrategia_invalida_e_recusada():
    resposta = _cliente().put("/config/estrategia", json={"valor": "chute"})
    assert resposta.status_code == 400


def test_cadeia_e_tier_convivem():
    """Gravar um nao pode apagar o outro: os dois vivem no mesmo arquivo."""
    cliente = _cliente()
    cliente.put("/config/cadeia", json={"nomes": ["gemini", "groq"]})
    cliente.put("/config/tier", json={"provedor": "gemini", "tier": 3})
    config = cliente.get("/config").json()
    assert config["cadeia"] == ["gemini", "groq"]
    gemini = [p for p in config["provedores"] if p["nome"] == "gemini"][0]
    assert gemini["tier"] == 3


def test_tier_e_grupo_de_provedores():
    """Tier nao e uma posicao na fila: e um grupo, e varios provedores cabem no
    mesmo. Confundir isso vira "escolher quem fica no ranking"."""
    config = _cliente().get("/config").json()
    assert set(config["tiers"]) == {"1", "2", "3", "9"}
    assert config["tiers"]["1"] == "Prioridade alta"
    # 9 e o ultimo recurso: existe, mas ninguem e movido para la.
    assert config["tiers"]["9"] == "Último recurso"
    tiers_usados = {p["tier"] for p in config["provedores"]}
    assert tiers_usados <= {1, 2, 3, 9}


def test_modelos_ordenam_dentro_do_provedor():
    """Tier ordena provedores; isto ordena modelos. "No Claude Code, tente
    Opus; se nao der, Sonnet; por ultimo Haiku"."""
    cliente = _cliente()
    ordem = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
    resposta = cliente.put("/config/modelos", json={"provedor": "claude_code", "modelos": ordem})
    assert resposta.status_code == 200
    assert resposta.json()["modelos"] == ordem


def test_tier_fora_da_faixa_e_recusado():
    assert _cliente().put("/config/tier", json={"provedor": "groq", "tier": 9}).status_code == 400


def test_catalogo_mostra_quem_esta_dentro_e_quem_esta_fora():
    """Da para incluir quem ainda nao esta roteando — e para isso que o
    catalogo aparece junto."""
    dados = _cliente().get("/config").json()
    nomes = {p["nome"] for p in dados["provedores"]}
    assert set(dados["cadeia"]) <= nomes
    assert any(p["na_cadeia"] for p in dados["provedores"])


def test_conta_nao_e_provedor():
    """`ultra` e `ultra_max` batiam no mesmo endpoint do OpenRouter com a mesma
    chave (o segundo caia no primeiro pelo fallback) e so o modelo mudava.
    Como provedores, apareciam como dois OpenRouters a mais — inclusive na tela
    de Modelos, como se tivessem catalogo proprio."""
    dados = _cliente().get("/config").json()
    nomes = {p["nome"] for p in dados["provedores"]}
    assert "ultra" not in nomes and "ultra_max" not in nomes


def test_a_chave_paga_virou_conta_do_openrouter():
    """Os dois modelos dela sao modelos do OpenRouter, escolhiveis como os
    outros; a chave e uma conta dele, marcada como paga."""
    cliente = _cliente()
    modelos = [p for p in cliente.get("/config").json()["provedores"]
               if p["nome"] == "openrouter"][0]["modelos"]
    assert "deepseek/deepseek-v4-pro" in modelos

    contas = cliente.get("/contas").json()
    paga = [c for c in contas["contas"] if c["id"] == "openrouter-paga"]
    assert paga and paga[0]["provider"] == "openrouter" and paga[0]["paga"]
    # Os modos pesados apontam para ela: sem isso cairiam na conta gratuita,
    # que e o oposto do que "Dedicado" quer dizer.
    assert contas["tiers"]["ultra_max"] == "openrouter-paga"


def test_auth_por_cli_nao_pede_chave():
    """Claude Code e Codex autenticam pelo CLI oficial, dono da sessao. So
    `codex_cli` era reconhecido, entao o Claude Code aparecia como "sem chave"
    com o login funcionando — e a tela pedia uma API key que nao existe."""
    contas = _cliente().get("/contas").json()["contas"]
    por_cli = {c["id"]: c for c in contas if c.get("por_cli")}
    assert "claude_code" in por_cli
    assert por_cli["claude_code"]["auth_type"] == "claude_cli"
    assert por_cli["claude_code"]["key_env"] == ""


def test_chave_tem_nome_e_marca_de_paga(monkeypatch, tmp_path):
    """Quatro chaves do mesmo provedor eram quatro dicas de quatro caracteres:
    rotacionar era adivinhar, e a paga ficava indistinguivel das gratuitas."""
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "cofre.json"))
    cliente = _cliente()
    cliente.post("/credenciais", json={
        "variavel": "GROQ_API_KEY", "valor": "chave-gratuita-aaaaaaaa",
        "rotulo": "pessoal",
    })
    cliente.post("/credenciais", json={
        "variavel": "GROQ_API_KEY", "valor": "chave-paga-bbbbbbbbbbbb",
        "rotulo": "empresa", "paga": True,
    })

    linha = [c for c in cliente.get("/credenciais").json()["credenciais"]
             if c["variavel"] == "GROQ_API_KEY"][0]
    assert [k["nome"] for k in linha["chaves"]] == ["pessoal", "empresa"]
    assert [k["paga"] for k in linha["chaves"]] == [False, True]

    # Renomear e remover pela posicao: o valor nao sai daqui, entao e a posicao
    # que o painel conhece.
    assert cliente.put("/credenciais/GROQ_API_KEY/0", json={"rotulo": "outro nome"}).status_code == 200
    assert cliente.delete("/credenciais/GROQ_API_KEY/0").json()["removida"] is True
    linha = [c for c in cliente.get("/credenciais").json()["credenciais"]
             if c["variavel"] == "GROQ_API_KEY"][0]
    assert [k["nome"] for k in linha["chaves"]] == ["empresa"]


def test_ultimo_recurso_fora_do_ranking():
    """O fallback nao e provedor: e o aviso de que ninguem respondeu. No
    ranking, ele competia por qualidade e uptime com quem de fato responde."""
    dados = _cliente().get("/painel/dados").json()
    assert all(linha["nome"] != "fallback" for linha in dados["ordem"])
    assert all(linha["nome"] != "fallback" for linha in dados["provedores"])


def test_numero_sem_historico_e_marcado_como_estimativa():
    """Sem nenhuma chamada, o numero e o prior do catalogo — palpite de fabrica,
    igual para todo mundo. Escrito como "0.60", passava por medicao."""
    dados = _cliente().get("/painel/dados").json()
    sem_uso = [linha for linha in dados["ordem"] if linha["motivo"] == "sem histórico"]
    for linha in sem_uso:
        assert linha["estimado"] is True
        assert linha["qualidade"] == "—" or "estimado" in linha["qualidade"]


def test_credito_devolve_o_nome_da_variavel_nunca_o_valor(monkeypatch):
    """O nome (`GROQ_API_KEY`) diz de onde veio e ajuda a configurar; o valor
    nao pode sair nem em pedaco — nem prefixo, nem sufixo."""
    segredo = "sk-teste-valor-que-nao-pode-vazar-123456"
    monkeypatch.setenv("GROQ_API_KEY", segredo)

    resposta = _cliente().get("/saldo")
    assert resposta.status_code == 200
    texto = resposta.text
    assert segredo not in texto
    assert segredo[:12] not in texto
    assert segredo[-12:] not in texto


def test_dia_ruim_nao_e_o_mesmo_que_provedor_ruim():
    """Um provedor bom que caiu um dia aparece com uptime alto e 1 dia ruim.
    Sem o dia a dia, ele fica indistinguivel de um que falha toda semana."""
    import os
    import tempfile

    os.environ["ROBINBANDIT_HOME"] = tempfile.mkdtemp(prefix="rb-hist-teste-")
    from robinbandit import historico

    historico.esquecer()
    for _ in range(200):
        historico.registrar("bom", ok=True)
    for _ in range(30):
        historico.registrar("bom", ok=False, motivo="529 overloaded")

    resumo = historico.resumo(["bom"], 30)[0]
    assert resumo["dias_ruins"] == 1
    assert resumo["pior_motivo"] == "529 overloaded"
    assert resumo["uptime"] > 80


def test_dia_sem_uso_nao_vira_incidente():
    """Ausencia nao e falha: pintar de vermelho o dia em que ninguem usou
    seria inventar um incidente."""
    import os
    import tempfile

    os.environ["ROBINBANDIT_HOME"] = tempfile.mkdtemp(prefix="rb-hist-vazio-")
    from robinbandit import historico

    historico.esquecer()
    historico.registrar("alguem", ok=True)
    faixa = historico.faixa("alguem", 5)
    assert [d["saude"] for d in faixa[:-1]] == ["vazio"] * 4
    assert faixa[-1]["saude"] == "ok"


def test_o_painel_fala_as_duas_linguas(tmp_path, monkeypatch):
    """A documentacao virou bilingue e a pagina do projeto esta em ingles; quem
    chegasse por la instalava e encontrava a interface so em portugues."""
    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "contas.json"))
    cliente = _cliente()

    config = cliente.get("/config").json()
    assert config["idioma"] in ("pt", "en")
    assert set(config["idiomas"]) == {"pt", "en"}

    assert cliente.put("/config/idioma", json={"valor": "en"}).json()["idioma"] == "en"
    assert cliente.get("/config").json()["idioma"] == "en"


def test_idioma_invalido_e_recusado(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(tmp_path / "contas.json"))
    assert _cliente().put("/config/idioma", json={"valor": "klingon"}).status_code == 400


def test_a_traducao_nao_tem_chave_pela_metade():
    """Uma chave com `pt` e sem `en` some da tela em silencio: o `T()` cai no
    portugues e ninguem percebe ate alguem ler a pagina em ingles."""
    import re

    from robinbandit.painel import pasta_do_painel

    textos = (pasta_do_painel() / "textos.js").read_text(encoding="utf-8")

    # Recorta da chave ate a proxima, em vez de casar `{...}`: os textos tem
    # `{n}` dentro (o lugar do numero), e um `[^}]*` para no primeiro deles.
    marcas = [(m.group(1), m.start()) for m in
              re.finditer(r"'([a-z][a-z._0-9]+)':\s*\{", textos)]
    assert marcas, "nao achei nenhuma entrada no dicionario"

    incompletas = []
    for i, (chave, inicio) in enumerate(marcas):
        fim = marcas[i + 1][1] if i + 1 < len(marcas) else len(textos)
        corpo = textos[inicio:fim]
        if "pt:" not in corpo or "en:" not in corpo:
            incompletas.append(chave)
    assert not incompletas, f"sem par pt/en: {incompletas}"


def test_todo_data_t_do_html_existe_no_dicionario():
    """Marcar um elemento com uma chave que nao existe faz a tela mostrar a
    propria chave — `nav.agora` no lugar de `Agora`."""
    import re

    from robinbandit.painel import pasta_do_painel

    pasta = pasta_do_painel()
    html = (pasta / "pagina.html").read_text(encoding="utf-8")
    textos = (pasta / "textos.js").read_text(encoding="utf-8")

    usadas = set(re.findall(r'data-t(?:-ph)?="([^"]+)"', html))
    definidas = set(re.findall(r"'([a-z][a-z._0-9]+)':\s*\{", textos))

    faltando = sorted(usadas - definidas)
    assert not faltando, f"chaves usadas no HTML e ausentes do dicionario: {faltando}"


def test_os_blocos_que_o_js_esconde_existem_no_html():
    """A tela Agora mostra os primeiros passos enquanto nao ha chamada, e
    esconde os blocos que ficariam vazios. O JS faz isso por id: um id
    renomeado no HTML quebra a tela em silencio, sem erro em lugar nenhum."""
    import re

    from robinbandit.painel import pasta_do_painel

    pasta = pasta_do_painel()
    html = (pasta / "pagina.html").read_text(encoding="utf-8")
    js = (pasta / "painel.js").read_text(encoding="utf-8")

    lista = re.search(r"\['placar',([^\]]*)\]\.forEach", js)
    assert lista, "nao achei a lista de blocos escondidos no painel.js"
    ids = ["placar"] + re.findall(r"'(\w+)'", lista.group(1))

    for alvo in ids:
        assert f'id="{alvo}"' in html, f"o JS esconde #{alvo}, que nao existe no HTML"


def test_cada_bloco_escondido_tem_o_titulo_como_irmao_anterior():
    """O JS esconde o `h2` de cada bloco pegando `previousElementSibling`. Se
    alguem puser qualquer coisa entre o titulo e o bloco, o titulo fica sozinho
    em cima de um espaco vazio."""
    import re

    from robinbandit.painel import pasta_do_painel

    html = (pasta_do_painel() / "pagina.html").read_text(encoding="utf-8")
    tela = re.search(r'<section id="tela-agora".*?</section>', html, re.S).group(0)

    # ordem/credito/historico tem titulo; placar abre a tela e nao tem.
    for alvo in ("ordem", "credito", "historico"):
        antes = tela.split(f'id="{alvo}"')[0]
        # Tira a tag que está sendo aberta (`<div class="carta" `) para sobrar
        # o que veio antes dela. Comparar pela última tag ABERTA acharia o
        # `<span class="risco">` de dentro do h2, que não é irmão de ninguém.
        anterior = re.sub(r"<\w+[^<>]*$", "", antes).rstrip()
        assert anterior.endswith("</h2>"), (
            f"#{alvo} não vem logo depois de um </h2>. O JS esconde o título "
            "por previousElementSibling, e pegaria o elemento errado."
        )
