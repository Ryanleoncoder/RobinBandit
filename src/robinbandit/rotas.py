"""Uma rota nomeada só tenta os provedores e modelos que ela declara."""
from dataclasses import replace


class RotaNomeada:
    def __init__(self, nome, cadeia):
        self.name = nome
        self.cadeia = cadeia
        self.cadeia._classification_disabled = True

    def __getattr__(self, nome):
        return getattr(self.cadeia, nome)

    async def complete(self, messages, temperature=0.2, complexity=None, **kwargs):
        if complexity is not None and "context" not in kwargs:
            kwargs["context"] = complexity
        return await self.cadeia.complete(messages, temperature, **kwargs)


def build_route(config, nome, settings=None):
    from .gateway import RobinGateway
    from .providers import build_provider
    from .routing.chain import ChainProvider

    if nome not in config.routes:
        raise KeyError(f"rota não declarada: {nome}")
    spec = config.routes[nome]
    providers = []
    for chave in spec["chain_order"]:
        provider = build_provider(config, chave, settings, models=spec["models"].get(chave), model_role=nome)
        if provider is not None:
            providers.append(provider)
    if not providers:
        raise RuntimeError(f"nenhum provedor disponível na rota {nome}")
    scoped = replace(config, strategy="fixed", chain_order=spec["chain_order"],
                     last_resort=config.last_resort if config.last_resort in spec["chain_order"] else None)
    return RotaNomeada(nome, ChainProvider(providers, RobinGateway(scoped)))
