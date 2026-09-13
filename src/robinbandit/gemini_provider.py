import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .credentials import KeyRotator, parse_keys, is_quota_error
from .token_budget import model_token_budget

logger = logging.getLogger(__name__)

def _usage_gemini(data: Dict) -> Optional[Dict[str, int]]:
    """`usageMetadata` do Gemini traduzido para o mesmo formato dos demais."""
    bruto = data.get("usageMetadata") if isinstance(data, dict) else None
    if not isinstance(bruto, dict):
        return None
    entrada = int(bruto.get("promptTokenCount") or 0)
    saida = int(bruto.get("candidatesTokenCount") or 0)
    total = int(bruto.get("totalTokenCount") or (entrada + saida))
    if not total:
        return None
    # Quanto da entrada veio do cache implicito. O Gemini cobra 10% por esses
    # tokens, entao a mesma entrada pode custar dez vezes mais ou menos sem
    # que nada apareca no total. Sem este numero nao da pra saber se um prefixo
    # estavel esta valendo alguma coisa — e essa duvida ja custou uma decisao
    # errada aqui: recortar o prompt "para economizar" quebraria o cache.
    cacheado = int(bruto.get("cachedContentTokenCount") or 0)
    usado = {"entrada": entrada, "saida": saida, "total": total}
    if cacheado:
        usado["cacheado"] = cacheado
    return usado


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Cota diária (RPD) e qualidade relativa por modelo, do painel de cotas do free
# tier. RPD alto = workhorse (rotina, sem medo de gastar); RPD baixo = reservar
# pro CRITICAL. Os "premium" (2.5/3.5-flash) têm SÓ 20/dia — não dá pra torrar
# em bate-papo. Modelos fora do mapa usam o padrão (ordem configurada).
_GEMINI_RPD = {
    "gemma-4-31b-it": 1500, "gemma-4-26b-a4b-it": 1500,
    "gemini-3.1-flash-lite": 500,
    "gemini-2.5-flash-lite": 20, "gemini-2.5-flash": 20, "gemini-3.5-flash": 20,
}
_GEMINI_QUALITY = {
    "gemini-3.5-flash": 5, "gemini-2.5-flash": 4, "gemini-3.1-flash-lite": 3,
    "gemini-2.5-flash-lite": 3, "gemma-4-31b-it": 3, "gemma-4-26b-a4b-it": 2,
}


def _order_gemini_models(models: List[str], complexity: Optional[str]) -> List[str]:
    """Ordena os modelos do Gemini conforme a complexidade E a cota (RPD):
    - CRITICAL/COMPLEX: qualidade primeiro (aceita gastar a cota escassa).
    - resto (rotina): MAIOR RPD primeiro — poupa os modelos de 20/dia.
    Estável pra empates via índice na lista configurada."""
    idx = {m: i for i, m in enumerate(models)}
    if (complexity or "").upper() in ("CRITICAL", "COMPLEX"):
        return sorted(models, key=lambda m: (-_GEMINI_QUALITY.get(m, 0), idx[m]))
    return sorted(models, key=lambda m: (-_GEMINI_RPD.get(m, 100), idx[m]))


