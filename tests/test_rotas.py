"""A cadeia auxiliar não herda os modelos nem a seleção dedicada do turno."""
import pytest

from robinbandit import RobinConfig, build_route


def _config():
    return RobinConfig.from_mapping({"providers": {"rapido": {"models": ["grande"]},
        "reserva": {"models": ["medio"]}, "principal": {"models": ["principal"]}},
        "routes": {"auxiliar": {"chain_order": ["rapido", "reserva"],
                                "models": {"rapido": ["pequeno"], "reserva": ["menor"]}}}})


async def test_rota_monta_so_seus_modelos_e_faz_failover(monkeypatch):
    pedidos = []

    class Provedor:
        def __init__(self, nome, models):
            self.name = nome
            self.models = models
            self.last_model = nome + ":" + models[0]

        async def complete(self, messages, temperature=0.2, preferred_model=None, **kwargs):
            pedidos.append((self.name, preferred_model))
            if self.name == "rapido":
                raise RuntimeError("modelo não encontrado, 404")
            return "resumo"

    def montar(config, chave, settings=None, models=None, **kwargs):
        return Provedor(chave, models)

    monkeypatch.setattr("robinbandit.providers.build_provider", montar)
    rota = build_route(_config(), "auxiliar")
    assert await rota.complete([{"role": "user", "content": "resuma"}], complexity="SIMPLE") == "resumo"
    assert pedidos == [("rapido", "pequeno"), ("reserva", "menor")]
    assert rota.last_provider == "reserva"
    assert rota.last_model == "reserva:menor"


def test_sem_provedor_nao_cai_na_cadeia_principal(monkeypatch):
    monkeypatch.setattr("robinbandit.providers.build_provider", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="nenhum provedor disponível"):
        build_route(_config(), "auxiliar")
    with pytest.raises(KeyError, match="não declarada"):
        build_route(_config(), "outra")


@pytest.mark.parametrize("spec", [{"chain_order": ["ausente"]},
    {"chain_order": ["a", "a"]}, {"chain_order": ["a"], "models": {"a": "texto"}},
    {"chain_order": ["a"], "models": {"fora": ["x"]}}])
def test_config_recusa_rota_invalida(spec):
    with pytest.raises(ValueError):
        RobinConfig.from_mapping({"providers": {"a": {}}, "routes": {"auxiliar": spec}})
