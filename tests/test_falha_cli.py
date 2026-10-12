"""Falhas de assinatura conservam identidade sem devolver a saída privada do CLI."""
import json

import pytest

from robinbandit.providers import ReinforcedProvider
from robinbandit.providers.claude_code_provider import ClaudeCodeError, ClaudeCodeProvider, _ler_stream
from robinbandit.providers.codex_provider import CodexAuthStatus, CodexProvider
from robinbandit.providers.erro_cli import classificar_cli
from robinbandit.routing.chain import ChainProvider, FalhaDaCadeia
from robinbandit.routing.erros import classificar
from robinbandit.routing.router import ProviderRouter
from robinbandit.state.atividade import Atividade


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("texto,tipo", [
    ("You've hit your limit", "credit"),
    ("OAuth token expired", "auth"),
    ("CLI não instalado", "not_found"),
])
def test_erro_publico_classificado_sem_saida_privada(cli, texto, tipo):
    falha = classificar_cli(RuntimeError(texto + " token-privado-exemplo"), cli, "conta-trabalho")
    assert classificar(falha) == tipo
    assert "conta-trabalho" in str(falha)
    assert "token-privado-exemplo" not in str(falha)
    assert falha.conta_inteira


def test_stream_de_falha_conserva_lista_de_erros():
    erro = _ler_stream(json.dumps({"type": "result", "is_error": True,
                                  "errors": ["You've hit your limit"]}))
    assert erro["erro"] == "You've hit your limit"


async def test_claude_limite_nao_tenta_todos_os_modelos(monkeypatch):
    monkeypatch.setattr(ClaudeCodeProvider, "configured", property(lambda _: True))
    provedor = ClaudeCodeProvider(models=["haiku", "sonnet"])
    pedidos = []

    async def falhar(*args, **kwargs):
        pedidos.append(kwargs["model"])
        raise ClaudeCodeError("You've hit your limit token-privado-exemplo")

    monkeypatch.setattr(provedor, "generate", falhar)
    with pytest.raises(RuntimeError) as erro:
        await provedor.complete([{"role": "user", "content": "oi"}])
    assert classificar(erro.value) == "credit"
    assert pedidos == ["haiku"]
    assert provedor.last_attempted_model == "claude_code:haiku"


async def test_codex_login_falhou_nao_reusa_metadados(monkeypatch):
    monkeypatch.setattr("robinbandit.providers.codex_provider.codex_auth_status",
                        lambda _: CodexAuthStatus(False, "codex_cli", "execute: codex login"))
    provedor = CodexProvider(["modelo"])
    provedor.last_model = "modelo-de-outro-turno"
    with pytest.raises(RuntimeError) as erro:
        await provedor.complete([{"role": "user", "content": "oi"}])
    assert classificar(erro.value) == "auth"
    assert provedor.last_model is None and provedor.last_attempted_model is None


class ContaEsgotada:
    name = "claude_code"
    supports_tools = True
    models = ["haiku"]
    last_model = None
    last_attempted_model = "claude_code:haiku"

    async def complete(self, messages, temperature=0.2, tools=None):
        raise classificar_cli(RuntimeError("You've hit your limit"), "claude", self.name)


@pytest.mark.parametrize("runtime", [False, True])
async def test_cadeia_conserva_conta_modelo_e_tipo_no_grupo(runtime):
    from robinbandit.routing.sentury import ChainProvider as CadeiaDoRuntime, use_ultra_provider, clear_ultra_provider

    grupo = ReinforcedProvider([ContaEsgotada()], name="ultra_max")
    atividade = Atividade(persistir=True)
    cadeia = CadeiaDoRuntime([grupo], activity=atividade) if runtime else ChainProvider([grupo], ProviderRouter(), activity=atividade)
    cadeia.router.order = lambda *args, **kwargs: [grupo]
    token = use_ultra_provider(grupo)
    try:
        with pytest.raises(FalhaDaCadeia) as erro:
            await cadeia.complete([{"role": "user", "content": "oi"}])
    finally:
        clear_ultra_provider(token)
    assert erro.value.tipos == ["credit"]
    assert "Claude Code" in erro.value.falhas["claude_code"]["motivo"]
    assert "ultra_max" not in erro.value.falhas
    assert cadeia.last_provider == "claude_code" and cadeia.last_model == "claude_code:haiku"
    item = atividade.resumo()[0]
    assert item["provedor"] == "claude_code" and item["modelo"] == "claude_code:haiku"
    assert item["motivo"] == "credit" and item["status"] == "falha"
    assert Atividade(persistir=True).resumo()[0]["provedor"] == "claude_code"


@pytest.mark.parametrize("runtime", [False, True])
async def test_falha_seguida_de_sucesso_nao_atribui_resposta_a_conta_errada(runtime):
    from robinbandit.routing.sentury import ChainProvider as CadeiaDoRuntime

    class Boa:
        name = "boa"
        last_model = "boa:modelo"
        async def complete(self, *args, **kwargs):
            return "voltou"

    ruim, boa = ContaEsgotada(), Boa()
    atividade = Atividade()
    providers = [ruim, boa]
    cadeia = CadeiaDoRuntime(providers, activity=atividade) if runtime else ChainProvider(providers, ProviderRouter(), activity=atividade)
    cadeia.router.order = lambda *args, **kwargs: providers
    assert await cadeia.complete([{"role": "user", "content": "oi"}]) == "voltou"
    assert cadeia.last_provider == "boa" and cadeia.last_model == "boa:modelo"
    assert {i["provedor"] for i in atividade.resumo()} == {"boa", "claude_code"}


def test_erro_desconhecido_nao_revela_saida_do_cli():
    falha = classificar_cli(RuntimeError("falha token-privado-exemplo"), "claude", "conta")
    assert classificar(falha) == "other"
    assert "token-privado-exemplo" not in str(falha)


async def test_grupo_conserva_as_duas_contas_que_falharam():
    a, b = ContaEsgotada(), ContaEsgotada()
    b.name = "claude-trabalho"
    b.last_attempted_model = "claude-trabalho:haiku"
    grupo = ReinforcedProvider([a, b], name="ultra_max")
    with pytest.raises(FalhaDaCadeia) as erro:
        await grupo.complete([{"role": "user", "content": "oi"}])
    assert set(erro.value.falhas) == {"claude_code", "claude-trabalho"}
    assert erro.value.tipos == ["credit", "credit"]
    assert erro.value.falhas["claude-trabalho"]["modelo"] == "claude-trabalho:haiku"
