"""Classificação e filas explícitas não alteram seleções dedicadas."""
import asyncio
import inspect
import json
import time

from .classificacao import contrato, mensagens, validar_saida


class FalhaDeClassificacao(RuntimeError):
    pass


async def construir(config, alvo):
    from ..providers import build_provider

    return await asyncio.to_thread(build_provider, config, alvo["provedor"], models=[alvo["modelo"]])


async def classificar(config, escolha, pedido, contexto="", contextos=None, atividade=None):
    from ..state.classificacao import validar_classificador
    from .chain import _anotar_o_gasto, _somar

    escolha = validar_classificador(escolha, config.providers if config else {})
    if escolha["tipo"] != "llm":
        raise ValueError("Escolha uma LLM para classificar.")
    m = mensagens(pedido, contexto, contextos)
    alvos = [{k: escolha[k] for k in ("provedor", "modelo")}, *escolha.get("reservas", [])]
    inicio = time.monotonic()
    prazo = inicio + 30
    for indice, alvo in enumerate(alvos):
        restante = prazo - time.monotonic()
        if restante <= 0:
            break
        provedor = None
        evento = None
        chamado = False
        uso_capturado = None
        status = "falha"
        comeco = time.monotonic()
        try:
            timeout = restante / (len(alvos) - indice)
            limite_da_tentativa = time.monotonic() + timeout
            async def tentar():
                nonlocal provedor, evento, chamado, uso_capturado
                provedor = await construir(config, alvo)
                if provedor is None:
                    raise ValueError("LLM sem conexão ou desativada.")
                # Adaptadores que usam subprocesso também respeitam o prazo.
                provedor.timeout = max(0.1, min(float(getattr(provedor, "timeout", timeout)), limite_da_tentativa - time.monotonic()))
                evento = atividade.abrir(alvo["provedor"], "CLASSIFY", modo="classificador", tentativa=indice + 1) if atividade else None
                parametros = inspect.signature(provedor.complete).parameters
                aceita = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros.values())
                extras = {k: v for k, v in {"complexity": "CLASSIFY", "reasoning_effort": "low", "classification_labels": contrato()["rotulos"],
                                          "preferred_model": alvo["modelo"], "strict_model": True}.items()
                          if aceita or k in parametros}
                chamado = True
                try:
                    texto = await provedor.complete(m, temperature=0, **extras)
                finally:
                    # O uso de alguns adaptadores é local à tarefa assíncrona.
                    uso_capturado = getattr(provedor, "last_usage", None)
                if getattr(provedor, "last_tool_calls", None):
                    raise ValueError("O classificador devolveu ferramentas em vez de um nível.")
                return validar_saida(texto)
            nivel = await asyncio.wait_for(tentar(), timeout=timeout)
            status = "sucesso"
            uso_seguro = {k: uso_capturado[k] for k in ("entrada", "saida", "total", "raciocinio", "cacheado", "custo_usd")
                          if k in uso_capturado} if isinstance(uso_capturado, dict) else None
            return {"nivel": nivel, "provedor": alvo["provedor"], "modelo": alvo["modelo"],
                    "duracao_ms": round((time.monotonic() - inicio) * 1000), "uso": uso_seguro}
        except (asyncio.TimeoutError, ValueError, RuntimeError, OSError):
            continue
        except Exception:
            # Erros do SDK podem conter URLs ou cabeçalhos com segredo.
            continue
        finally:
            uso = uso_capturado
            if chamado:
                _anotar_o_gasto(alvo["provedor"], uso)
                _somar(uso)
            if evento:
                atividade.concluir(evento, status=status, modelo=alvo["modelo"], uso=uso,
                                   duracao_ms=(time.monotonic() - comeco) * 1000)
    raise FalhaDeClassificacao("Nenhuma LLM classificadora devolveu um nível válido no prazo de 30 segundos. Confira a conexão e os IDs dos modelos.")


def ordem_dos_niveis(nivel):
    niveis = contrato()["rotulos"]
    indice = niveis.index(nivel)
    return sorted(niveis, key=lambda n: (abs(niveis.index(n) - indice), -niveis.index(n)))


def entrada_da_conversa(conversa):
    def texto(m):
        valor = m.get("content", "")
        if isinstance(valor, str):
            return valor
        if isinstance(valor, list):
            return "\n".join(p.get("text", "") for p in valor if isinstance(p, dict) and isinstance(p.get("text"), str))
        return ""
    usuarios = [i for i, m in enumerate(conversa) if m.get("role") == "user" and texto(m).strip()]
    if not usuarios:
        raise ValueError("A classificação precisa de um pedido do usuário.")
    ultimo = usuarios[-1]
    pedido = texto(conversa[ultimo])[-16000:]
    contexto = json.dumps([{"role": m.get("role"), "content": texto(m)} for m in conversa[max(0, ultimo - 6):]
                          if m.get("role") in {"user", "assistant"}], ensure_ascii=False)[-24000:]
    return pedido, contexto


async def responder(cadeia, config, conversa, temperatura, contexto, tools, esforco):
    from ..state.classificacao import carregar
    from .chain import ChainProvider, FalhaDaCadeia, suporta_ferramentas
    from .selection import RouteSelection

    try:
        dados = carregar()
    except ValueError as exc:
        raise RuntimeError("A configuração do classificador não pôde ser lida. Confira o painel.") from exc
    if dados["classificador"]["tipo"] != "llm" or not any(dados["filas"].values()):
        raise RuntimeError("Configuração incompleta do classificador: salve um classificador e modelos nos blocos antes de usar a rota.")
    try:
        pedido, historico = entrada_da_conversa(conversa)
        resultado = await classificar(config, dados["classificador"], pedido, historico, dados["contextos"], cadeia.activity)
    except (ValueError, FalhaDeClassificacao):
        return None
    falhas = []
    vistos = set()
    exigidas = ChainProvider.exigencias(conversa)
    for nivel in ordem_dos_niveis(resultado["nivel"]):
        for alvo in dados["filas"][nivel]:
            chave = (alvo["provedor"], alvo["modelo"])
            if chave in vistos:
                continue
            vistos.add(chave)
            try:
                provedor = await construir(config, alvo)
                if provedor is None or (tools and not suporta_ferramentas(provedor)):
                    continue
                if exigidas and not exigidas <= cadeia.router.capabilities_of(provedor):
                    continue
                tentativa = ChainProvider([provedor], cadeia.router, activity=cadeia.activity)
                tentativa._classification_attempt = True
                texto = await tentativa.complete(conversa, temperatura, context=nivel,
                                                selection=RouteSelection.strict(alvo["provedor"] + ":" + alvo["modelo"]),
                                                tools=tools, reasoning_effort=esforco)
                for atributo in ("last_model", "last_provider", "last_usage", "last_tool_calls"):
                    setattr(cadeia, atributo, getattr(tentativa, atributo))
                return texto
            except Exception:
                falhas.append("other")
    raise FalhaDaCadeia("As filas do classificador se esgotaram sem resposta.", falhas or ["other"])