def _split_messages(messages: List[Dict[str, str]]) -> Tuple[str, List[Dict]]:
    """Converte o formato OpenAI/Groq (roles system/user/assistant) para o do
    Gemini: instruções de sistema vão para `system_instruction`, e o resto vira
    `contents` com roles user/model. Mensagens consecutivas do mesmo papel são
    mescladas — o Gemini exige papéis alternados, e o orquestrador manda o user
    duplicado no primeiro turno (uma vez no histórico, outra como mensagem)."""
    system_parts: List[str] = []
    contents: List[Dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            system_parts.append(content if isinstance(content, str) else _somente_texto(content))
            continue
        g_role = "model" if role == "assistant" else "user"
        partes = _partes(content)
        if contents and contents[-1]["role"] == g_role:
            contents[-1]["parts"].extend(partes)
        else:
            contents.append({"role": g_role, "parts": partes})
    return "\n\n".join(system_parts), contents


def _somente_texto(content: Any) -> str:
    if isinstance(content, str):
        return content
    pedacos = [
        str(parte.get("text") or "")
        for parte in (content or [])
        if isinstance(parte, dict) and parte.get("type") == "text"
    ]
    return "\n".join(p for p in pedacos if p)


def _partes(content: Any) -> List[Dict]:
    """Conteudo multimodal no formato OpenAI vira `parts` do Gemini.

    Imagem chega como data URL (`data:image/png;base64,...`) ou URL comum; o
    Gemini so aceita inline com mime declarado, entao a URL comum vira texto
    em vez de virar um binario que nao temos.
    """
    if isinstance(content, str):
        return [{"text": content}]
    partes: List[Dict] = []
    for item in content or []:
        if not isinstance(item, dict):
            continue
        tipo = str(item.get("type") or "")
        if tipo == "text":
            partes.append({"text": str(item.get("text") or "")})
        elif tipo.startswith("image"):
            bruto = item.get("image_url")
            url = str((bruto.get("url") if isinstance(bruto, dict) else bruto) or item.get("url") or "")
            if url.startswith("data:") and "base64," in url:
                cabecalho, dados = url.split("base64,", 1)
                mime = cabecalho[5:].rstrip(";") or "image/png"
                partes.append({"inline_data": {"mime_type": mime, "data": dados}})
            elif url:
                partes.append({"text": f"[imagem em {url}]"})
    return partes or [{"text": ""}]


class GeminiProvider:
    """Provedor da API Gemini (Google AI). Mesmo contrato de `complete` dos
    outros provedores — o Harness não muda em nada. Pensado como fallback do
    Groq, mas funciona sozinho também."""

    def __init__(self, api_key: str, models: List[str]):
        self.name = "gemini"
        # Pool de credenciais: aceita 1 chave ou CSV ("k1,k2,k3") — cada Gemini
        # tem RPM baixo (5/min), então várias chaves multiplicam a cota.
        self._keys = KeyRotator(parse_keys(api_key))
        self.models = models or ["gemini-2.5-flash"]
        self.last_model: Optional[str] = None
        self.last_reasoning_summary: Optional[str] = None
        self.last_usage: Optional[Dict[str, int]] = None

    @staticmethod
    def _extract_parts_payload(data: Dict) -> Tuple[str, Optional[str]]:
        candidate = ((data.get("candidates") or [{}])[0] or {})
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        visible_parts: List[str] = []
        thought_parts: List[str] = []

        for part in parts:
            text = str(part.get("text") or "").strip()
            if not text:
                continue
            if part.get("thought"):
                thought_parts.append(text)
            else:
                visible_parts.append(text)

        visible_text = "\n\n".join(visible_parts).strip()
        thought_summary = "\n\n".join(thought_parts).strip() or None
        return visible_text, thought_summary

    def _build_payload(self, messages: List[Dict[str, str]], temperature: float, include_thoughts: bool = True) -> Dict:
        system_instruction, contents = _split_messages(messages)
        # Sem responseMimeType: o mesmo provider serve ao PLANNER (que precisa de
        # JSON, guiado pelo prompt) e ao RESPONDER (texto puro). Forçar JSON aqui
        # quebraria as respostas em linguagem natural do responder.
        payload: Dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                # maxOutputTokens é DINÂMICO por modelo (definido no loop de complete()
                # via model_token_budget, igual aos outros providers). Aqui só um
                # default; o valor real depende do modelo que responder.
                "maxOutputTokens": model_token_budget(None),
                "thinkingConfig": {
                    "includeThoughts": include_thoughts,
                },
            },
        }
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}
        return payload

    async def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2, complexity: Optional[str] = None,
                       preferred_model: Optional[str] = None,
                       strict_model: bool = False) -> str:
        is_classify = (complexity or "").upper() == "CLASSIFY"
        payload = self._build_payload(messages, temperature, include_thoughts=not is_classify)
        last_error: Optional[Exception] = None
        self.last_reasoning_summary = None
        self.last_model = None
        self.last_attempted_model = None
        self.model_failures = []

        # Troca inteligente: ordena por complexidade + cota (RPD). Rotina vai nos
        # workhorses de RPD alto (gemma/flash-lite); CRITICAL usa os melhores.
        models_to_try = _order_gemini_models(list(self.models), complexity)
        # Perfil (ex.: coding → antigravity): tenta o modelo preferido PRIMEIRO,
        # mesmo que não esteja em GEMINI_MODELS (é um id válido da API). Se der
        # 429/erro, cai nos demais normalmente.
        if preferred_model and strict_model:
            models_to_try = [preferred_model]
        elif preferred_model:
            models_to_try = [preferred_model] + [m for m in models_to_try if m != preferred_model]

        async with httpx.AsyncClient(timeout=20.0) as client:
            # rotaciona as chaves (Gemini limita RPM por chave/projeto)
            for key in self._keys.order():
                cota_na_chave = False
                for model in models_to_try:
                    self.last_attempted_model = f"gemini:{model}"
                    try:
                        # Budget DINÂMICO por modelo: flash/pro grandes → 8192,
                        # flash-lite/gemma pequenos → 2048. Com includeThoughts, o
                        # pensamento e a resposta dividem esse teto — 8192 evita o
                        # truncamento da resposta ("...nós temos um mapa").
                        # floor=4096: o Gemini SEMPRE gera com includeThoughts, então
                        # o pensamento divide o teto com a resposta — garante folga.
                        payload["generationConfig"]["maxOutputTokens"] = (
                            min(model_token_budget(model, floor=512), 512)
                            if is_classify else model_token_budget(model, floor=4096)
                        )
                        response = await client.post(
                            GEMINI_URL.format(model=model),
                            headers={"x-goog-api-key": key},
                            json=payload,
                        )
                        response.raise_for_status()
                        data = response.json()
                        self.last_usage = _usage_gemini(data)
                        visible_text, thought_summary = self._extract_parts_payload(data)
                        if thought_summary:
                            self.last_reasoning_summary = thought_summary[:2400]
                        self.last_model = f"gemini:{model}"
                        logger.info("Gemini respondeu com o modelo %s", model)
                        if visible_text:
                            return visible_text
                        return data["candidates"][0]["content"]["parts"][0]["text"]
                    except Exception as exc:
                        self.model_failures.append(f"gemini:{model}")
                        logger.warning("Gemini model %s failed: %s", model, exc)
                        last_error = exc
                        if is_quota_error(exc):
                            cota_na_chave = True
                            break  # essa chave bateu cota → próxima chave
                        continue
                if cota_na_chave and self._keys.has_multiple:
                    continue
        raise RuntimeError(f"Todos os modelos/chaves Gemini falharam: {last_error}")
