"""Claude Code como provedor, pela assinatura.

O RobinBandit nao le, copia ou renova credencial: `~/.claude/.credentials.json`
e do CLI. Aqui ele e so mais um provedor de modelo — o loop de ferramentas
continua sendo do agente hospedeiro.
"""
import json
from pathlib import Path

import pytest

from robinbandit import RobinConfig
from robinbandit.providers import claude_code_provider
from robinbandit.providers.claude_code_provider import (
    ClaudeCodeError,
    ClaudeCodeProvider,
    _texto_das_mensagens,
)
from robinbandit.providers import build_provider

ROOT = Path(__file__).resolve().parents[1]


def test_provedor_esta_no_catalogo_com_auth_de_cli():
    cfg = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    spec = cfg.providers.get("claude_code")
    assert spec, "claude_code nao declarado"
    assert spec["adapter"] == "claude_code"
    assert spec["auth_type"] == "claude_cli"
    # Sem chave: quem autentica e o CLI. Exigir uma faria o provedor aparecer
    # como "falta configurar" para quem ja esta logado.
    assert spec.get("chave_opcional") is True
    assert not spec.get("api_key_env")


def test_historico_vira_prompt_com_os_papeis_marcados():
    sistema, prompt = _texto_das_mensagens([
        {"role": "system", "content": "Seja breve."},
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "ola"},
        {"role": "user", "content": "tudo bem?"},
    ])
    assert sistema == "Seja breve."
    assert prompt == "Usuário: oi\n\nAssistente: ola\n\nUsuário: tudo bem?"


def test_mensagem_vazia_nao_vira_linha_solta():
    _sistema, prompt = _texto_das_mensagens([
        {"role": "user", "content": "  "},
        {"role": "user", "content": "vale"},
    ])
    assert prompt == "Usuário: vale"


@pytest.mark.asyncio
async def test_sem_nada_para_perguntar_falha_cedo():
    provider = ClaudeCodeProvider()
    with pytest.raises(ClaudeCodeError):
        await provider.generate([{"role": "system", "content": "so contexto"}])


def test_ferramentas_do_cli_ficam_desligadas():
    """Dois loops de ferramenta no mesmo turno — o do CLI e o do agente —
    disputariam a mesma execucao.

    `--allowed-tools ""` NAO desliga: so nega. Medido no benchmark, o modelo
    tentava ler a pasta com o Bash do CLI, era negado e tentava de novo ate a
    chamada estourar 110s. Com `--tools ""` a mesma tarefa volta em 1 turno."""
    provider = ClaudeCodeProvider()
    try:
        comando = provider._comando("", "")
    except ClaudeCodeError:
        pytest.skip("Claude Code CLI nao instalado nesta maquina")
    assert comando[comando.index("--tools") + 1] == ""
    assert "--allowed-tools" not in comando
    assert comando[comando.index("--permission-mode") + 1] == "dontAsk"
    assert "--output-format" in comando and "stream-json" in comando


def test_fabrica_devolve_none_sem_cli(monkeypatch):
    """Sem o CLI ele fica fora da cadeia, em vez de falhar no meio do turno."""
    import robinbandit.providers.claude_code_provider as ccp

    monkeypatch.setattr(ccp, "resolve_claude_binary", lambda binary="claude": None)
    ccp._STATUS_CACHE.clear()
    cfg = RobinConfig.from_yaml(ROOT / "config" / "sentury.yaml")
    assert build_provider(cfg, "claude_code", None) is None


def test_erro_do_cli_nao_vira_resposta(monkeypatch):
    """Uma falha tem de parecer falha: devolver o texto do erro como resposta
    e o jeito mais silencioso de entregar lixo."""
    import subprocess

    import robinbandit.providers.claude_code_provider as ccp

    class Saida:
        stdout = json.dumps(
            {"type": "result", "is_error": True, "result": "limite atingido"})
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Saida())
    monkeypatch.setattr(ccp, "resolve_claude_binary", lambda binary="claude": "claude")

    import asyncio

    provider = ClaudeCodeProvider()
    with pytest.raises(ClaudeCodeError, match="limite atingido"):
        asyncio.run(provider.generate([{"role": "user", "content": "oi"}]))


