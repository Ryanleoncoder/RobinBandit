"""Responses API pública com a autorização própria do plano ChatGPT."""
import asyncio
import json
from contextvars import ContextVar

from ..accounts.openai_oauth import LoginInvalido, RESOURCE, access_token


def _entrada(messages):
    itens = []
    for msg in messages:
        papel = msg.get("role")
        if papel == "tool":
            itens.append({"type": "function_call_output", "call_id": msg["tool_call_id"],
                          "output": msg.get("content") or ""})
            continue
        for call in msg.get("tool_calls") or []:
            funcao = call["function"]
            itens.append({"type": "function_call", "namespace": "robinbandit",
                          "call_id": call["id"], "name": funcao["name"], "arguments": funcao["arguments"]})
        conteudo = msg.get("content")
        if not conteudo:
            continue
        blocos = []
        if isinstance(conteudo, str):
            blocos.append({"type": "output_text" if papel == "assistant" else "input_text", "text": conteudo})
        else:
            for bloco in conteudo:
                if bloco.get("type") == "text":
                    blocos.append({"type": "output_text" if papel == "assistant" else "input_text", "text": bloco["text"]})
                elif bloco.get("type") == "image_url":
                    imagem = bloco["image_url"]
                    blocos.append({"type": "input_image", "image_url": imagem["url"], "detail": imagem.get("detail", "auto")})
                else:
                    raise ValueError("Este tipo de anexo não é aceito pela conexão ChatGPT.")
        itens.append({"type": "message", "role": "developer" if papel == "system" else papel, "content": blocos})
    return itens


class ChatGPTProvider:
    supports_tools = True
    last_quota = None
    last_truncated = False
    last_reasoning_summary = None

    def __init__(self, models, *, name="chatgpt", timeout=110):
        self.name, self.models, self.timeout = name, list(models), min(float(timeout), 110)
        self._ultimo = ContextVar("chatgpt_resultado_" + str(id(self)), default={})

    @property
    def last_usage(self):
        return self._ultimo.get().get("usage")

    @property
    def last_tool_calls(self):
        return self._ultimo.get().get("tool_calls")

    @property
    def last_model(self):
        return self._ultimo.get().get("model")

    async def complete(self, messages, temperature=0.2, tools=None, **kwargs):
        return await self.generate(messages, temperature=temperature, tools=tools, **kwargs)

    async def generate(self, messages, temperature=0.2, tools=None, reasoning_effort=None,
                       complexity="SIMPLE", is_classify=False, **kwargs):
        import httpx
        self._ultimo.set({})
        if not self.models:
            raise ValueError("Selecione um modelo ChatGPT.")
        modelo = self.models[0]
        payload = {"model": modelo, "input": _entrada(messages), "store": False, "stream": True}
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        nomes = set()
        if tools:
            funcoes = []
            for tool in tools:
                f = tool.get("function") or {}
                if tool.get("type") != "function" or not f.get("name") or f["name"] in nomes:
                    raise ValueError("Declaração de ferramenta inválida.")
                nomes.add(f["name"])
                funcoes.append({"type": "function", "name": f["name"], "description": f.get("description", ""),
                                "parameters": f.get("parameters", {"type": "object", "properties": {}}),
                                "strict": f.get("strict", False)})
            payload["tools"] = [{"type": "namespace", "name": "robinbandit", "description": "Ferramentas da chamada.", "tools": funcoes}]
        token = await asyncio.to_thread(access_token)
        final = None
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as cliente:
                async with cliente.stream("POST", RESOURCE + "/responses",
                                          headers={"Authorization": "Bearer " + token}, json=payload) as resposta:
                    if resposta.status_code >= 300:
                        erro = LoginInvalido("O ChatGPT recusou a chamada. Confira a conexão, o modelo e o limite do plano.")
                        erro.tipo = "quota" if resposta.status_code == 429 else "auth" if resposta.status_code in (401, 403) else "transient"
                        raise erro
                    linhas = []
                    async for linha in resposta.aiter_lines():
                        if linha.startswith("data:"):
                            linhas.append(linha[5:].lstrip())
                        elif not linha and linhas:
                            corpo = "\n".join(linhas)
                            linhas = []
                            if corpo == "[DONE]":
                                continue
                            evento = json.loads(corpo)
                            if evento.get("type") in {"response.failed", "error", "response.incomplete"}:
                                raise LoginInvalido("O ChatGPT não concluiu a chamada.")
                            if evento.get("type") == "response.completed":
                                final = evento["response"]
        except LoginInvalido:
            raise
        except Exception:
            raise LoginInvalido("Não foi possível concluir a conexão com o ChatGPT.") from None
        if not isinstance(final, dict) or final.get("status") != "completed":
            raise LoginInvalido("A conexão terminou antes da resposta final do ChatGPT.")
        textos, calls = [], []
        for item in final.get("output", []):
            if item.get("type") == "message":
                for bloco in item.get("content", []):
                    if bloco.get("type") == "refusal":
                        from .recusa import RecusaDoModelo
                        raise RecusaDoModelo(self.name + ":" + modelo, bloco.get("refusal", ""))
                    if bloco.get("type") == "output_text":
                        textos.append(bloco.get("text", ""))
            elif item.get("type") == "function_call":
                if item.get("name") not in nomes or item.get("namespace", "robinbandit") != "robinbandit":
                    raise LoginInvalido("O ChatGPT solicitou uma ferramenta fora da chamada.")
                calls.append({"id": item["call_id"], "type": "function", "function": {
                    "name": item["name"], "arguments": item["arguments"]}})
        uso = final.get("usage")
        medido = None
        if isinstance(uso, dict):
            medido = {"entrada": uso.get("input_tokens", 0), "saida": uso.get("output_tokens", 0),
                      "total": uso.get("total_tokens", 0),
                      "cacheado": (uso.get("input_tokens_details") or {}).get("cached_tokens", 0)}
        texto = "\n".join(textos)
        if not texto.strip() and not calls:
            raise LoginInvalido("O ChatGPT devolveu uma resposta vazia.")
        self._ultimo.set({"model": self.name + ":" + modelo, "usage": medido, "tool_calls": calls or None})
        return texto


async def listar_modelos():
    import httpx
    token = await asyncio.to_thread(access_token)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as cliente:
            resposta = await cliente.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + token})
            resposta.raise_for_status()
            return [{"id": m["slug"], "name": m.get("display_name", m["slug"])}
                    for m in resposta.json()["models"] if m.get("visibility") == "list"]
    except Exception:
        raise LoginInvalido("Não foi possível consultar os modelos desta conta ChatGPT.") from None
