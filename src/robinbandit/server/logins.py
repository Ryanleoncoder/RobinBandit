"""Conexão de contas só pode ser iniciada na máquina da pessoa."""
import ipaddress
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..accounts import openai_oauth
from ..accounts.login import Logins


class PedidoLogin(BaseModel):
    conta: str = Field(default="", max_length=128)
    metodo: Literal["", "direto", "cli"] = ""


def _local(request):
    host = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "testclient"
    origem = urlsplit(request.headers.get("origin", ""))
    host_permitido = request.url.hostname in {"127.0.0.1", "localhost", "::1"} or (
        host == "testclient" and request.url.hostname == "testserver")
    if (not local or request.headers.get("x-robinbandit-login") != "1"
            or not host_permitido
            or (request.headers.get("origin") and not origem.netloc)
            or (origem.netloc and (origem.scheme not in {"http", "https"}
                                  or origem.hostname not in {"127.0.0.1", "localhost", "::1"}))):
        raise HTTPException(403, "Inicie a conexão na máquina local pelo painel.")


def rotas(config, alterado=None):
    logins = Logins(config, alterado)

    @asynccontextmanager
    async def lifespan(_):
        yield
        logins.fechar()

    router = APIRouter(prefix="/login", lifespan=lifespan)
    router.gestor_login = logins

    @router.get("/{provedor}")
    def status(provedor: str, request: Request):
        _local(request)
        try:
            return logins.status(provedor)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.post("/{provedor}")
    def iniciar(provedor: str, pedido: PedidoLogin, request: Request):
        _local(request)
        try:
            return logins.iniciar(provedor, pedido.conta, pedido.metodo)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(503, "Não foi possível iniciar o login oficial.") from None

    @router.get("/tentativas/{tid}")
    def tentativa(tid: str, request: Request):
        _local(request)
        try:
            return logins.consultar(tid)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.delete("/tentativas/{tid}")
    def cancelar(tid: str, request: Request):
        _local(request)
        try:
            logins.cancelar(tid)
            return {"cancelada": True}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.post("/{provedor}/selecionar")
    def selecionar(provedor: str, pedido: PedidoLogin, request: Request):
        _local(request)
        try:
            spec = logins.spec(provedor)
            if spec["auth_type"] != "chatgpt_oauth" and not spec.get("login_direto"):
                raise HTTPException(400, "Esta conta é gerenciada pelo CLI oficial.")
            openai_oauth.selecionar(pedido.conta)
            if alterado:
                alterado()
            return openai_oauth.situacao()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.post("/{provedor}/sair")
    def sair(provedor: str, pedido: PedidoLogin, request: Request):
        _local(request)
        try:
            spec = logins.spec(provedor)
            if spec["auth_type"] != "chatgpt_oauth" and not spec.get("login_direto"):
                raise HTTPException(400, "Encerre esta conexão pelo CLI oficial.")
            resultado = openai_oauth.sair(pedido.conta)
            if alterado:
                alterado()
            return resultado
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    return router
