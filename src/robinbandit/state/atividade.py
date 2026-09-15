"""Atividade recente do roteador, somente em memória."""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class Atividade:
    def __init__(self, limite: int = 60, agora=time.time) -> None:
        self._limite = max(1, int(limite))
        self._agora = agora
        self._lock = threading.RLock()
        self._itens: Deque[Dict[str, Any]] = deque()
        self._por_id: Dict[str, Dict[str, Any]] = {}

    def abrir(
        self,
        provedor: str,
        contexto: Optional[str] = None,
        *,
        modo: str = "router",
        tentativa: int = 1,
    ) -> str:
        identificador = uuid.uuid4().hex
        item = {
            "id": identificador,
            "provedor": str(provedor or ""),
            "contexto": str(contexto or ""),
            "modo": str(modo or "router"),
            "tentativa": max(1, int(tentativa)),
            "status": "em_andamento",
            "inicio": self._agora(),
            "duracao_ms": None,
            "modelo": "",
            "motivo": "",
            "uso": None,
        }
        with self._lock:
            self._itens.appendleft(item)
            self._por_id[identificador] = item
            while len(self._itens) > self._limite:
                antigo = self._itens.pop()
                self._por_id.pop(antigo["id"], None)
        return identificador

    def concluir(
        self,
        identificador: str,
        *,
        status: str,
        provedor: Optional[str] = None,
        modelo: Optional[str] = None,
        duracao_ms: Optional[float] = None,
        motivo: Optional[str] = None,
        uso: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            item = self._por_id.get(identificador)
            if item is None:
                return
            item["status"] = str(status or "falha")
            if provedor:
                item["provedor"] = str(provedor)
            item["modelo"] = str(modelo or "")
            item["motivo"] = str(motivo or "")[:160]
            item["duracao_ms"] = (
                round(float(duracao_ms)) if duracao_ms is not None else None
            )
            if isinstance(uso, dict):
                permitidos = (
                    "entrada", "saida", "total", "cacheado", "custo_usd",
                    "chamadas_com_custo",
                )
                item["uso"] = {campo: uso[campo] for campo in permitidos if campo in uso}

    def resumo(self, limite: int = 12) -> List[Dict[str, Any]]:
        agora = self._agora()
        with self._lock:
            itens = [dict(item) for item in list(self._itens)[:max(1, int(limite))]]
        for item in itens:
            item["ha_segundos"] = round(max(0.0, agora - float(item.pop("inicio"))), 1)
        return itens


__all__ = ["Atividade"]
