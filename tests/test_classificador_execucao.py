"""A classificação é explícita, mensurável e não interfere na seleção dedicada."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from robinbandit import RobinConfig
from robinbandit.accounts import account_config
from robinbandit.config import caminho_do_catalogo
from robinbandit.gateway import RobinGateway
from robinbandit.routing.chain import ChainProvider, FalhaDaCadeia
from robinbandit.routing import classificador_execucao as execucao
from robinbandit.routing.classificacao import contrato
from robinbandit.routing.selection import RouteSelection
from robinbandit.server import create_app
from robinbandit.state import classificacao, uso


class Provedor:
    supports_tools = True
    capabilities = {"vision"}

    def __init__(self, nome, modelo, resposta, chamadas):
        self.name = nome
        self.models = [modelo]
        self.last_model = modelo
        self.last_usage = {"entrada": 5, "saida": 1, "total": 6}
        self.last_tool_calls = None
        self.resposta = resposta
        self.chamadas = chamadas

    async def complete(self, messages, temperature=0.2, **kwargs):
        self.chamadas.append((self.name, self.models[0], messages, kwargs))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


def preparar(monkeypatch, respostas=None):
    config = RobinConfig.from_yaml(caminho_do_catalogo())
    chamadas = []
    respostas = respostas or {}

    async def construir(config, alvo):
        resposta = respostas.get(alvo["modelo"], "resposta da caixa")
        return Provedor(alvo["provedor"], alvo["modelo"], resposta, chamadas)

    monkeypatch.setattr(execucao, "construir", construir)
    filas = {r: [] for r in contrato()["rotulos"]}
    escolha = {"tipo": "llm", "provedor": "cerebras", "modelo": "classifica"}
    return config, chamadas, filas, escolha


def test_teste_usa_rascunho_sem_chamar_caixa_ou_ativar_modo(monkeypatch):
    config, chamadas, filas, escolha = preparar(monkeypatch, {"classifica": "COMPLEX"})
    c = TestClient(create_app([], RobinGateway(config).router, config=config))
    antes = account_config.estrategia()
    contextos = {r: "" for r in filas}
    contextos["COMPLEX"] = "Modelos preferidos para código"
    r = c.post("/config/classificacao/testar", json={"pedido": "请分析代码", "classificador": escolha, "contextos": contextos})
    assert r.status_code == 200
    assert r.json()["nivel"] == "COMPLEX"
    assert len(chamadas) == 1
    assert chamadas[0][1] == "classifica"
    assert json.loads(chamadas[0][2][1]["content"])["contextos_dos_niveis"] == contextos
    assert chamadas[0][3]["strict_model"]
    assert account_config.estrategia() == antes
    assert not classificacao.caminho().exists()
    assert uso.total(30)["chamadas"] == 1


def test_reserva_classifica_apos_saida_invalida_sem_vazar_texto(monkeypatch):
    config, chamadas, filas, escolha = preparar(monkeypatch, {"classifica": "COMPLEX porque contém segredo", "reserva": "SIMPLE"})
    escolha["reservas"] = [{"provedor": "groq", "modelo": "reserva"}]
    c = TestClient(create_app([], RobinGateway(config).router, config=config))
    r = c.post("/config/classificacao/testar", json={"pedido": "olá", "classificador": escolha, "contextos": {r: "" for r in filas}})
    assert r.status_code == 200
    assert r.json()["nivel"] == "SIMPLE"
    assert [a[1] for a in chamadas] == ["classifica", "reserva"]
    assert "segredo" not in r.text


def test_teste_falha_clara_sem_devolver_erro_do_sdk(monkeypatch):
    config, _, filas, escolha = preparar(monkeypatch, {"classifica": RuntimeError("Bearer segredo-do-sdk")})
    c = TestClient(create_app([], RobinGateway(config).router, config=config))
    r = c.post("/config/classificacao/testar", json={"pedido": "teste", "classificador": escolha, "contextos": {r: "" for r in filas}})
    assert r.status_code == 502
    assert "nível válido" in r.json()["detail"]
    assert "segredo-do-sdk" not in r.text


def test_modo_incompleto_pode_ser_escolhido_mas_nao_responde(monkeypatch):
    config, _, filas, escolha = preparar(monkeypatch)
    chamadas = []
    c = TestClient(create_app([Provedor("cerebras", "normal", "normal", chamadas)], RobinGateway(config).router, config=config))
    assert c.put("/config/estrategia", json={"valor": "classifier"}).status_code == 200
    r = c.post("/v1/chat/completions", json={"model": "normal", "messages": [{"role": "user", "content": "olá"}]})
    assert r.status_code == 502
    assert "incompleta" in r.text
    assert chamadas == []
    classificacao.guardar(filas, config.providers, escolha)
    assert c.put("/config/estrategia", json={"valor": "classifier"}).status_code == 200
    filas["STANDARD"] = [{"provedor": "groq", "modelo": "caixa"}]
    classificacao.guardar(filas, config.providers, escolha)
    assert c.put("/config/estrategia", json={"valor": "classifier"}).status_code == 200
    assert account_config.estrategia() == "classifier"


@pytest.mark.asyncio
async def test_caixa_respeita_ordem_e_fallback_para_vizinha_mais_alta(monkeypatch):
    config, chamadas, filas, escolha = preparar(monkeypatch, {"classifica": "STANDARD", "primeiro": RuntimeError("falhou"), "segundo": RuntimeError("falhou")})
    filas["STANDARD"] = [{"provedor": "groq", "modelo": "primeiro"}, {"provedor": "cerebras", "modelo": "segundo"}]
    filas["COMPLEX"] = [{"provedor": "groq", "modelo": "acima"}]
    filas["SIMPLE"] = [{"provedor": "cerebras", "modelo": "abaixo"}]
    classificacao.guardar(filas, config.providers, escolha)
    account_config.definir_estrategia("classifier")
    normal = Provedor("cerebras", "normal", "normal", chamadas)
    cadeia = ChainProvider([normal], RobinGateway(config))
    assert await cadeia.complete([{"role": "user", "content": "pedido"}]) == "resposta da caixa"
    assert [a[1] for a in chamadas] == ["classifica", "primeiro", "segundo", "acima"]
    assert cadeia.last_model == "acima"


@pytest.mark.asyncio
@pytest.mark.parametrize("selecao", [RouteSelection.strict("cerebras:normal"), RouteSelection.hybrid("cerebras:normal")])
async def test_selecao_explicita_nao_chama_classificador(monkeypatch, selecao):
    config, chamadas, filas, escolha = preparar(monkeypatch, {"classifica": "COMPLEX"})
    classificacao.guardar(filas, config.providers, escolha)
    account_config.definir_estrategia("classifier")
    cadeia = ChainProvider([Provedor("cerebras", "normal", "normal", chamadas)], RobinGateway(config))
    assert await cadeia.complete([{"role": "user", "content": "pedido"}], selection=selecao) == "normal"
    assert [a[1] for a in chamadas] == ["normal"]


@pytest.mark.asyncio
async def test_classificacao_invalida_mantem_rota_adaptativa(monkeypatch):
    config, chamadas, filas, escolha = preparar(monkeypatch, {"classifica": "explicação inválida"})
    filas["STANDARD"] = [{"provedor": "groq", "modelo": "caixa"}]
    classificacao.guardar(filas, config.providers, escolha)
    account_config.definir_estrategia("classifier")
    cadeia = ChainProvider([Provedor("cerebras", "normal", "normal", chamadas)], RobinGateway(config))
    assert await cadeia.complete([{"role": "user", "content": "pedido"}]) == "normal"
    assert [a[1] for a in chamadas] == ["classifica", "normal"]


@pytest.mark.asyncio
async def test_todas_caixas_esgotadas_nao_chamam_modelo_fora_delas(monkeypatch):
    config, chamadas, filas, escolha = preparar(monkeypatch, {"classifica": "COMPLEX", "caixa": RuntimeError("falhou")})
    filas["COMPLEX"] = [{"provedor": "groq", "modelo": "caixa"}]
    classificacao.guardar(filas, config.providers, escolha)
    account_config.definir_estrategia("classifier")
    cadeia = ChainProvider([Provedor("cerebras", "normal", "normal", chamadas)], RobinGateway(config))
    with pytest.raises(FalhaDaCadeia, match="esgotaram"):
        await cadeia.complete([{"role": "user", "content": "pedido"}])
    assert [a[1] for a in chamadas] == ["classifica", "caixa"]


def test_reservas_duplicadas_nao_sao_salvas(monkeypatch):
    config, _, filas, escolha = preparar(monkeypatch)
    escolha["reservas"] = [{"provedor": escolha["provedor"], "modelo": escolha["modelo"]}]
    with pytest.raises(ValueError, match="repetir"):
        classificacao.guardar(filas, config.providers, escolha)
    assert not classificacao.caminho().exists()


def test_proximidade_e_ordem_estaveis():
    assert execucao.ordem_dos_niveis("STANDARD") == ["STANDARD", "COMPLEX", "SIMPLE", "CRITICAL"]
    assert execucao.ordem_dos_niveis("COMPLEX") == ["COMPLEX", "CRITICAL", "STANDARD", "SIMPLE"]


@pytest.mark.asyncio
async def test_uso_do_classificador_e_capturado_na_tarefa_certa(monkeypatch):
    import contextvars

    config, _, filas, escolha = preparar(monkeypatch)

    class ComUsoLocal:
        def __init__(self):
            self._uso = contextvars.ContextVar("uso-classificador", default=None)
            self.last_tool_calls = None

        @property
        def last_usage(self):
            return self._uso.get()

        async def complete(self, messages, temperature=0, **kwargs):
            self._uso.set({"entrada": 21, "saida": 2, "total": 23})
            return "SIMPLE"

    async def construir(*args):
        return ComUsoLocal()

    monkeypatch.setattr(execucao, "construir", construir)
    assert (await execucao.classificar(config, escolha, "olá"))["nivel"] == "SIMPLE"
    assert uso.total(30)["total"] == 23


@pytest.mark.asyncio
async def test_cancelamento_nao_e_transformado_em_fallback(monkeypatch):
    config, _, _, escolha = preparar(monkeypatch)

    async def cancelar(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(execucao, "construir", cancelar)
    with pytest.raises(asyncio.CancelledError):
        await execucao.classificar(config, escolha, "olá")


@pytest.mark.asyncio
async def test_rota_auxiliar_nao_herda_modo_classificador(monkeypatch):
    from robinbandit import build_route

    config, chamadas, _, _ = preparar(monkeypatch)
    config.routes["auxiliar"] = {"chain_order": ["cerebras"], "models": {"cerebras": ["auxiliar"]}}
    monkeypatch.setattr("robinbandit.providers.build_provider",
                        lambda config, chave, settings=None, models=None, **kw: Provedor(chave, models[0], "resumo", chamadas))
    account_config.definir_estrategia("classifier")
    rota = build_route(config, "auxiliar")
    assert await rota.complete([{"role": "user", "content": "resuma"}]) == "resumo"
    assert [c[1] for c in chamadas] == ["auxiliar"]


def test_rosto_arrasto_reservas_popover_e_teste_da_interface(monkeypatch, tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    config, _, _, _ = preparar(monkeypatch)
    c = TestClient(create_app([], RobinGateway(config).router, config=config))
    testes = []

    async def classificar(config, escolha, pedido, contexto, contextos, atividade):
        testes.append((escolha, pedido, contextos))
        return {"nivel": "COMPLEX", "provedor": escolha["provedor"], "modelo": escolha["modelo"], "duracao_ms": 100}

    monkeypatch.setattr(execucao, "classificar", classificar)

    def atender(route):
        from urllib.parse import urlsplit

        req = route.request
        url = urlsplit(req.url)
        if url.hostname != "painel.test":
            route.abort()
            return
        assert not url.path.startswith("/v1/")
        if url.path.startswith("/login/"):
            route.fulfill(json={"configurada": False, "instalado": False, "contas": [], "estado": "desconectado"})
            return
        r = c.request(req.method, url.path + ("?" + url.query if url.query else ""),
                      content=req.post_data, headers={"content-type": "application/json"})
        route.fulfill(status=r.status_code, body=r.content, content_type=r.headers.get("content-type"))

    with pw.sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(tmp_path / "perfil"), channel="chrome", headless=True,
                                                   viewport={"width": 1366, "height": 1800})
        try:
            page = ctx.pages[0]
            erros = []
            page.on("pageerror", lambda e: erros.append(str(e)))
            page.route("**/*", atender)
            page.goto("http://painel.test/painel?tela=provedores&classificador=1")
            page.locator("#modo-rota").select_option("classifier")
            page.locator("#clf-catalogo-painel > summary").click()
            page.locator("#clf-busca").fill("cerebras")
            page.locator("#clf-catalogo .clf-modelo").first.drag_to(page.locator("#clf-rosto"))
            pw.expect(page.locator("#clf-lista-classificadores .clf-classificador-item")).to_have_count(1)
            primeiro = page.locator("#clf-lista-classificadores .clf-classificador-item span").first.inner_text()
            page.locator("#clf-busca").fill("groq")
            page.locator("#clf-catalogo .clf-modelo").first.drag_to(page.locator("#clf-rosto"))
            pw.expect(page.locator("#clf-lista-classificadores .clf-classificador-item")).to_have_count(2)
            segundo = page.locator("#clf-lista-classificadores .clf-classificador-item span").last.inner_text()
            page.locator("#clf-lista-classificadores").get_by_role("button", name="Mover antes:").last.click()
            pw.expect(page.locator("#clf-gerir")).to_be_visible()
            pw.expect(page.locator("#clf-lista-classificadores .clf-classificador-item span").first).to_have_text(segundo.replace("2. ", "1. "))
            page.keyboard.press("Escape")
            pw.expect(page.locator("#clf-gerir")).to_be_hidden()
            page.locator("#clf-rosto").click()
            pw.expect(page.locator("#clf-gerir")).to_be_visible()
            assert page.locator("#clf-gerir").evaluate("el=>el.parentElement===document.body")
            assert page.locator("#clf-gerir").evaluate("el=>{const r=el.getBoundingClientRect();return r.x>=0 && r.y>=0 && r.right<=innerWidth && r.bottom<=innerHeight;}")
            page.locator("#clf-lista-classificadores").get_by_role("button", name="Remover classificador:").last.click()
            pw.expect(page.locator("#clf-lista-classificadores .clf-classificador-item")).to_have_count(1)
            assert "Groq" in page.locator("#clf-lista-classificadores .clf-classificador-item span").first.inner_text()
            page.keyboard.press("Escape")
            page.locator("#clf-teste-pedido").fill("Analise meu código")
            page.locator('[data-caixa="COMPLEX"] .clf-contexto-detalhe > summary').click()
            page.locator("#clf-contexto-COMPLEX").fill("Meus modelos preferidos para programação")
            page.locator("#clf-testar").click()
            pw.expect(page.locator("#clf-status")).to_contain_text("Classificação: COMPLEX")
            pw.expect(page.locator('[data-caixa="COMPLEX"]')).to_have_class("clf-caixa escolhida")
            assert len(testes) == 1
            assert testes[0][2]["COMPLEX"] == "Meus modelos preferidos para programação"
            assert not classificacao.caminho().exists()
            assert account_config.estrategia() == "classifier"
            assert not erros
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            ctx.close()
