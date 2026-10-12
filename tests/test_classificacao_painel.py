"""As filas da apresentação persistem sem ativar uma nova rota."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from robinbandit import RobinConfig
from robinbandit.config import caminho_do_catalogo
from robinbandit.routing.router import ProviderRouter
from robinbandit.server import create_app
from robinbandit.state import classificacao


def cliente():
    return TestClient(create_app([], ProviderRouter(), config=RobinConfig.from_yaml(caminho_do_catalogo())))


def test_filas_preservam_ordem_e_nao_ativam_classificador():
    c = cliente()
    filas = c.get("/config/classificacao").json()["filas"]
    modelo = {"provedor": "cerebras", "modelo": "gpt-oss-120b"}
    filas["SIMPLE"] = [modelo, {"provedor": "chatgpt_codex", "modelo": "gpt-5.5"}]
    filas["COMPLEX"] = [modelo]
    antes = c.get("/config").json()
    r = c.put("/config/classificacao", json={"filas": filas})
    assert r.status_code == 200
    assert r.json()["modo"] == "configuracao"
    assert not r.json()["classificador_conectado"]
    assert cliente().get("/config/classificacao").json()["filas"] == filas
    depois = c.get("/config").json()
    assert depois["estrategia"] == antes["estrategia"]
    assert depois["cadeia"] == antes["cadeia"]


@pytest.mark.parametrize("defeito", ["provedor", "nivel", "duplicado", "ativar"])
def test_fila_invalida_nao_e_gravada(defeito):
    c = cliente()
    filas = c.get("/config/classificacao").json()["filas"]
    modelo = {"provedor": "cerebras", "modelo": "gpt-oss-120b"}
    if defeito == "provedor":
        filas["SIMPLE"] = [{**modelo, "provedor": "inexistente"}]
    elif defeito == "nivel":
        filas["outro"] = []
    elif defeito == "duplicado":
        filas["SIMPLE"] = [modelo, modelo]
    corpo = {"filas": filas}
    if defeito == "ativar":
        corpo["modo"] = "ativo"
    assert c.put("/config/classificacao", json=corpo).status_code in (400, 422)
    assert not classificacao.caminho().exists()


def test_arquivo_corrompido_e_preservado():
    alvo = classificacao.caminho()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text("arquivo danificado", encoding="utf-8")
    c = cliente()
    assert c.get("/config/classificacao").status_code == 409
    filas = {n["id"]: [] for n in classificacao.niveis()}
    assert c.put("/config/classificacao", json={"filas": filas}).status_code == 400
    assert alvo.read_text(encoding="utf-8") == "arquivo danificado"


def test_json_valido_com_modelo_invalido_nao_e_substituido():
    import json

    filas = {n["id"]: [] for n in classificacao.niveis()}
    filas["SIMPLE"] = [None]
    alvo = classificacao.caminho()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"filas": filas})
    alvo.write_text(original, encoding="utf-8")
    assert cliente().get("/config/classificacao").status_code == 409
    assert alvo.read_text(encoding="utf-8") == original


def test_escolha_llm_e_contextos_persistem_sem_ativar_rota():
    c = cliente()
    dados = c.get("/config/classificacao").json()
    assert dados["classificador"] == {"tipo": "nenhum", "provedor": "", "modelo": ""}
    contextos = dados["contextos"]
    contextos["COMPLEX"] = "Prefiro estes modelos para programação."
    escolha = {"tipo": "llm", "provedor": "cerebras", "modelo": "modelo-manual-fora-do-catalogo"}
    antes = c.get("/config").json()
    r = c.put("/config/classificacao", json={"filas": dados["filas"], "classificador": escolha, "contextos": contextos})
    assert r.status_code == 200
    salvo = cliente().get("/config/classificacao").json()
    assert salvo["classificador"] == escolha
    assert salvo["contextos"] == contextos
    assert not salvo["classificador_conectado"]
    assert salvo["modo"] == "configuracao"
    depois = c.get("/config").json()
    assert depois["estrategia"] == antes["estrategia"]
    assert depois["cadeia"] == antes["cadeia"]
    assert c.put("/config/classificacao", json={"filas": dados["filas"]}).status_code == 200
    preservado = c.get("/config/classificacao").json()
    assert preservado["classificador"] == escolha
    assert preservado["contextos"] == contextos


def test_arquivo_so_com_filas_ganha_defaults_sem_ser_regravado():
    import json

    alvo = classificacao.caminho()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"filas": {n["id"]: [] for n in classificacao.niveis()}})
    alvo.write_text(original, encoding="utf-8")
    dados = cliente().get("/config/classificacao").json()
    assert dados["classificador"]["tipo"] == "nenhum"
    assert all(v == "" for v in dados["contextos"].values())
    assert alvo.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("escolha", [
    {"tipo": "llm", "provedor": "inexistente", "modelo": "modelo"},
    {"tipo": "llm", "provedor": "fallback", "modelo": "modelo"},
    {"tipo": "llm", "provedor": "cerebras", "modelo": " "},
    {"tipo": "llm", "provedor": "cerebras", "modelo": "modelo\nextra"},
    {"tipo": "nenhum", "provedor": "cerebras", "modelo": "modelo"},
    {"tipo": "outro", "provedor": "cerebras", "modelo": "modelo"},
    {"tipo": "llm", "provedor": "cerebras", "modelo": "modelo", "token": "nao-guardar"},
])
def test_classificador_invalido_nao_e_gravado(escolha):
    c = cliente()
    filas = c.get("/config/classificacao").json()["filas"]
    assert c.put("/config/classificacao", json={"filas": filas, "classificador": escolha}).status_code in (400, 422)
    assert not classificacao.caminho().exists()


def test_contexto_invalido_nao_substitui_configuracao():
    c = cliente()
    dados = c.get("/config/classificacao").json()
    assert c.put("/config/classificacao", json={"filas": dados["filas"]}).status_code == 200
    original = classificacao.caminho().read_bytes()
    for contextos in ({}, {**dados["contextos"], "EXTRA": "outro"},
                      {**dados["contextos"], "COMPLEX": "x" * 2001},
                      {**dados["contextos"], "COMPLEX": "texto\x00"}):
        assert c.put("/config/classificacao", json={"filas": dados["filas"], "contextos": contextos}).status_code == 400
        assert classificacao.caminho().read_bytes() == original


def test_contexto_corrompido_no_disco_e_preservado():
    import json

    alvo = classificacao.caminho()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"filas": {n["id"]: [] for n in classificacao.niveis()}, "contextos": {"COMPLEX": "incompleto"}})
    alvo.write_text(original, encoding="utf-8")
    assert cliente().get("/config/classificacao").status_code == 409
    assert alvo.read_text(encoding="utf-8") == original


def test_interface_configura_recolhe_e_mostra_classificacao(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    c = cliente()
    requisicoes = []
    nivel_fake = "STANDARD"

    def atender(route):
        from urllib.parse import urlsplit
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != "painel.test":
            route.abort()
            return
        requisicoes.append((req.method, url.path))
        assert not url.path.startswith("/v1/")
        if url.path.startswith("/login/"):
            route.fulfill(json={"configurada": False, "instalado": False, "contas": [], "estado": "desconectado"})
            return
        if url.path == "/config/classificacao/testar":
            route.fulfill(json={"nivel": nivel_fake, "modelo": "modelo-manual", "duracao_ms": 100})
            return
        r = c.request(req.method, url.path + ("?" + url.query if url.query else ""),
                      content=req.post_data, headers={"content-type": "application/json"})
        route.fulfill(status=r.status_code, body=r.content, content_type=r.headers.get("content-type"))

    with pw.sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(tmp_path / "perfil"), channel="chrome", headless=True,
                                                   viewport={"width": 1366, "height": 1000})
        try:
            page = ctx.pages[0]
            page.add_init_script("""
                window.piscadasObservadas=0;
                const animate=Element.prototype.animate;
                Element.prototype.animate=function(...args){
                  if(this.classList.contains('clf-olho'))window.piscadasObservadas++;
                  return animate.apply(this,args);
                };
            """)
            erros = []
            page.on("pageerror", lambda e: erros.append(str(e)))
            page.route("**/*", atender)
            page.goto("http://painel.test/painel?tela=provedores&classificador=1")
            page.locator("#modo-rota").select_option("classifier")
            pw.expect(page.locator("#rota-atual")).to_be_hidden()
            pw.expect(page.locator("#modo-rota")).to_have_value("classifier")
            pw.expect(page.locator("#modo-rota")).to_have_count(1)
            pw.expect(page.locator("#abrir-classificador, #clf-nivel, #clf-simular")).to_have_count(0)
            assert not page.locator("#clf-config").evaluate("el=>el.open")
            assert not page.locator("#clf-catalogo-painel").evaluate("el=>el.open")
            assert page.locator("#clf-teste-pedido").input_value().strip()
            assert page.locator("#clf-teste").bounding_box()["height"] < 180
            assert page.locator("#clf-testar").bounding_box()["y"] < page.locator("#clf-mapa").bounding_box()["y"]
            page.locator("#clf-catalogo-painel > summary").click()
            busca = page.locator("#clf-busca")
            busca.fill("cerebras")
            page.locator("#clf-catalogo .clf-modelo-nome").first.click()
            page.locator("#clf-destino").select_option("STANDARD")
            page.locator("#clf-escolha").get_by_role("button", name="Adicionar", exact=True).click()
            origem = page.locator("#clf-catalogo .clf-modelo").first
            caixa = page.locator('[data-caixa="COMPLEX"]')
            origem.drag_to(caixa.locator(".clf-fila"))
            pw.expect(caixa.locator(".clf-modelo")).to_have_count(1)
            busca.fill("groq")
            page.locator("#clf-catalogo .clf-modelo-nome").first.click()
            page.locator("#clf-destino").select_option("STANDARD")
            page.locator("#clf-escolha").get_by_role("button", name="Adicionar", exact=True).click()
            standard = page.locator('[data-caixa="STANDARD"]')
            pw.expect(standard.locator(".clf-modelo")).to_have_count(2)
            standard.get_by_role("button", name="Opções de").last.click()
            standard.get_by_role("button", name="Mover antes:").last.click()
            page.locator("#clf-catalogo-painel > summary").click()
            page.locator("#clf-config > summary").click()
            page.locator("#clf-tipo").select_option("llm")
            page.locator("#clf-provedor").select_option("cerebras")
            page.locator("#clf-modelo").fill("modelo-manual-fora-do-catalogo")
            pw.expect(page.locator("#clf-modelo-aviso")).to_contain_text("não verificado")
            page.locator("#clf-add-modelo").click()
            page.locator("#clf-provedor").select_option("groq")
            page.locator("#clf-modelo").fill("outro-classificador")
            page.locator("#clf-add-modelo").click()
            pw.expect(page.locator("#clf-lista-config .clf-classificador-item")).to_have_count(2)
            pw.expect(page.locator("#clf-lista-config .clf-classificador-item").first).to_contain_text("modelo-manual-fora-do-catalogo")
            antes_contexto = page.locator("#clf-caixas").evaluate("el=>Array.from(el.children,c=>{const r=c.getBoundingClientRect();return [r.x+scrollX,r.y+scrollY,r.width,r.height];})")
            caixa.locator(".clf-contexto-detalhe > summary").click()
            assert page.locator("#clf-caixas").evaluate("el=>Array.from(el.children,c=>{const r=c.getBoundingClientRect();return [r.x+scrollX,r.y+scrollY,r.width,r.height];})") == antes_contexto
            pw.expect(page.locator("#clf-ativacao")).to_contain_text("Classificador selecionado")
            page.locator("#clf-contexto-COMPLEX").fill("Prefiro estes modelos para código.")
            page.locator("#clf-salvar").click()
            pw.expect(page.locator("#clf-status")).to_contain_text("Configuração salva")
            salvo = c.get("/config/classificacao").json()
            assert salvo["filas"]["STANDARD"][0]["provedor"] == "groq"
            assert salvo["filas"]["COMPLEX"][0]["provedor"] == "cerebras"
            assert salvo["classificador"]["modelo"] == "modelo-manual-fora-do-catalogo"
            assert salvo["classificador"]["reservas"] == [{"provedor": "groq", "modelo": "outro-classificador"}]
            page.locator("#clf-config > summary").click()
            for nivel_fake, x, y in (("STANDARD", "10px", "-12px"), ("SIMPLE", "-10px", "-12px"),
                                     ("COMPLEX", "-10px", "12px"), ("CRITICAL", "10px", "12px")):
                page.locator("#clf-testar").click()
                pw.expect(page.locator("#clf-status")).to_contain_text("Classificação: " + nivel_fake)
                pw.expect(page.locator('.clf-caixa.escolhida')).to_have_count(1)
                assert page.locator(".clf-olhos").evaluate("el=>el.style.getPropertyValue('--olhar-x')") == x
                assert page.locator(".clf-olhos").evaluate("el=>el.style.getPropertyValue('--olhar-y')") == y
            assert page.locator('[data-caixa="CRITICAL"]').evaluate("el=>getComputedStyle(el).outlineStyle") == "solid"
            rosto = page.locator(".clf-olhos").bounding_box()
            assert abs(rosto["width"] - rosto["height"]) < 1
            assert page.locator(".clf-olho i").count() == 0
            page.screenshot(path=str(tmp_path / "classificador-desktop.png"), full_page=True)
            page.evaluate("Math.random=()=>0.25")
            antes = page.evaluate("window.piscadasObservadas")
            page.wait_for_function("antes=>window.piscadasObservadas>antes", arg=antes, timeout=9000)
            pw.expect(page.locator('[data-caixa="CRITICAL"]')).to_have_class("clf-caixa escolhida")
            page.emulate_media(reduced_motion="reduce")
            page.wait_for_function("document.querySelector('.clf-olhos').getAnimations({subtree:true}).length===0")
            page.reload()
            page.locator("#clf-config > summary").click()
            pw.expect(page.locator("#clf-lista-config .clf-classificador-item")).to_have_count(2)
            caixa.locator(".clf-contexto-detalhe > summary").click()
            pw.expect(page.locator("#clf-contexto-COMPLEX")).to_have_value("Prefiro estes modelos para código.")
            page.locator("#clf-contexto-COMPLEX").fill("Alteração descartada")
            page.locator("#clf-descartar").click()
            pw.expect(page.locator("#clf-contexto-COMPLEX")).to_have_value("Prefiro estes modelos para código.")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not erros, erros
            assert all(m == "GET" or (m == "PUT" and path in {"/config/classificacao", "/config/estrategia"})
                       or (m == "POST" and path == "/config/classificacao/testar") for m, path in requisicoes)
        finally:
            ctx.close()