def test_cli_roda_fora_do_projeto_e_sem_memoria_automatica(monkeypatch, tmp_path):
    """O turno do modelo não herda a memória nem as instruções da pasta de quem chamou."""
    import os
    import subprocess

    import robinbandit.providers.claude_code_provider as ccp

    vistos = {}

    class Saida:
        stdout = json.dumps({"type": "result", "subtype": "success", "result": "ok"})
        stderr = ""

    def rodar(*a, **k):
        vistos.update(k)
        return Saida()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", rodar)
    monkeypatch.setattr(ccp, "resolve_claude_binary", lambda binary="claude": "claude")

    import asyncio

    asyncio.run(ClaudeCodeProvider().generate([{"role": "user", "content": "oi"}]))
    assert os.path.abspath(vistos["cwd"]) != os.path.abspath(str(tmp_path))
    assert vistos["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


class TestLeituraDoStream:
    """O `--output-format json` nao dava sinal de vida nenhum.

    O stream da: o texto, o uso e — quando existe — o pensamento. Medido no CLI
    2.1.278, o texto do pensamento vem vazio; o contador nao.
    """

    def _linhas(self, *eventos):
        return "\n".join(json.dumps(e) for e in eventos)

    def test_pega_o_resultado_e_o_uso(self):
        saida = self._linhas(
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "51"}]}},
            {"type": "result", "subtype": "success", "result": "51",
             "usage": {"input_tokens": 10, "output_tokens": 2,
                       "cache_read_input_tokens": 7},
             "total_cost_usd": 0.015},
        )
        lido = claude_code_provider._ler_stream(saida)
        assert lido["texto"] == "51"
        assert lido["completou"] is True
        assert lido["uso"]["input_tokens"] == 10
        assert lido["custo"] == 0.015

    def test_aviso_antes_do_json_nao_derruba(self):
        saida = "Warning: workspace nao confiado\n" + self._linhas(
            {"type": "result", "result": "ok"})
        assert claude_code_provider._ler_stream(saida)["texto"] == "ok"

    def test_erro_vira_erro(self):
        saida = self._linhas({"type": "result", "is_error": True, "result": "limite"})
        assert claude_code_provider._ler_stream(saida)["erro"] == "limite"

    def test_stream_cortado_no_meio_nao_vira_resposta_vazia(self):
        """Sem `result` e sem texto, o CLI morreu — e morte nao e resposta."""
        saida = self._linhas({"type": "system", "subtype": "init"})
        lido = claude_code_provider._ler_stream(saida)
        assert lido["completou"] is False and lido["texto"] == ""

    def test_conta_o_pensamento_quando_o_texto_vem_vazio(self):
        """O caso real: bloco `thinking` so com assinatura."""
        saida = self._linhas(
            {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 132},
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "", "signature": "EooE"},
                {"type": "text", "text": "131"}]}},
            {"type": "result", "result": "131"},
        )
        lido = claude_code_provider._ler_stream(saida)
        assert lido["pensamento"] == ""
        resumo = claude_code_provider._resumo_do_pensamento(lido)
        assert "132 tokens" in resumo

    def test_texto_do_pensamento_ganha_do_contador(self):
        lido = {"pensamento": "vou somar os dias", "tokens_de_pensamento": 132}
        assert claude_code_provider._resumo_do_pensamento(lido) == "vou somar os dias"

    def test_sem_pensamento_nenhum_nao_inventa_resumo(self):
        lido = {"pensamento": "", "tokens_de_pensamento": 0}
        assert claude_code_provider._resumo_do_pensamento(lido) is None


def test_o_comando_pede_stream():
    """Se alguem voltar para `json`, o resumo de raciocinio morre em silencio."""
    p = claude_code_provider.ClaudeCodeProvider(name="claude_code")
    comando = p._comando("", "claude-haiku-4-5")
    assert "stream-json" in comando and "--verbose" in comando


