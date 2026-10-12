"""Login fica no cliente oficial, sem capturar sua credencial."""
import subprocess
import threading
import time


def consultar(tipo, binario):
    if tipo == "claude_cli":
        from ..providers import claude_code_provider as modulo
        resolver, status = modulo.resolve_claude_binary, modulo.claude_code_auth_status
    elif tipo == "codex_cli":
        from ..providers import codex_provider as modulo
        resolver, status = modulo.resolve_codex_binary, modulo.codex_auth_status
    else:
        raise ValueError("Este provedor não usa login por CLI.")
    executavel = resolver(binario)
    if executavel:
        modulo._STATUS_CACHE.pop(executavel, None)
    conectado = bool(executavel and status(binario).configured)
    return {
        "estado": "conectado" if conectado else "desconectado" if executavel else "nao_instalado",
        "instalado": bool(executavel), "configurada": conectado,
    }


class LoginCLI:
    def __init__(self, tipo, binario):
        self.tipo, self.binario = tipo, binario
        self.estado = "aguardando"
        self.processo = None
        self.cancelado = threading.Event()

    def iniciar(self):
        status = consultar(self.tipo, self.binario)
        if not status["instalado"]:
            raise ValueError("Instale o CLI oficial antes de conectar.")
        if status["configurada"]:
            self.estado = "conectado"
            return
        from ..providers.claude_code_provider import resolve_claude_binary
        from ..providers.codex_provider import resolve_codex_binary
        if self.tipo == "claude_cli":
            comando = [resolve_claude_binary(self.binario), "auth", "login"]
        else:
            comando = [resolve_codex_binary(self.binario), "login"]
        self.processo = subprocess.Popen(
            comando, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.thread = threading.Thread(target=self._acompanhar, daemon=True)
        self.thread.start()

    def _acompanhar(self):
        prazo = time.monotonic() + 600
        while self.processo.poll() is None:
            if self.cancelado.wait(0.2) or time.monotonic() >= prazo:
                self.processo.terminate()
                try:
                    self.processo.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.processo.kill()
                    self.processo.wait(timeout=3)
                self.estado = "cancelado" if self.cancelado.is_set() else "expirado"
                return
        self.estado = "conectado" if consultar(self.tipo, self.binario)["configurada"] else "falhou"

    def cancelar(self):
        self.cancelado.set()
        if getattr(self, "thread", None) and self.thread is not threading.current_thread():
            self.thread.join(timeout=4)

    def publico(self):
        return {"estado": self.estado, "configurada": self.estado == "conectado"}
