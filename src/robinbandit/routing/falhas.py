"""Motivos públicos da chamada ficam separados do erro técnico e das credenciais."""
import contextvars


class MotivosDaChamada:
    @property
    def ultimas_falhas(self):
        campo = getattr(self, "_motivos", None)
        return {nome: dict(valor) for nome, valor in (campo.get() or {}).items()} if campo else {}

    def _abrir_motivos(self):
        if not hasattr(self, "_motivos"):
            self._motivos = contextvars.ContextVar(f"robin_motivos_{id(self)}", default=None)
        self._motivos.set({})

    def _registrar_falha(self, nome, tipo, erro):
        detalhe = {"tipo": tipo}
        vistos = set()
        while erro is not None and id(erro) not in vistos:
            vistos.add(id(erro))
            if getattr(erro, "motivo_publico", None):
                detalhe.update(motivo=erro.motivo_publico, retoma_em=getattr(erro, "retoma_em", ""))
                break
            erro = erro.__cause__ or erro.__context__
        atual = self.ultimas_falhas
        atual[nome] = detalhe
        self._motivos.set(atual)
