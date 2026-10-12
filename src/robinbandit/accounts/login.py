"""Tentativas de login têm prazo e não expõem tokens ao navegador."""
import importlib.util
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from . import openai_oauth
from .login_cli import LoginCLI, consultar


class LoginChatGPT:
    def __init__(self, conta=""):
        if importlib.util.find_spec("cryptography") is None:
            raise ValueError("Instale a opção de autenticação do RobinBandit antes de conectar.")
        self.estado, self.detalhe = "aguardando", ""
        self.cancelado = threading.Event()
        tentativa = self

        class Callback(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *args):
                pass

            def do_GET(self):
                esperado = "127.0.0.1:" + str(self.server.server_port)
                url = urlsplit(self.path)
                if len(self.path) > 8192:
                    self.send_error(400, "Resposta de login invalida")
                    return
                params = parse_qs(url.query, keep_blank_values=True)
                state = params.get("state", [])
                if (self.headers.get("Host") != esperado or url.path != "/auth/callback"
                        or len(state) != 1 or not secrets.compare_digest(state[0], tentativa.auth.state)
                        or any(len(valores) != 1 for valores in params.values())
                        or tentativa.estado != "aguardando"):
                    self.send_error(400, "Resposta de login invalida")
                    return
                tentativa.estado = "validando"
                try:
                    tentativa.auth.concluir({k: v[0] for k, v in params.items()}, tentativa.cancelado.is_set)
                    tentativa.estado = "conectado"
                    texto = "Conta conectada. Pode voltar ao aplicativo."
                except openai_oauth.LoginInvalido as exc:
                    tentativa.estado, tentativa.detalhe = "falhou", str(exc)
                    texto = "O login nao foi concluido. Volte ao aplicativo para conferir."
                except Exception:
                    tentativa.estado, tentativa.detalhe = "falhou", "Não foi possível salvar a autorização."
                    texto = "O login nao foi concluido. Volte ao aplicativo para conferir."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                try:
                    self.wfile.write(texto.encode("utf-8"))
                except OSError:
                    pass

        self.servidor = HTTPServer(("127.0.0.1", 0), Callback)
        self.servidor.timeout = 0.2
        try:
            uri = "http://127.0.0.1:" + str(self.servidor.server_port) + "/auth/callback"
            self.auth = openai_oauth.Autorizacao(uri, conta)
        except Exception:
            self.servidor.server_close()
            raise

    def iniciar(self):
        threading.Thread(target=self._acompanhar, daemon=True).start()
        if not webbrowser.open(self.auth.url(), new=2):
            self.cancelar()
            raise ValueError("Não foi possível abrir o navegador padrão para entrar.")

    def _acompanhar(self):
        prazo = time.monotonic() + 600
        try:
            while self.estado == "aguardando" and time.monotonic() < prazo and not self.cancelado.is_set():
                self.servidor.handle_request()
            if self.estado == "aguardando":
                self.estado = "cancelado" if self.cancelado.is_set() else "expirado"
        finally:
            self.servidor.server_close()

    def cancelar(self):
        self.cancelado.set()

    def publico(self):
        return {"estado": self.estado, "detalhe": self.detalhe, "configurada": self.estado == "conectado"}


class Logins:
    def __init__(self, config, alterado=None):
        self.config, self.alterado = config, alterado
        self.tentativas = {}
        self.lock = threading.RLock()

    def spec(self, provedor):
        spec = (self.config.providers if self.config else {}).get(provedor) or {}
        if spec.get("enabled") is False or spec.get("auth_type") not in {"codex_cli", "claude_cli", "chatgpt_oauth"}:
            raise ValueError("Este provedor não oferece login guiado.")
        return spec

    def status(self, provedor):
        spec = self.spec(provedor)
        with self.lock:
            self._limpar()
            for tid, (p, t, _, _) in self.tentativas.items():
                if p == provedor and t.publico()["configurada"]:
                    self.consultar(tid)
        if spec["auth_type"] == "chatgpt_oauth":
            resultado = {**openai_oauth.situacao(), "disponivel": importlib.util.find_spec("cryptography") is not None}
        else:
            from ..providers import _source_value
            binary = _source_value(None, spec.get("binary_env", "")) or spec.get("binary", "")
            resultado = {**consultar(spec["auth_type"], binary), "instalacao_url": spec.get("instalacao_url", "")}
            if spec.get("login_direto"):
                cli = resultado
                resultado = {**openai_oauth.situacao(), "disponivel": importlib.util.find_spec("cryptography") is not None,
                             "instalado": cli["instalado"], "cli_configurado": cli["configurada"],
                             "instalacao_url": cli["instalacao_url"], "metodo": openai_oauth.metodo()}
                if resultado["metodo"] == "cli":
                    resultado["configurada"] = cli["configurada"]
        with self.lock:
            self._limpar()
            for tid, (p, t, _, _) in self.tentativas.items():
                if p == provedor and t.publico()["estado"] in {"aguardando", "validando"}:
                    resultado["tentativa"] = tid
                    break
        return resultado

    def iniciar(self, provedor, conta="", metodo=""):
        spec = self.spec(provedor)
        direto = spec["auth_type"] == "chatgpt_oauth" or (spec.get("login_direto") and metodo != "cli")
        if metodo == "cli" and spec["auth_type"] == "chatgpt_oauth":
            raise ValueError("Esta conexão não oferece CLI.")
        if metodo == "direto" and not direto:
            raise ValueError("Este provedor não oferece conexão direta.")
        with self.lock:
            self._limpar()
            if any(p == provedor and t.publico()["estado"] in {"aguardando", "validando"}
                   for p, t, _, _ in self.tentativas.values()):
                raise ValueError("Já existe um login em andamento para este provedor.")
            if len(self.tentativas) >= 16:
                raise ValueError("Aguarde as tentativas anteriores terminarem.")
            if direto:
                tentativa = LoginChatGPT(conta)
            else:
                from ..providers import _source_value
                binary = _source_value(None, spec.get("binary_env", "")) or spec.get("binary", "")
                tentativa = LoginCLI(spec["auth_type"], binary)
                tentativa.usar_como_chatgpt = bool(spec.get("login_direto"))
            tentativa.iniciar()
            tid = secrets.token_urlsafe(32)
            self.tentativas[tid] = (provedor, tentativa, time.monotonic(), False)
            return {"id": tid, **tentativa.publico()}

    def _limpar(self):
        for tid, (_, t, inicio, _) in list(self.tentativas.items()):
            if time.monotonic() - inicio > 660:
                t.cancelar()
                del self.tentativas[tid]

    def consultar(self, tid):
        with self.lock:
            self._limpar()
            if tid not in self.tentativas:
                raise ValueError("Tentativa não encontrada ou expirada.")
            p, t, inicio, notificado = self.tentativas[tid]
            publico = t.publico()
            if publico["configurada"] and not notificado:
                if getattr(t, "usar_como_chatgpt", False):
                    openai_oauth.usar_cli()
                if self.alterado:
                    self.alterado()
                self.tentativas[tid] = (p, t, inicio, True)
            return publico

    def cancelar(self, tid):
        with self.lock:
            if tid not in self.tentativas:
                raise ValueError("Tentativa não encontrada.")
            tentativa = self.tentativas[tid][1]
            if tentativa.publico()["estado"] in {"aguardando", "validando"}:
                tentativa.cancelar()
                tentativa.estado = "cancelado"

    def fechar(self):
        for _, t, _, _ in self.tentativas.values():
            t.cancelar()
