"""Catálogo de contas nomeadas e tiers atendidos por cada conta."""
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..config import RobinConfig

# Permite consultar settings sem guardar valores secretos no catálogo.
_FONTE_DE_SEGREDO: Any = None
_FONTE_DE_CONFIG: Optional["RobinConfig"] = None


def vincular_fonte(settings) -> None:
    """Aponta de onde as contas leem o segredo (o settings da app)."""
    global _FONTE_DE_SEGREDO
    _FONTE_DE_SEGREDO = settings


def vincular_config(config: "RobinConfig") -> None:
    """Vincula o catálogo YAML que descreve contas e provedores conhecidos."""
    global _FONTE_DE_CONFIG
    _FONTE_DE_CONFIG = config


def _ler_do_ambiente(nome: str) -> str:
    """Só o que o deploy configurou: os.environ e o `.env` via settings."""
    valor = os.environ.get(nome, "")
    if not valor and _FONTE_DE_SEGREDO is not None:
        valor = getattr(_FONTE_DE_SEGREDO, nome, "") or ""
    return str(valor).strip()


def _ler_segredo(nome: str) -> str:
    """Lê do cofre primeiro, depois do ambiente/settings."""
    from . import secrets
    return secrets.ler(nome) or _ler_do_ambiente(nome)


@dataclass(frozen=True)
class Conta:
    """Uma conta de provedor. `key_env` é o NOME da variável, não a chave."""
    id: str
    provider: str
    key_env: str = ""
    models: List[str] = field(default_factory=list)
    label: str = ""
    paga: bool = False
    # Alguns provedores (ChatGPT Codex, Claude Code) delegam OAuth ao cliente
    # oficial e portanto não possuem API key que o Robin deva guardar.
    auth_type: str = ""
    auth_binary: str = "codex"

    @property
    def por_cli(self) -> bool:
        """Quem autentica é o CLI oficial, e a sessão é dele."""
        return self.auth_type.endswith("_cli")

    def _status_do_cli(self):
        if self.auth_type == "codex_cli":
            from ..providers.codex_provider import codex_auth_status

            return codex_auth_status(self.auth_binary)
        from ..providers.claude_code_provider import claude_code_auth_status

        # `auth_binary` padrão é "codex"; Claude sem binary usa "claude".
        binario = self.auth_binary if self.auth_binary not in ("", "codex") else "claude"
        return claude_code_auth_status(binario)

    @property
    def configurada(self) -> bool:
        if self.por_cli:
            return bool(self._status_do_cli().configured)
        return bool(self.key_env and _ler_segredo(self.key_env))

    def resolver_chave(self) -> str:
        """Lê o segredo apenas na hora do uso."""
        return _ler_segredo(self.key_env) if self.key_env else ""

    def para_painel(self) -> Dict[str, Any]:
        """Visão segura para o painel, sem retornar valores secretos."""
        from . import secrets
        if self.por_cli:
            status = self._status_do_cli()
            situacao = {
                "configurada": bool(status.configured),
                "origem": self.auth_type if status.configured else "ausente",
                "dica": "",
                "detalhe": str(getattr(status, "detail", "") or ""),
            }
        else:
            situacao = secrets.situacao(self.key_env, _ler_do_ambiente(self.key_env))
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label or self.id,
            "key_env": self.key_env,      # o NOME ajuda a debugar config
            "auth_type": self.auth_type,
            "por_cli": self.por_cli,
            "models": list(self.models),
            "paga": self.paga,
            **situacao,                   # configurada, origem, dica
        }


