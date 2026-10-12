"""A tela de uso acompanha novas chamadas sem exigir recarregar a página."""
import pytest

from fastapi.testclient import TestClient
from robinbandit import RobinConfig
from robinbandit.config import caminho_do_catalogo
from robinbandit.gateway import RobinGateway
from robinbandit.server import create_app
from robinbandit.state import classificacao, uso
from robinbandit.accounts import account_config


def test_uso_atualiza_ao_testar_abrir_aba_e_receber_nova_chamada(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    cfg = RobinConfig.from_yaml(caminho_do_catalogo())
    classificacao.guardar({n["id"]: [] for n in classificacao.niveis()}, cfg.providers,
                         {"tipo": "llm", "provedor": "gemini", "modelo": "gemini-2.5-flash"})
    account_config.definir_estrategia("classifier")
    c = TestClient(create_app([], RobinGateway(cfg).router, config=cfg))
    requests = []
    medicao = {"entrada": 359, "saida": 2, "raciocinio": 490, "total": 851}

    def atender(route):
        from urllib.parse import urlsplit

        req = route.request
        url = urlsplit(req.url)
        if url.hostname != "painel.test":
            route.abort()
            return
        requests.append((req.method, url.path))
        assert not url.path.startswith("/v1/")
        if url.path.startswith("/login/"):
            route.fulfill(json={"configurada": False, "instalado": False, "contas": [], "estado": "desconectado"})
            return
        if url.path == "/config/classificacao/testar":
            uso.registrar("gemini", medicao)
            route.fulfill(json={"nivel": "STANDARD", "modelo": "gemini-2.5-flash", "duracao_ms": 100, "uso": medicao})
            return
        r = c.request(req.method, url.path + ("?" + url.query if url.query else ""),
                      content=req.post_data, headers={"content-type": "application/json"})
        route.fulfill(status=r.status_code, body=r.content, content_type=r.headers.get("content-type"))

    with pw.sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(tmp_path / "perfil"), channel="chrome", headless=True,
                                                   viewport={"width": 1366, "height": 1000})
        try:
            page = ctx.pages[0]
            erros = []
            page.on("pageerror", lambda e: erros.append(str(e)))
            page.route("**/*", atender)
            page.goto("http://painel.test/painel?tela=provedores")
            pw.expect(page.locator("#clf-testar")).to_be_enabled()
            anteriores = requests.count(("GET", "/uso"))
            page.locator("#clf-testar").click()
            pw.expect(page.locator("#clf-status")).to_contain_text("490 raciocínio")
            pw.expect(page.locator("#uso-provedores")).to_contain_text("490 raciocínio")
            assert requests.count(("GET", "/uso")) > anteriores
            anteriores = requests.count(("GET", "/uso"))
            page.locator('nav [data-tela="uso"]').click()
            page.locator("#uso-detalhe > summary").click()
            pw.expect(page.locator("#uso-provedores")).to_be_visible()
            page.wait_for_function("document.querySelector('#uso-numeros').textContent.includes('851')")
            assert requests.count(("GET", "/uso")) > anteriores
            uso.registrar("gemini", medicao)
            pw.expect(page.locator("#uso-provedores")).to_contain_text("1,7 mil", timeout=9000)
            pw.expect(page.locator("#uso-provedores")).to_contain_text("980 raciocínio")
            assert c.get("/uso?dias=30").json()["total"]["total"] == 1702
            assert not erros
        finally:
            ctx.close()
