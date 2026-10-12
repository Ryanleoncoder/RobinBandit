"""A saída do CLI é classificada sem devolver seu conteúdo à interface."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _contrato():
    return json.loads((Path(__file__).parents[1] / "assets/providers/erros-cli.json").read_text(encoding="utf-8"))


class FalhaDoCLI(RuntimeError):
    def __init__(self, cli, conta, tipo, motivo, *, conta_inteira=False):
        self.tipo = tipo
        self.conta_inteira = conta_inteira
        rotulo = _contrato()["rotulos"][cli]
        self.motivo_publico = f"A conta {rotulo} ({conta}) {motivo}"
        if tipo == "auth":
            self.motivo_publico += "; no terminal, use " + _contrato()["logins"][cli]
        super().__init__(self.motivo_publico)


def classificar_cli(erro, cli, conta):
    if isinstance(erro, FalhaDoCLI) or getattr(erro, "motivo_publico", None):
        return erro
    texto = (type(erro).__name__ + " " + str(erro)).lower()
    for regra in _contrato()["regras"]:
        if any(marca in texto for marca in regra["marcas"]):
            return FalhaDoCLI(cli, conta, regra["tipo"], regra["motivo"], conta_inteira=regra["conta_inteira"])
    from ..routing.erros import classificar
    return FalhaDoCLI(cli, conta, classificar(erro), "teve uma falha ao responder; tente novamente ou troque o modelo do modo")