class TestFerramentasNoCLI:
    """O CLI nao aceita definicao de ferramenta, mas o agente manda `tools=`.

    O provedor engolia isso num `**_ignorado`: `last_tool_calls` ficava None e o
    caminho nativo — que funciona nos provedores de API — nunca disparava aqui.
    """

    def test_traduz_o_plano_em_chamadas(self):
        texto = ('Vou listar a pasta para ver o que tem nela.\n\n```json\n'
                 '{"plan":[{"tool":"listar_arquivos","arguments":{"padrao":"**/*"}}]}\n```')
        assert claude_code_provider._chamadas_do_texto(texto) == [
            {"function": {"name": "listar_arquivos", "arguments": {"padrao": "**/*"}}}]

    def test_aceita_o_nome_que_o_resto_do_mundo_usa(self):
        texto = '{"tool_calls":[{"name":"ler_arquivo","arguments":{"caminho":"R.md"}}]}'
        assert claude_code_provider._chamadas_do_texto(texto)[0]["function"]["name"] == "ler_arquivo"

    def test_chave_dentro_de_string_nao_corta_o_objeto(self):
        """Contagem de chaves ingenua quebra em `a{b}.md` e perde a chamada."""
        texto = '{"plan":[{"tool":"ler_arquivo","arguments":{"caminho":"a{b}.md"}}]}'
        assert claude_code_provider._chamadas_do_texto(texto)[0]["function"]["arguments"] == {
            "caminho": "a{b}.md"}

    def test_pula_o_json_que_nao_e_plano(self):
        texto = '{"outra":"coisa"} e depois {"plan":[{"tool":"x","arguments":{}}]}'
        assert claude_code_provider._chamadas_do_texto(texto)[0]["function"]["name"] == "x"

    def test_plano_vazio_nao_vira_chamada(self):
        """Plano vazio é resposta legítima: quem trata é o caminho de texto."""
        assert claude_code_provider._chamadas_do_texto('{"plan":[]}') is None

    def test_sem_json_nao_inventa(self):
        assert claude_code_provider._chamadas_do_texto("só texto") is None

    def test_a_instrucao_leva_o_esquema_de_cada_ferramenta(self):
        """O CLI nao recebe `tools=`: sem o esquema no texto, o modelo nao sabe
        os parametros (a `acao` do `computador`, por exemplo) e so anuncia."""
        esquema = {"type": "object", "properties": {"acao": {"type": "string", "enum": ["ver"]}}}
        texto = claude_code_provider._COMO_USAR_FERRAMENTA.format(
            ferramentas=claude_code_provider._ferramentas_para_o_texto(
                [{"function": {"name": "computador", "description": "usa a tela", "parameters": esquema}}]))
        assert '"name": "computador"' in texto and '"enum": ["ver"]' in texto
        assert '{"tool_calls": [{"name": "<ferramenta>", "arguments": {...}}]}' in texto
        chamada = claude_code_provider._chamadas_do_texto(
            'Vou ler a janela.\n```json\n'
            '{"tool_calls": [{"name": "computador", "arguments": {"acao": "elementos"}}]}\n```')
        assert chamada[0]["function"] == {"name": "computador", "arguments": {"acao": "elementos"}}

    def test_tools_desconhecido_nao_derruba(self):
        assert claude_code_provider._ferramentas_para_o_texto(None) == "(nenhuma)"
        assert claude_code_provider._ferramentas_para_o_texto([{"sem": "funcao"}]) == "(nenhuma)"


class TestImagemPeloCLI:
    """O print entra como bloco base64 pelo `--input-format stream-json`."""

    URL = "data:image/png;base64,iVBORw0KGgo="

    def test_imagem_do_conteudo_multimodal_sai_do_texto(self):
        imagens = []
        _sistema, prompt = claude_code_provider._texto_das_mensagens(
            [{"role": "user", "content": [{"type": "text", "text": "o que há na tela?"},
                                          {"type": "image_url", "image_url": {"url": self.URL}}]}], imagens)
        assert prompt == "Usuário: o que há na tela?" and imagens == [self.URL]

    def test_entrada_em_stream_json_com_o_bloco_de_imagem(self):
        import json

        linha = json.loads(claude_code_provider._entrada_com_imagens("Usuário: oi", [self.URL]))
        assert linha["type"] == "user"
        texto, imagem = linha["message"]["content"]
        assert texto == {"type": "text", "text": "Usuário: oi"}
        assert imagem["source"] == {"type": "base64", "data": "iVBORw0KGgo=", "media_type": "image/png"}

    def test_o_comando_so_muda_a_entrada_quando_ha_imagem(self):
        p = claude_code_provider.ClaudeCodeProvider(name="claude_code")
        assert "--input-format" not in p._comando("", "claude-haiku-4-5")
        comando = p._comando("", "claude-haiku-4-5", com_imagem=True)
        assert comando[comando.index("--input-format") + 1] == "stream-json"


