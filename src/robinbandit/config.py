"""Configuração declarativa do RobinBandit."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


def caminho_do_usuario() -> Path:
    """Config pessoal desta maquina. `ROBINBANDIT_HOME` aponta para outra."""
    import os

    home = os.environ.get("ROBINBANDIT_HOME") or str(Path.home() / ".robinbandit")
    return Path(home) / "config.yaml"


def _fundir(base: Any, novo: Any) -> Any:
    """Mapa dentro de mapa se funde; o resto o usuario substitui inteiro.

    Trocar `providers` inteiro por causa de um endpoint seria hostil, mas
    fundir LISTA nao: quem escreve `chain_order` esta dizendo a ordem que
    quer, e mesclar com a de fabrica produziria uma terceira ordem que
    ninguem pediu.
    """
    if isinstance(base, Mapping) and isinstance(novo, Mapping):
        saida = dict(base)
        for chave, valor in novo.items():
            saida[chave] = _fundir(saida.get(chave), valor)
        return saida
    return novo


# Nome reservado para o catalogo que vem dentro do pacote. Quem escreve
# `herda: padrao` quer os 40+ provedores de fabrica sem copia-los.
CATALOGO_DE_FABRICA = "padrao"


def caminho_do_catalogo() -> Path:
    """O catalogo de fabrica, dentro do pacote — nao ao lado dele.

    Antes ele morava em `config/` na raiz do repositorio, o que funcionava para
    quem clonava e deixava quem instalava pelo pip sem catalogo nenhum.
    """
    return Path(__file__).resolve().parent / "padrao.yaml"


def _resolver_heranca(raw: Mapping[str, Any], origem: Path) -> Mapping[str, Any]:
    """Aplica `herda:` — o arquivo do agente e o que MUDA, nao uma copia.

    Sem isto, cada agente hospedeiro versionava as 700 linhas do catalogo
    inteiro e as copias envelheciam em ritmos diferentes.
    """
    pai = raw.get("herda") or raw.get("extends")
    if not pai:
        return raw
    if str(pai).strip() == CATALOGO_DE_FABRICA:
        caminho = caminho_do_catalogo()
    else:
        caminho = Path(str(pai)).expanduser()
        if not caminho.is_absolute():
            caminho = origem.parent / caminho
    if not caminho.is_file():
        raise FileNotFoundError(f"{origem}: herda aponta para arquivo inexistente: {caminho}")
    if caminho.resolve() == origem.resolve():
        raise ValueError(f"{origem}: herda apontando para o proprio arquivo")

    import yaml

    with caminho.open("r", encoding="utf-8") as stream:
        base = yaml.safe_load(stream) or {}
    base = _resolver_heranca(base, caminho)
    filho = {k: v for k, v in raw.items() if k not in ("herda", "extends")}
    return _fundir(dict(base), filho)


def _com_override_do_usuario(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """Aplica `~/.robinbandit/config.yaml` por cima do que veio no repo.

    O que vem versionado sao os PADROES — inclusive os priors de qualidade e
    tier. O que e desta maquina (endpoint local, chave, ordem preferida) fica
    fora do repositorio, sem exigir um fork para mudar uma linha.
    """
    caminho = caminho_do_usuario()
    if not caminho.exists():
        return raw
    try:
        import yaml

        with caminho.open("r", encoding="utf-8") as stream:
            do_usuario = yaml.safe_load(stream) or {}
    except Exception as exc:
        logger.warning("RobinBandit: config do usuario ignorada (%s): %s", caminho, exc)
        return raw
    if not isinstance(do_usuario, Mapping):
        return raw
    logger.info("RobinBandit: aplicando config do usuario de %s", caminho)
    return _fundir(dict(raw), do_usuario)


@dataclass(frozen=True)
class RobinConfig:
    version: int = 1
    agent_mode: str = "universal"
    # Em que língua a interface responde. O YAML declara o padrão; a escolha
    # feita no painel ou pela CLI é um override por cima, como tier e cadeia.
    # Vazio significa "descubra pelo sistema".
    idioma: str = ""
    providers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    weights: Dict[str, Tuple[float, float, float]] = field(default_factory=dict)
    last_resort: Optional[str] = None
    strategy: str = "adaptive"
    chain_order: List[str] = field(default_factory=list)
    cost_penalties: Dict[str, float] = field(default_factory=dict)
    profiles: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    secrets: Dict[str, Any] = field(default_factory=dict)
    accounts: Dict[str, Any] = field(default_factory=dict)
    erros: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RobinConfig":
        if not isinstance(raw, Mapping):
            raise TypeError("configuração RobinBandit deve ser um objeto/mapa")
        version = int(raw.get("version", 1))
        if version != 1:
            raise ValueError(f"versão de configuração não suportada: {version}")

        agent_mode = str(raw.get("agent_mode", "universal")).strip().lower()
        if agent_mode not in {"sentury", "universal"}:
            raise ValueError("agent_mode deve ser sentury ou universal")

        idioma = str(raw.get("idioma", "") or "").strip().lower()
        if idioma and idioma not in {"pt", "en"}:
            raise ValueError("idioma deve ser pt ou en")

        providers_raw = raw.get("providers") or {}
        if not isinstance(providers_raw, Mapping):
            raise TypeError("providers deve ser um mapa")
        providers: Dict[str, Dict[str, Any]] = {}
        for key, value in providers_raw.items():
            if not isinstance(value, Mapping):
                raise TypeError(f"providers.{key} deve ser um mapa")
            item = dict(value)
            forbidden = {name for name in ("api_key", "secret", "token") if name in item}
            if forbidden:
                raise ValueError(
                    f"providers.{key} contém segredo literal; use apenas *_env"
                )
            if "tier" in item:
                item["tier"] = int(item["tier"])
            if "quality" in item:
                quality = float(item["quality"])
                if not 0.0 <= quality <= 1.0:
                    raise ValueError(f"providers.{key}.quality deve estar entre 0 e 1")
                item["quality"] = quality
            if "priority" in item:
                item["priority"] = int(item["priority"])
                if item["priority"] < 1:
                    raise ValueError(f"providers.{key}.priority deve ser >= 1")
            if "models" in item and not isinstance(item["models"], (list, tuple, Mapping)):
                raise TypeError(f"providers.{key}.models deve ser lista ou mapa")
            auth_type = str(item.get("auth_type") or "").strip().lower()
            # `claude_cli` e `codex_cli`: quem autentica e o CLI da assinatura,
            # e o RobinBandit nunca toca na credencial.
            if auth_type and auth_type not in {"api_key", "codex_cli", "claude_cli"}:
                raise ValueError(f"providers.{key}.auth_type desconhecido: {auth_type}")
            adapter = str(item.get("adapter") or "openai").strip().lower()
            if adapter in {"codex", "codex_app_server"} and auth_type != "codex_cli":
                raise ValueError(
                    f"providers.{key} com adapter Codex exige auth_type: codex_cli"
                )
            providers[str(key).strip().lower()] = item

        routing = raw.get("routing") or {}
        if not isinstance(routing, Mapping):
            raise TypeError("routing deve ser um mapa")
        weights_raw = routing.get("weights") or {}
        weights: Dict[str, Tuple[float, float, float]] = {}
        for context, values in weights_raw.items():
            if not isinstance(values, (list, tuple)) or len(values) != 3:
                raise ValueError(f"routing.weights.{context} deve ter três números")
            parsed = tuple(float(v) for v in values)
            if any(v < 0 for v in parsed) or sum(parsed) <= 0:
                raise ValueError(f"routing.weights.{context} contém pesos inválidos")
            weights[str(context)] = parsed

        last_resort = routing.get("last_resort")
        strategy = str(routing.get("strategy", "adaptive")).strip().lower()
        if strategy not in {"adaptive", "tier"}:
            raise ValueError("routing.strategy deve ser adaptive ou tier")
        chain_order = [str(v).strip().lower() for v in (routing.get("chain_order") or []) if str(v).strip()]
        unknown = [key for key in chain_order if key not in providers]
        if unknown:
            raise ValueError(f"routing.chain_order contém provedores desconhecidos: {', '.join(unknown)}")
        if len(chain_order) != len(set(chain_order)):
            raise ValueError("routing.chain_order contém provedores duplicados")
        if last_resort and str(last_resort).strip().lower() not in providers:
            raise ValueError("routing.last_resort deve apontar para um provedor conhecido")
        # Como reagir ao erro de um provedor: tabela, nao algoritmo. Aplicada
        # no import para valer em todo mundo que ja tem a config carregada.
        erros = dict(routing.get("erros") or {})
        from .erros import configurar as _configurar_erros

        _configurar_erros(erros)

        # Sonda opcional de cota. Custa cota para medir cota, entao vem
        # desligada: so compensa em provedor de assinatura com janela longa.
        from .quota_ping import configurar as _configurar_ping

        _configurar_ping(routing.get("quota_ping"))

        penalties_raw = routing.get("cost_penalties") or {}
        if not isinstance(penalties_raw, Mapping):
            raise TypeError("routing.cost_penalties deve ser um mapa")
        cost_penalties = {str(k): float(v) for k, v in penalties_raw.items()}
        if any(value < 0 for value in cost_penalties.values()):
            raise ValueError("routing.cost_penalties não aceita valores negativos")

        profiles_raw = raw.get("profiles") or {}
        if not isinstance(profiles_raw, Mapping):
            raise TypeError("profiles deve ser um mapa")
        profiles: Dict[str, List[Dict[str, str]]] = {}
        for profile, targets in profiles_raw.items():
            if not isinstance(targets, (list, tuple)):
                raise TypeError(f"profiles.{profile} deve ser uma lista")
            parsed_targets: List[Dict[str, str]] = []
            for target in targets:
                if isinstance(target, str) and ":" in target:
                    provider, model = target.split(":", 1)
                elif isinstance(target, Mapping):
                    provider, model = target.get("provider"), target.get("model")
                else:
                    raise ValueError(f"profiles.{profile} contém target inválido")
                provider, model = str(provider or "").strip().lower(), str(model or "").strip()
                if not provider or not model:
                    raise ValueError(f"profiles.{profile} exige provider:model")
                if provider not in providers:
                    raise ValueError(
                        f"profiles.{profile} aponta para provedor desconhecido: {provider}"
                    )
                parsed_targets.append({"provider": provider, "model": model})
            profiles[str(profile).strip().lower()] = parsed_targets

        secrets_raw = raw.get("secrets") or {}
        if not isinstance(secrets_raw, Mapping):
            raise TypeError("secrets deve ser um mapa")
        accounts_raw = raw.get("accounts") or {}
        if not isinstance(accounts_raw, Mapping):
            raise TypeError("accounts deve ser um mapa")
        account_items = accounts_raw.get("items", accounts_raw.get("contas", [])) or []
        if not isinstance(account_items, (list, tuple)):
            raise TypeError("accounts.items deve ser uma lista")
        for index, account in enumerate(account_items):
            if not isinstance(account, Mapping):
                raise TypeError(f"accounts.items[{index}] deve ser um mapa")
            if any(field in account for field in ("api_key", "secret", "token")):
                raise ValueError("accounts guarda key_env, nunca segredo literal")
            auth_type = str(account.get("auth_type") or "").strip().lower()
            # `claude_cli` e `codex_cli`: quem autentica e o CLI da assinatura,
            # e o RobinBandit nunca toca na credencial.
            if auth_type and auth_type not in {"api_key", "codex_cli", "claude_cli"}:
                raise ValueError(
                    f"accounts.items[{index}].auth_type desconhecido: {auth_type}"
                )
            provider = str(account.get("provider") or "").strip().lower()
            if provider and provider not in providers:
                raise ValueError(
                    f"accounts.items[{index}] aponta para provedor desconhecido: {provider}"
                )
        return cls(
            version=version,
            agent_mode=agent_mode,
            idioma=idioma,
            providers=providers,
            weights=weights,
            last_resort=str(last_resort).strip().lower() if last_resort else None,
            strategy=strategy,
            chain_order=chain_order or list(providers),
            cost_penalties=cost_penalties,
            profiles=profiles,
            secrets=dict(secrets_raw),
            accounts={
                "contas": [dict(item) for item in account_items],
                "tiers": dict(accounts_raw.get("tiers") or {}),
            },
            erros=erros,
        )

    def provider_capabilities(self, key: str) -> set:
        """O que este provedor sabe fazer alem de texto (ex.: `vision`).

        Declarado no YAML, provedor a provedor. Sem declaracao, assume-se
        somente texto: e melhor deixar um capaz de fora do que mandar uma
        imagem para quem nao enxerga e receber um erro no meio do turno.
        """
        spec = self.providers.get(str(key).lower()) or {}
        bruto = spec.get("capabilities") or []
        if isinstance(bruto, str):
            bruto = [bruto]
        return {str(item).strip().lower() for item in bruto if str(item).strip()}

    def provider_models(self, key: str, role: Optional[str] = None) -> List[str]:
        """Lista canônica de modelos declarados para um provedor/papel.

        Papéis como ``planner`` permitem que um agente use uma ordem diferente
        sem voltar a espalhar listas de modelos pelo código do host.
        """
        spec = self.providers.get(str(key).lower()) or {}
        field_name = f"{str(role).strip().lower()}_models" if role else "models"
        raw = spec.get(field_name) or spec.get("models") or []
        if isinstance(raw, Mapping):
            return [str(model) for model in raw]
        return [str(model).strip() for model in raw if str(model).strip()]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RobinConfig":
        try:
            import yaml
        except ImportError:
            raise RuntimeError(
                "Leitura YAML exige o extra: pip install 'robinbandit[yaml]'"
            ) from None
        origem = Path(path)
        with origem.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream) or {}
        return cls.from_mapping(_com_override_do_usuario(_resolver_heranca(raw, origem)))


def load_config(path: str | Path) -> RobinConfig:
    return RobinConfig.from_yaml(path)