class CatalogoDeContas:
    """Contas declaradas + qual delas serve cada tier."""

    def __init__(self, contas: Optional[List[Conta]] = None,
                 tiers: Optional[Dict[str, str]] = None):
        self._contas: Dict[str, Conta] = {c.id: c for c in (contas or [])}
        # tier -> id da conta. Ex.: {"ultra_max": "openrouter-paga"}
        self._tiers: Dict[str, str] = dict(tiers or {})

    # --- leitura ---

    def listar(self, apenas_configuradas: bool = False) -> List[Conta]:
        contas = list(self._contas.values())
        return [c for c in contas if c.configurada] if apenas_configuradas else contas

    def obter(self, conta_id: str) -> Optional[Conta]:
        return self._contas.get(str(conta_id or "").strip())

    def do_provedor(self, provider: str) -> List[Conta]:
        p = str(provider or "").strip().lower()
        return [c for c in self._contas.values() if c.provider == p]

    def tiers_declarados(self) -> Dict[str, str]:
        """tier -> id, cru. Serve pra mesclar camadas antes de validar o id."""
        return dict(self._tiers)

    def conta_do_tier(self, tier: str) -> Optional[Conta]:
        """Qual conta serve este tier ('ultra', 'ultra_max'). None = não
        declarado, e o caller mantém o comportamento antigo por env."""
        conta_id = self._tiers.get(str(tier or "").strip().lower())
        return self.obter(conta_id) if conta_id else None

    # --- escrita (config, não segredo) ---

    def registrar(self, conta: Conta) -> None:
        self._contas[conta.id] = conta

    def apontar_tier(self, tier: str, conta_id: str) -> None:
        """Escolhe a conta de um tier e valida o alvo."""
        alvo = str(conta_id or "").strip()
        if alvo not in self._contas:
            disponiveis = ", ".join(sorted(self._contas)) or "nenhuma"
            raise ValueError(
                f"conta '{alvo}' não existe no catálogo. Disponíveis: {disponiveis}."
            )
        self._tiers[str(tier).strip().lower()] = alvo

    def para_painel(self) -> Dict[str, Any]:
        return {
            "contas": [c.para_painel() for c in self.listar()],
            "tiers": dict(self._tiers),
        }


def carregar_catalogo(bruto: Any) -> CatalogoDeContas:
    """Monta o catálogo a partir de config."""
    if not bruto:
        return CatalogoDeContas()
    if isinstance(bruto, dict):
        itens, tiers = bruto.get("contas") or [], bruto.get("tiers") or {}
    elif isinstance(bruto, list):
        itens, tiers = bruto, {}
    else:
        raise ValueError("catálogo de contas deve ser uma lista ou um objeto com 'contas'.")

    contas: List[Conta] = []
    vistos = set()
    for i, item in enumerate(itens):
        if not isinstance(item, dict):
            raise ValueError(f"conta #{i + 1} não é um objeto.")
        cid = str(item.get("id") or "").strip()
        provider = str(item.get("provider") or "").strip().lower()
        key_env = str(item.get("key_env") or "").strip()
        auth_type = str(item.get("auth_type") or "").strip().lower()
        faltando = [n for n, v in (("id", cid), ("provider", provider)) if not v]
        if not key_env and not auth_type:
            faltando.append("key_env ou auth_type")
        if faltando:
            raise ValueError(f"conta #{i + 1} sem {', '.join(faltando)}.")
        if cid in vistos:
            raise ValueError(f"conta '{cid}' declarada duas vezes.")
        vistos.add(cid)
        contas.append(Conta(
            id=cid, provider=provider, key_env=key_env,
            models=[str(m).strip() for m in (item.get("models") or []) if str(m).strip()],
            label=str(item.get("label") or "").strip(),
            paga=bool(item.get("paga")),
            auth_type=auth_type,
            auth_binary=str(item.get("auth_binary") or "codex").strip(),
        ))

    catalogo = CatalogoDeContas(contas)
    for tier, conta_id in (tiers or {}).items():
        catalogo.apontar_tier(tier, conta_id)   # valida o id
    return catalogo


def catalogo_das_settings(settings) -> CatalogoDeContas:
    """Catálogo vindo de `SENTURY_ACCOUNTS` em JSON."""
    import json

    bruto = (getattr(settings, "SENTURY_ACCOUNTS", "") or "").strip()
    if not bruto:
        return CatalogoDeContas()
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SENTURY_ACCOUNTS não é JSON válido: {exc}") from exc
    return carregar_catalogo(dados)


def _config_efetiva(
    config: Optional["RobinConfig"] = None,
    settings: Any = None,
) -> "RobinConfig":
    efetiva = config or _FONTE_DE_CONFIG
    if efetiva is None and settings is not None:
        path = str(
            getattr(settings, "ROBINBANDIT_CONFIG", "")
            or getattr(settings, "SENTURY_ROBINBANDIT_CONFIG", "")
            or ""
        ).strip()
        if path:
            from ..config import RobinConfig
            efetiva = RobinConfig.from_yaml(path)
    if efetiva is None:
        raise ValueError("catálogo de contas exige um RobinConfig vinculado")
    return efetiva


