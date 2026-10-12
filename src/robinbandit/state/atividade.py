"""Atividade recente com persistência opcional de metadados concluídos."""
from __future__ import annotations

import threading
import time
import uuid
import json
import os
import logging
from pathlib import Path
from .trava import bloquear
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class Atividade:
    def __init__(self, limite: int = 60, agora=time.time, *, persistir=False) -> None:
        self._limite = max(1, int(limite))
        self._agora = agora
        self._lock = threading.RLock()
        self._itens: Deque[Dict[str, Any]] = deque()
        self._por_id: Dict[str, Dict[str, Any]] = {}
        self._persistir = persistir

    def _caminho(self):
        return Path(os.environ.get("ROBINBANDIT_HOME") or Path.home() / ".robinbandit") / "atividade.json"

    def _ler(self):
        try:
            dados = json.loads(self._caminho().read_text(encoding="utf-8"))
            return [i for i in dados if isinstance(i, dict)] if isinstance(dados, list) else []
        except (OSError, ValueError):
            return []

    def _guardar(self, item):
        if not self._persistir:
            return
        # Contexto livre e conteúdo da chamada não entram no arquivo.
        campos = ("id", "provedor", "modelo", "status", "inicio", "duracao_ms", "tentativa", "modo", "uso")
        seguro = {k: item[k] for k in campos if k in item}
        try:
            alvo = self._caminho()
            with bloquear(alvo):
                dados = [i for i in self._ler() if i.get("id") != item["id"]]
                dados.append(seguro)
                dados.sort(key=lambda i: float(i.get("inicio", 0)), reverse=True)
                tmp = alvo.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
                tmp.write_text(json.dumps(dados[:self._limite], ensure_ascii=False), encoding="utf-8")
                tmp.replace(alvo)
        except OSError:
            logging.getLogger(__name__).warning("Não foi possível gravar a atividade do roteador.")

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
                    "entrada", "saida", "total", "cacheado", "custo_usd", "raciocinio",
                    "chamadas_com_custo",
                )
                item["uso"] = {campo: uso[campo] for campo in permitidos if campo in uso}
            self._guardar(item)

    def resumo(self, limite: int = 12) -> List[Dict[str, Any]]:
        agora = self._agora()
        with self._lock:
            por_id = {i.get("id"): i for i in self._ler()} if self._persistir else {}
            por_id.update({i["id"]: i for i in self._itens})
            ordenados = sorted(por_id.values(), key=lambda i: float(i.get("inicio", 0)), reverse=True)
            itens = [dict(item) for item in ordenados[:max(1, int(limite))]]
        for item in itens:
            item["ha_segundos"] = round(max(0.0, agora - float(item.pop("inicio"))), 1)
        return itens


__all__ = ["Atividade"]
