"""A página montada precisa iniciar e filtrar sem perder o que foi digitado."""
import json

import pytest

pytest.importorskip("fastapi")
playwright = pytest.importorskip("playwright.sync_api")

from fastapi.testclient import TestClient
from robinbandit import RobinConfig
from robinbandit.config import caminho_do_catalogo
from robinbandit.routing.router import ProviderRouter
from robinbandit.server import create_app


@pytest.mark.parametrize("estrategia", ["adaptive", "fixed", "round_robin"])
def test_pagina_completa_abre_busca_e_preserva_rascunho(tmp_path, estrategia):
    from types import SimpleNamespace

    config = RobinConfig.from_yaml(caminho_do_catalogo())
    provedores = [SimpleNamespace(name="cerebras"), SimpleNamespace(name="groq")]
    cliente = TestClient(create_app(provedores, ProviderRouter(), config=config))
    cliente.put("/config/estrategia", json={"valor": estrategia})

    def atender(route):
        from urllib.parse import urlsplit

        url = urlsplit(route.request.url)
        if url.hostname != "painel.test":
            route.abort()
            return
        assert route.request.method == "GET", "O teste não inicia login nem grava configuração."
        if url.path.startswith("/login/"):
            route.fulfill(json={"configurada": False, "instalado": False,
                                "disponivel": False, "contas": [], "estado": "desconectado"})
            return
        resposta = cliente.get(url.path + ("?" + url.query if url.query else ""))
        route.fulfill(status=resposta.status_code, body=resposta.content,
                      content_type=resposta.headers.get("content-type", "application/json"))

    with playwright.sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            str(tmp_path / "perfil"), channel="chrome", headless=True,
            viewport={"width": 1366, "height": 768},
        )
        try:
            pagina = contexto.pages[0]
            erros = []
            pagina.on("pageerror", lambda erro: erros.append(str(erro)))
            pagina.route("**/*", atender)
            pagina.goto("http://painel.test/painel?tela=provedores")
            busca = pagina.locator("#buscar-provedor")
            playwright.expect(pagina.locator("#busca-provedores #buscar-provedor")).to_be_visible()
            assert busca.bounding_box()["y"] > pagina.locator("#tela-provedores h1").bounding_box()["y"]
            busca.fill("cerebras")
            ordenada = estrategia in ("fixed", "round_robin")
            cartao = pagina.locator("#ordem-cadeia .lista-cadeia li:visible" if ordenada else "#tiers .grade > div:visible")
            playwright.expect(cartao).to_have_count(1)
            playwright.expect(cartao).to_contain_text("Cerebras")
            if ordenada:
                assert busca.bounding_box()["y"] < cartao.bounding_box()["y"]
                playwright.expect(cartao.locator('[data-move="1"]')).to_be_enabled()
                playwright.expect(pagina.locator("#tiers")).to_be_hidden()
                pagina.locator('nav [data-tela="credenciais"]').click()
            else:
                cartao.get_by_role("button", name="Configurar").click()
            credencial = pagina.locator("#credenciais .cred:visible")
            playwright.expect(credencial).to_have_count(1)
            playwright.expect(pagina.locator("#busca-credenciais #buscar-provedor")).to_be_visible()
            entrada = credencial.locator('input[type="password"]')
            entrada.fill("rascunho-ficticio")
            busca.fill("groq")
            busca.fill("cerebras")
            playwright.expect(entrada).to_have_value("rascunho-ficticio")
            pagina.locator('nav [data-tela="modelos"]').click()
            playwright.expect(pagina.locator("#busca-modelos #buscar-provedor")).to_be_visible()
            filtro = pagina.locator("#filtro-modelos").bounding_box()
            campo = busca.bounding_box()
            assert campo["x"] > filtro["x"] + filtro["width"]
            assert abs(campo["y"] - filtro["y"]) < 8
            pagina.screenshot(path=str(tmp_path / "modelos-notebook.png"))
            pagina.set_viewport_size({"width": 390, "height": 844})
            filtro = pagina.locator("#filtro-modelos").bounding_box()
            assert busca.bounding_box()["y"] >= filtro["y"] + filtro["height"]
            assert pagina.evaluate("document.documentElement.scrollWidth <= innerWidth")
            pagina.screenshot(path=str(tmp_path / "modelos-celular.png"), full_page=True)
            busca.fill("不存在的提供商")
            playwright.expect(pagina.locator("#busca-vazia")).to_be_visible()
            pagina.locator("#limpar-busca").focus()
            pagina.keyboard.press("Enter")
            playwright.expect(busca).to_have_value("")
            playwright.expect(busca).to_be_focused()
            assert erros == [], json.dumps(erros, ensure_ascii=False)
        finally:
            contexto.close()