def _valor_de_config(settings: Any, env_name: str) -> str:
    valor = os.environ.get(str(env_name or ""), "")
    if not valor and settings is not None:
        valor = getattr(settings, str(env_name or ""), "") or ""
    return str(valor).strip()


def descobrir_do_ambiente(
    settings,
    config: Optional["RobinConfig"] = None,
) -> CatalogoDeContas:  # noqa: D401
    """Monta o catálogo a partir do ambiente/settings já configurados."""
    efetiva = _config_efetiva(config, settings)
    vincular_fonte(settings)
    vincular_config(efetiva)
    contas: List[Conta] = []
    tiers: Dict[str, str] = {}
    for provider, spec in efetiva.providers.items():
        if str(spec.get("adapter") or "").lower() == "fallback":
            continue
        if spec.get("enabled") is False:
            continue
        env = str(spec.get("api_key_env") or "").strip()
        auth_type = str(spec.get("auth_type") or "").strip().lower()
        if not env and not auth_type:
            continue
        fallback_env = str(spec.get("api_key_fallback_env") or "").strip()
        if fallback_env and not _ler_segredo(env):
            env = fallback_env
        models_env = str(spec.get("models_env") or "").strip()
        modelos = [
            item.strip() for item in _valor_de_config(settings, models_env).split(",")
            if item.strip()
        ] or efetiva.provider_models(provider)
        contas.append(Conta(
            id=provider,
            provider=str(spec.get("account_provider") or provider).strip().lower(),
            key_env=env,
            models=modelos,
            label=str(spec.get("label") or provider),
            paga=bool(spec.get("paid_account")) or str(spec.get("cost_class") or "") in {
                "paid", "credits",
            },
            auth_type=auth_type,
            auth_binary=(
                _valor_de_config(settings, str(spec.get("binary_env") or ""))
                or str(spec.get("binary") or "codex").strip()
            ),
        ))
        selection_tier = str(spec.get("selection_tier") or "").strip().lower()
        if selection_tier:
            tiers[selection_tier] = provider

    catalogo = CatalogoDeContas(contas, tiers)
    return catalogo


def variaveis_conhecidas(
    settings,
    config: Optional["RobinConfig"] = None,
) -> List[str]:
    """Lista branca de variáveis que o cofre aceita gravar."""
    efetiva = _config_efetiva(config, settings)
    nomes = {c.key_env for c in catalogo_efetivo(settings, efetiva).listar()}
    for spec in efetiva.providers.values():
        nomes.update({
            str(spec.get("api_key_env") or "").strip(),
            str(spec.get("api_key_fallback_env") or "").strip(),
        })
    return sorted(n for n in nomes if n)


def catalogo_efetivo(
    settings,
    config: Optional["RobinConfig"] = None,
) -> CatalogoDeContas:
    """Catálogo efetivo: ambiente como base, painel por cima."""
    catalogo = descobrir_do_ambiente(settings, config)

    # `SENTURY_ACCOUNTS` continua valendo para deploys já configurados.
    efetiva = _config_efetiva(config, settings)
    camadas = [
        carregar_catalogo(efetiva.accounts),
        catalogo_das_settings(settings),
        _catalogo_do_painel(),
    ]

    # Mescla contas antes de validar tiers.
    for camada in camadas:
        for conta in camada.listar():
            catalogo.registrar(conta)
    for camada in camadas:
        for tier, conta_id in camada.tiers_declarados().items():
            if catalogo.obter(conta_id) is not None:
                catalogo.apontar_tier(tier, conta_id)
    return catalogo


def _catalogo_do_painel() -> CatalogoDeContas:
    """Contas e tiers gravados pelo painel."""
    try:
        from . import account_config
        dados = account_config.carregar()
        catalogo = carregar_catalogo({"contas": dados.get("contas") or []})
        catalogo._tiers = dict(dados.get("tiers") or {})   # validado no merge
        return catalogo
    except Exception:
        return CatalogoDeContas()