class TestEsforcoNoCLI:
    """O esforço da barra chega ao CLI como `--effort`."""

    @pytest.mark.parametrize("nivel,cli", [("none", "low"), ("low", "low"), ("medium", "medium"),
                                           ("xhigh", "xhigh"), (None, None), ("qualquer", None)])
    def test_traduz_o_nivel(self, nivel, cli):
        assert claude_code_provider.esforco_do_cli(nivel) == cli

    def test_o_comando_leva_o_esforco(self):
        p = claude_code_provider.ClaudeCodeProvider(name="claude_code")
        comando = p._comando("", "claude-haiku-4-5", esforco="none")
        assert comando[comando.index("--effort") + 1] == "low"
        assert "--effort" not in p._comando("", "claude-haiku-4-5")


class TestChamadaSolta:
    """A chamada escrita solta, sem o envelope `tool_calls`, também é chamada,
    desde que o nome seja de uma ferramenta da mesa."""

    NOMES = {"browser", "computador"}

    def test_objeto_solto(self):
        texto = 'Vou buscar.\n```json\n{"name": "browser", "arguments": {"acao": "snapshot"}}\n```'
        (chamada,) = claude_code_provider._chamadas_do_texto(texto, self.NOMES)
        assert chamada["function"] == {"name": "browser", "arguments": {"acao": "snapshot"}}

    def test_lista_e_formato_openai_com_argumentos_em_texto(self):
        texto = ('[{"type": "function", "function": {"name": "browser", "arguments": "{\\"acao\\": \\"navegar\\"}"}},'
                 ' {"tool": "computador", "args": {"acao": "ver"}}]')
        chamadas = claude_code_provider._chamadas_do_texto(texto, self.NOMES)
        assert [c["function"]["name"] for c in chamadas] == ["browser", "computador"]
        assert chamadas[0]["function"]["arguments"] == {"acao": "navegar"}

    def test_json_da_resposta_com_nome_qualquer_nao_vira_chamada(self):
        texto = 'O cadastro ficou assim: {"name": "Ana", "arguments": {"idade": 30}}'
        assert claude_code_provider._chamadas_do_texto(texto, self.NOMES) is None


def test_json_sem_a_ultima_chave_ainda_vira_chamada():
    """O Haiku errou a conta das chaves num roteiro aninhado (faltou a última) e
    o turno terminou em texto. O bloco json é fechado antes de desistir."""
    texto = ('Vou abrir a Galeria.\n```json\n{"tool_calls": [{"name": "browser", "arguments": {"acao": "roteiro", '
             '"argumentos": {"passos": [{"acao": "navegar", "argumentos": {"url": "http://127.0.0.1:8765/"}}, '
             '{"acao": "pensar"}]}}}]\n```\nDepois leio o resultado.')
    (chamada,) = claude_code_provider._chamadas_do_texto(texto, {"browser"})
    assert chamada["function"]["arguments"]["argumentos"]["passos"][1] == {"acao": "pensar"}


def test_chave_dentro_de_string_nao_conta_no_fechamento():
    assert claude_code_provider._fechar_json('{"a": "x{y"') == '{"a": "x{y"}'
    assert claude_code_provider._fechar_json(r'{"a": "diz \"{\" e segue"') == r'{"a": "diz \"{\" e segue"}'


def test_a_chamada_passada_vai_no_formato_que_a_instrucao_pede():
    """Em prosa ('(chamei browser com ...)'), o modelo imitou a prosa, nada rodou e
    ele respondeu 'salvei na sua conta'. O histórico mostra o mesmo bloco pedido."""
    mensagens = [{"role": "user", "content": "salve o pin"},
                 {"role": "assistant", "content": "Vou abrir.", "tool_calls": [
                     {"id": "1", "type": "function",
                      "function": {"name": "browser", "arguments": '{"acao": "navegar"}'}}]},
                 {"role": "tool", "content": "ok", "tool_call_id": "1"}]
    _sistema, prompt = claude_code_provider._texto_das_mensagens(mensagens)
    assert "(chamei" not in prompt
    (chamada,) = claude_code_provider._chamadas_do_texto(prompt, {"browser"})
    assert chamada["function"] == {"name": "browser", "arguments": {"acao": "navegar"}}
