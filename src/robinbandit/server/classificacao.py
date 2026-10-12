"""Salvar e testar não ativam o modo de roteamento."""
import asyncio
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..state import classificacao
from ..routing.classificacao import contrato


class Alvo(BaseModel):
    provedor: str = Field(min_length=1, max_length=128)
    modelo: str = Field(min_length=1, max_length=256)

    model_config = {"extra": "forbid"}


class Classificador(BaseModel):
    tipo: Literal["nenhum", "llm"]
    provedor: str = Field(default="", max_length=128)
    modelo: str = Field(default="", max_length=256)
    reservas: List[Alvo] = Field(default_factory=list, max_length=5)

    model_config = {"extra": "forbid"}


class Filas(BaseModel):
    filas: Dict[str, List[Alvo]]
    classificador: Optional[Classificador] = None
    contextos: Optional[Dict[str, str]] = None

    model_config = {"extra": "forbid"}


class Teste(BaseModel):
    pedido: str = Field(min_length=1, max_length=16000)
    contexto: str = Field(default="", max_length=24000)
    classificador: Classificador
    contextos: Dict[str, str]

    model_config = {"extra": "forbid"}


def escolha_do(pedido):
    dados = pedido.model_dump(exclude={"reservas"})
    if pedido.reservas:
        dados["reservas"] = [a.model_dump() for a in pedido.reservas]
    return dados


def rotas(config, atividade=None):
    router = APIRouter()
    teste_em_curso = asyncio.Lock()

    @router.get("/config/classificacao")
    async def ler():
        try:
            return {**classificacao.carregar(), "contrato": contrato()}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.put("/config/classificacao")
    async def gravar(pedido: Filas):
        try:
            filas = {k: [a.model_dump() for a in v] for k, v in pedido.filas.items()}
            escolha = escolha_do(pedido.classificador) if pedido.classificador is not None else None
            return classificacao.guardar(filas, getattr(config, "providers", {}) or {}, escolha, pedido.contextos)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/config/classificacao/testar")
    async def testar(pedido: Teste):
        from ..routing.classificador_execucao import classificar, FalhaDeClassificacao
        if teste_em_curso.locked():
            raise HTTPException(409, "Um teste de classificação já está em andamento.")
        async with teste_em_curso:
            try:
                return await classificar(config, escolha_do(pedido.classificador), pedido.pedido,
                                         pedido.contexto, pedido.contextos, atividade)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except FalhaDeClassificacao as exc:
                raise HTTPException(502, str(exc)) from exc

    return router
