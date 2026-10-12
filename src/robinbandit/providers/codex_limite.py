"""O limite da assinatura conserva a previsão informada, sem links comerciais."""
import re


class LimiteDoCodex(RuntimeError):
    tipo = "credit"

    def __init__(self, mensagem):
        texto = re.sub(r"https?://\S+", "", str(mensagem or ""))
        volta = re.search(r"try again (?:at|after)\s+([^\n.!?]+)", texto, re.I)
        self.retoma_em = volta.group(1).strip().rstrip(",;:")[:100] if volta else ""
        self.motivo_publico = "A assinatura do Codex atingiu o limite de uso"
        if self.retoma_em:
            self.motivo_publico += f"; retorno informado pelo Codex: {self.retoma_em}"
        else:
            self.motivo_publico += "; o horário de retorno não foi informado"
        super().__init__(self.motivo_publico + ".")


def erro_do_turno(erro):
    if isinstance(erro, dict):
        codigo = erro.get("codexErrorInfo")
        if isinstance(codigo, dict):
            codigo = next(iter(codigo), "")
        if str(codigo or "").lower() == "usagelimitexceeded":
            return LimiteDoCodex(erro.get("message"))
    return None
