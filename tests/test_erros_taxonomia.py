"""Taxonomia de erro: de quem e a culpa decide o que a cadeia faz.

Tres respostas diferentes para tres tipos de falha:

- do PEDIDO (413, contexto estourado, politica de conteudo): outro provedor
  pode aceitar, e este continua otimo para o proximo pedido normal. Sem saude,
  sem cooldown.
- PASSAGEIRA (429, 5xx): espera e tenta de novo no mesmo provedor.
- do PROVEDOR ou da configuracao (401, 404, credito): cooldown e saude.
"""
import pytest

from robinbandit import ChainProvider, FalhaDaCadeia, ProviderRouter, classify_error
from robinbandit.routing import erros

# Mensagens reais, como os provedores escrevem.
GROQ_413 = ("Error code: 413 - {'error': {'message': 'Request too large for model "
            "`llama-3.3-70b-versatile` in organization `org_x` service tier `on_demand` on tokens "
            "per minute (TPM): Limit 12000, Requested 15876, please reduce your message size and "
            "try again.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
OPENAI_CONTEXTO = ("Error code: 400 - This model's maximum context length is 128000 tokens. "
                   "However, your messages resulted in 130413 tokens. code: context_length_exceeded")
ANTHROPIC_CONTEXTO = "prompt is too long: 214513 tokens > 200000 maximum"
GEMINI_CONTEXTO = "400 The input token count (1048577) exceeds the maximum number of tokens allowed (1048576)."
OPENAI_POLITICA = ("Error code: 400 - The response was filtered due to the prompt triggering Azure "
                   "OpenAI's content management policy. code: content_filter")
MODELO_SUMIU = "Error code: 404 - {'error': {'message': 'The model `llama3-70b-8192` does not exist'}}"
SERVICO_FORA = "Server error '503 Service Unavailable' for url 'https://api.x.com/v1/chat'"
BEDROCK_COTA = "ThrottlingException: Too many tokens, please wait before trying again."


class TestClassificar:
    @pytest.mark.parametrize("mensagem,tipo", [
        (GROQ_413, "request_too_large"),
        (OPENAI_CONTEXTO, "context_length"),
        (ANTHROPIC_CONTEXTO, "context_length"),
        (GEMINI_CONTEXTO, "context_length"),
        (OPENAI_POLITICA, "content_policy"),
        (MODELO_SUMIU, "not_found"),
        (SERVICO_FORA, "transient"),
        ("502 Bad Gateway", "transient"),
        ("504 Gateway Timeout", "transient"),
        (BEDROCK_COTA, "rate_limit"),
    ])
    def test_cada_mensagem_real_no_seu_tipo(self, mensagem, tipo):
        assert classify_error(Exception(mensagem)) == tipo

    def test_o_413_da_groq_nao_e_cota(self):
        """Ele traz `rate_limit_exceeded` no corpo. Lido como cota, a cadeia
        reenviava o MESMO pedido grande demais e castigava o provedor."""
        assert classify_error(Exception(GROQ_413)) != "rate_limit"

    def test_codigo_http_casa_como_numero_inteiro(self):
        """Como trecho, "413" casava em "10413 tokens" e "500" em "limit 1500"."""
        assert classify_error(Exception("limit 1500 requests per day")) == "other"
        assert classify_error(Exception("used 10413 of your budget")) == "other"
        assert classify_error(Exception("Error code: 413")) == "request_too_large"

    def test_o_padrao_do_yaml_e_o_do_codigo_concordam(self):
        """O YAML SUBSTITUI a tabela do codigo quando existe. Regra que so mora
        num dos dois some em producao sem ninguem notar."""
        from pathlib import Path

        import yaml

        from robinbandit import config as cfg

        caminho = Path(cfg.__file__).resolve().parent / "padrao.yaml"
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
        tabela = bruto["routing"]["erros"]
        tipos_yaml = [r["tipo"] for r in tabela["regras"]]
        tipos_codigo = [tipo for tipo, _ in erros.REGRAS_PADRAO]
        assert tipos_yaml == tipos_codigo
        mensagens = (GROQ_413, OPENAI_CONTEXTO, ANTHROPIC_CONTEXTO, GEMINI_CONTEXTO,
                     OPENAI_POLITICA, MODELO_SUMIU, SERVICO_FORA, BEDROCK_COTA)
        pelo_codigo = [erros.classificar(Exception(m)) for m in mensagens]
        try:
            erros.configurar(tabela)
            assert [erros.classificar(Exception(m)) for m in mensagens] == pelo_codigo
            assert erros.cooldown_de("not_found") == erros.COOLDOWN_PADRAO["not_found"]
            assert erros.cooldown_de("transient") == erros.COOLDOWN_PADRAO["transient"]
        finally:
            erros.configurar(None)


class _Prov:
    def __init__(self, roteiro, name):
        self.roteiro = list(roteiro)
        self.calls = 0
        self.name = name
        self.last_model = name

    async def complete(self, messages, temperature=0.2, context=None):
        self.calls += 1
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def sem_espera(monkeypatch):
    import robinbandit.routing.chain as chain

    async def _no_sleep(s):
        pass

    monkeypatch.setattr(chain.asyncio, "sleep", _no_sleep)


def _oi():
    return [{"role": "user", "content": "oi"}]


class TestErroDaRequisicao:
    @pytest.mark.parametrize("mensagem", [GROQ_413, OPENAI_CONTEXTO, OPENAI_POLITICA])
    async def test_passa_adiante_sem_castigar_o_provedor(self, sem_espera, mensagem):
        pequeno = _Prov([Exception(mensagem)], name="pequeno")
        grande = _Prov(["coube aqui"], name="grande")
        router = ProviderRouter()
        cadeia = ChainProvider([pequeno, grande], router)

        # A ordem da cadeia e do roteador; forca o pequeno primeiro.
        router.order = lambda candidatos, *a, **k: list(candidatos)
        assert await cadeia.complete(_oi()) == "coube aqui"

        assert pequeno.calls == 1, "reenviar o mesmo pedido nao muda o tamanho dele"
        assert router.cooldown_remaining("pequeno") == 0
        estado = router.snapshot().get("pequeno") or {}
        assert not estado.get("err"), "a falha era do pedido, nao do provedor"
        assert not estado.get("health_samples")

    async def test_todos_recusando_o_pedido_diz_isso(self, sem_espera):
        """Contexto estourado em todos pede compactar e tentar de novo — nao e
        "o servico caiu". Quem chama so sabe a diferenca se o erro disser."""
        a = _Prov([Exception(OPENAI_CONTEXTO)], name="a")
        b = _Prov([Exception(ANTHROPIC_CONTEXTO)], name="b")
        cadeia = ChainProvider([a, b], ProviderRouter())

        with pytest.raises(FalhaDaCadeia) as falha:
            await cadeia.complete(_oi())
        assert falha.value.tipos == ["context_length", "context_length"]
        assert falha.value.da_requisicao is True
        assert isinstance(falha.value, RuntimeError), "quem ja capturava RuntimeError continua pegando"


class TestPassageiro:
    async def test_503_espera_e_tenta_de_novo_no_mesmo(self, sem_espera):
        instavel = _Prov([Exception(SERVICO_FORA), "voltou"], name="instavel")
        cadeia = ChainProvider([instavel], ProviderRouter())

        assert await cadeia.complete(_oi()) == "voltou"
        assert instavel.calls == 2

    async def test_503_que_persiste_vai_para_o_proximo_com_cooldown_curto(self, sem_espera):
        caido = _Prov([Exception(SERVICO_FORA), Exception(SERVICO_FORA)], name="caido")
        bom = _Prov(["ok"], name="bom")
        router = ProviderRouter()
        router.order = lambda candidatos, *a, **k: list(candidatos)

        assert await ChainProvider([caido, bom], router).complete(_oi()) == "ok"
        assert 0 < router.cooldown_remaining("caido") <= 20


class TestDoProvedor:
    async def test_modelo_que_sumiu_tira_o_provedor_por_um_tempo(self, sem_espera):
        velho = _Prov([Exception(MODELO_SUMIU)], name="velho")
        bom = _Prov(["ok"], name="bom")
        router = ProviderRouter()
        router.order = lambda candidatos, *a, **k: list(candidatos)

        assert await ChainProvider([velho, bom], router).complete(_oi()) == "ok"
        assert velho.calls == 1
        assert router.cooldown_remaining("velho") > 60
        assert (router.snapshot()["velho"]["err"]) == 1
