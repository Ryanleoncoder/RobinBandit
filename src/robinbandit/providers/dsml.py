"""Chamada de ferramenta do DeepSeek que chega como texto (DSML).

O DeepSeek V3.2/V4 escreve a chamada no proprio formato:

    <｜DSML｜tool_calls>
    <｜DSML｜invoke name="executar_comando">
    <｜DSML｜parameter name="comando" string="true">git log -1</｜DSML｜parameter>
    </｜DSML｜invoke>
    </｜DSML｜tool_calls>

Quem serve o modelo deveria converter isso em `tool_calls`; quando nao
converte, o texto chega no `content`. A intencao de chamar esta completa, entao
aqui ela vira a chamada que era.

`string="true"` e valor literal; `string="false"` e JSON. A abertura
`tool_calls` pode faltar, por isso a leitura parte do `invoke`.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

_BARRA = "[｜|]"
_INVOKE = re.compile(
    rf"<{_BARRA}DSML{_BARRA}invoke\s+name=\"([^\"]+)\"\s*>(.*?)</{_BARRA}DSML{_BARRA}invoke>",
    re.DOTALL,
)
_PARAMETRO = re.compile(
    rf"<{_BARRA}DSML{_BARRA}parameter\s+name=\"([^\"]+)\"(?:\s+string=\"(true|false)\")?\s*>(.*?)"
    rf"</{_BARRA}DSML{_BARRA}parameter>",
    re.DOTALL,
)
_ENVELOPE = re.compile(rf"</?{_BARRA}DSML{_BARRA}(?:tool_calls|function_calls)>")


def _valor(bruto: str, literal: str) -> Any:
    if literal == "false":
        try:
            return json.loads(bruto.strip())
        except ValueError:
            return bruto.strip()
    return bruto.strip("\n")


def chamadas_do_dsml(texto: str) -> Tuple[str, List[Dict[str, Any]]]:
    """O texto sem as chamadas, e as chamadas no formato `tool_calls`."""
    conteudo = str(texto or "")
    if "DSML" not in conteudo:
        return conteudo, []
    chamadas: List[Dict[str, Any]] = []
    for i, invoke in enumerate(_INVOKE.finditer(conteudo)):
        argumentos = {nome: _valor(valor, literal)
                      for nome, literal, valor in _PARAMETRO.findall(invoke.group(2))}
        chamadas.append({
            "id": f"dsml_{i}",
            "type": "function",
            "function": {"name": invoke.group(1).strip(),
                         "arguments": json.dumps(argumentos, ensure_ascii=False)},
        })
    if not chamadas:
        return conteudo, []
    resto = _ENVELOPE.sub("", _INVOKE.sub("", conteudo)).strip()
    return resto, chamadas
