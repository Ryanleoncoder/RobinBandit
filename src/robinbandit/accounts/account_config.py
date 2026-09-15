"""Persistência local de contas e preferências do painel.

Segredos ficam em ``secrets.py``. Aqui entram apenas configuração declarativa:
contas, fila do Reforçado, tiers, modelos, idioma e estratégia.
"""
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
_PATH_ENV = "ROBINBANDIT_ACCOUNTS_PATH"
_PREFERENCES_PATH_ENV = "ROBINBANDIT_PREFERENCES_PATH"

_CAMPOS_DE_CONTA = ("contas", "tiers", "reforcado")
_CAMPOS_DE_PREFERENCIA = (
    "provedores", "modelos", "modelos_por_papel", "estrategia", "cadeia", "idioma",
)

# Caminho legado usado antes de ``ROBINBANDIT_HOME``.
_LEGADO = Path(".sentury") / "contas.json"


def _padrao() -> Path:
    """Retorna o arquivo de contas da instalação local."""
    home = os.environ.get("ROBINBANDIT_HOME") or str(Path.home() / ".robinbandit")
    novo = Path(home) / "contas.json"
    legado = Path.cwd() / _LEGADO
    if legado.is_file() and not novo.exists():
        # Migra sem remover o arquivo antigo.
        try:
            novo.parent.mkdir(parents=True, exist_ok=True)
            novo.write_text(legado.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            return legado
    return novo


def configure(metadata: Optional[Dict[str, Any]] = None) -> None:
    """Aplica a referência de caminho declarada no YAML."""
    global _PATH_ENV
    configured = str((metadata or {}).get("account_config_path_env") or "").strip()
    _PATH_ENV = configured or "ROBINBANDIT_ACCOUNTS_PATH"


def caminho_da_config() -> Path:
    bruto = (os.environ.get(_PATH_ENV)
             or os.environ.get("ROBINBANDIT_ACCOUNTS_PATH")
             or os.environ.get("SENTURY_ACCOUNTS_PATH") or "").strip()
    return Path(bruto).expanduser() if bruto else _padrao()


def caminho_das_preferencias() -> Path:
    """Arquivo das escolhas feitas no painel."""
    bruto = str(os.environ.get(_PREFERENCES_PATH_ENV) or "").strip()
    if bruto:
        return Path(bruto).expanduser()
    caminho_contas = caminho_da_config()
    return caminho_contas.with_name("preferencias.json")


def _ler_json(caminho: Path) -> Dict[str, Any]:
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_json(caminho: Path, dados: Dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(
        f".{caminho.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(caminho)


def carregar() -> Dict[str, Any]:
    vazio = {
        "contas": [], "tiers": {}, "reforcado": [], "provedores": {}, "modelos": {},
        "modelos_por_papel": {},
        "estrategia": "", "cadeia": [],
        "idioma": "",
    }
    caminho = caminho_da_config()
    contas = _ler_json(caminho)
    preferencias = _ler_json(caminho_das_preferencias())

    # Grava o destino antes de limpar o formato antigo.
    campos_legados = [
        campo for campo in _CAMPOS_DE_PREFERENCIA if campo in contas
    ]
    legadas = {
        campo: contas[campo]
        for campo in campos_legados if campo not in preferencias
    }
    if campos_legados:
        preferencias.update(legadas)
        try:
            _gravar_json(caminho_das_preferencias(), preferencias)
            limpas = {campo: contas.get(campo) for campo in _CAMPOS_DE_CONTA if campo in contas}
            _gravar_json(caminho, limpas)
            contas = limpas
        except OSError:
            # Continua lendo a configuração antiga nesta execução.
            preferencias.update(legadas)

    dados = {**contas, **preferencias}
    return {
        "contas": [c for c in (dados.get("contas") or []) if isinstance(c, dict)],
        "tiers": {str(k): str(v) for k, v in (dados.get("tiers") or {}).items()},
        # Instalações antigas usavam apenas ``tiers.ultra`` como fallback.
        "reforcado": [
            str(conta).strip()
            for conta in (dados.get("reforcado") or [])
            if str(conta).strip()
        ],
        # provedor -> tier de roteamento (1 preferencial ... 3 ultimo recurso).
        "provedores": {str(k): v for k, v in (dados.get("provedores") or {}).items()},
        # provedor -> modelos escolhidos no catalogo vivo.
        "modelos": {
            str(k): [str(modelo).strip() for modelo in v if str(modelo).strip()]
            for k, v in (dados.get("modelos") or {}).items()
            if isinstance(v, list)
        },
        # Texto continua em "modelos" para manter compatibilidade.
        "modelos_por_papel": {
            str(papel): {
                str(k): [str(m).strip() for m in v if str(m).strip()]
                for k, v in (mapa or {}).items()
                if isinstance(v, list)
            }
            for papel, mapa in (dados.get("modelos_por_papel") or {}).items()
            if isinstance(mapa, dict)
        },
        "estrategia": str(dados.get("estrategia") or ""),
        "cadeia": [
            str(nome).strip().lower()
            for nome in (dados.get("cadeia") or [])
            if str(nome).strip()
        ],
        "idioma": str(dados.get("idioma") or "").strip().lower(),
    }


def _gravar(dados: Dict[str, Any]) -> None:
    contas = {campo: dados.get(campo) for campo in _CAMPOS_DE_CONTA}
    preferencias = {campo: dados.get(campo) for campo in _CAMPOS_DE_PREFERENCIA}
    _gravar_json(caminho_da_config(), contas)
    _gravar_json(caminho_das_preferencias(), preferencias)


_CAMPOS = ("id", "provider", "key_env", "label", "models", "paga")


def salvar_conta(item: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou atualiza uma conta declarada. Devolve a conta salva."""
    cid = str(item.get("id") or "").strip()
    provider = str(item.get("provider") or "").strip().lower()
    key_env = str(item.get("key_env") or "").strip().upper()
    faltando = [n for n, v in (("id", cid), ("provider", provider), ("key_env", key_env)) if not v]
    if faltando:
        raise ValueError(f"conta sem {', '.join(faltando)}.")
    if not key_env.replace("_", "").isalnum():
        # O nome entra na lista branca do cofre.
        raise ValueError("key_env deve ter só letras, números e underscore (ex.: GROQ_API_KEY_2).")

    with _LOCK:
        dados = carregar()
        nova = {
            "id": cid,
            "provider": provider,
            "key_env": key_env,
            "label": str(item.get("label") or "").strip(),
            "models": [str(m).strip() for m in (item.get("models") or []) if str(m).strip()],
            "paga": bool(item.get("paga")),
        }
        dados["contas"] = [c for c in dados["contas"] if str(c.get("id")) != cid] + [nova]
        _gravar(dados)
        return nova


def remover_conta(conta_id: str) -> bool:
    """Remove apenas a conta declarada no painel."""
    cid = str(conta_id or "").strip()
    with _LOCK:
        dados = carregar()
        antes = len(dados["contas"])
        dados["contas"] = [c for c in dados["contas"] if str(c.get("id")) != cid]
        # Remove referências órfãs.
        dados["tiers"] = {t: v for t, v in dados["tiers"].items() if v != cid}
        dados["reforcado"] = [conta for conta in dados["reforcado"] if conta != cid]
        if len(dados["contas"]) == antes:
            return False
        _gravar(dados)
        return True


def apontar_tier(tier: str, conta_id: str, ids_validos: Optional[List[str]] = None) -> None:
    """Escolhe qual conta serve um tier de seleção."""
    t = str(tier or "").strip().lower()
    alvo = str(conta_id or "").strip()
    if t not in ("ultra", "ultra_max"):
        raise ValueError(f"tier '{t}' não existe. Use 'ultra' ou 'ultra_max'.")
    if ids_validos is not None and alvo and alvo not in ids_validos:
        raise ValueError(f"conta '{alvo}' não existe. Disponíveis: {', '.join(sorted(ids_validos))}.")
    with _LOCK:
        dados = carregar()
        if alvo:
            dados["tiers"][t] = alvo
        else:
            dados["tiers"].pop(t, None)   # string vazia = voltar ao padrão do ambiente
        _gravar(dados)


def ordem_do_reforcado() -> List[str]:
    """Contas preferidas, na ordem. Vazio mantém o padrão legado do YAML."""
    return list(carregar().get("reforcado") or [])


def definir_ordem_do_reforcado(
    contas: List[str], ids_validos: Optional[List[str]] = None,
) -> List[str]:
    """Grava a fila do Reforçado sem limitar por preço ou autenticação."""
    ordem: List[str] = []
    for conta in contas or []:
        cid = str(conta or "").strip()
        if cid and cid not in ordem:
            ordem.append(cid)
    if ids_validos is not None:
        invalidas = [cid for cid in ordem if cid not in ids_validos]
        if invalidas:
            raise ValueError(
                f"conta '{invalidas[0]}' não existe. "
                f"Disponíveis: {', '.join(sorted(ids_validos))}."
            )
    with _LOCK:
        dados = carregar()
        dados["reforcado"] = ordem
        _gravar(dados)
    return ordem


# Cache por mtime evita I/O no caminho quente e reflete mudanças do painel.
_CACHE_TIERS: Dict[str, Any] = {"mtime": None, "valor": {}}
_CACHE_MODELOS: Dict[str, Any] = {"mtime": None, "valor": {}}


def overrides_de_tier() -> Dict[str, int]:
    """provedor -> tier escolhido no painel. Vazio = usa o tier do YAML."""
    caminho = caminho_das_preferencias()
    try:
        mtime = caminho.stat().st_mtime
    except OSError:
        _CACHE_TIERS.update(mtime=None, valor={})
        return {}
    if _CACHE_TIERS["mtime"] != mtime:
        bruto = carregar().get("provedores") or {}
        limpo = {}
        for k, v in bruto.items():
            try:
                limpo[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        _CACHE_TIERS.update(mtime=mtime, valor=limpo)
    return dict(_CACHE_TIERS["valor"])


def definir_tier_de_provedor(provider: str, tier: Any) -> None:
    """Move um provedor de tier; vazio devolve ao padrão do YAML."""
    chave = str(provider or "").strip().lower()
    if not chave:
        raise ValueError("provedor vazio.")
    with _LOCK:
        dados = carregar()
        if tier in (None, ""):
            dados["provedores"].pop(chave, None)
        else:
            try:
                n = int(tier)
            except (TypeError, ValueError):
                raise ValueError(f"tier '{tier}' não é um número.") from None
            if n not in (1, 2, 3):
                raise ValueError(f"tier {n} não existe. Use 1, 2 ou 3.")
            dados["provedores"][chave] = n
        _gravar(dados)


def overrides_de_modelos() -> Dict[str, List[str]]:
    """Modelos escolhidos pelo usuario por provedor; vazio usa ambiente/YAML."""
    caminho = caminho_das_preferencias()
    try:
        mtime = caminho.stat().st_mtime
    except OSError:
        _CACHE_MODELOS.update(mtime=None, valor={})
        return {}
    if _CACHE_MODELOS["mtime"] != mtime:
        bruto = carregar().get("modelos") or {}
        limpo = {
            str(provider).strip().lower(): [
                str(modelo).strip() for modelo in modelos if str(modelo).strip()
            ]
            for provider, modelos in bruto.items()
            if isinstance(modelos, list)
        }
        _CACHE_MODELOS.update(mtime=mtime, valor=limpo)
    return {provider: list(modelos) for provider, modelos in _CACHE_MODELOS["valor"].items()}


def modelos_por_papel(papel: str = "texto") -> Dict[str, List[str]]:
    """Modelos escolhidos por papel. Texto usa a chave historica."""
    alvo = str(papel or "texto").strip().lower()
    if alvo in ("", "texto"):
        return overrides_de_modelos()
    bruto = (carregar().get("modelos_por_papel") or {}).get(alvo) or {}
    return {str(k).strip().lower(): list(v) for k, v in bruto.items()}


def papeis_configurados() -> Dict[str, Dict[str, List[str]]]:
    """Tudo que ja foi escolhido, por papel. Texto entra junto."""
    dados = carregar()
    saida = {"texto": overrides_de_modelos()}
    for papel, mapa in (dados.get("modelos_por_papel") or {}).items():
        saida[str(papel)] = {str(k): list(v) for k, v in mapa.items()}
    return saida


def definir_modelos_de_provedor(provider: str, modelos: List[str], papel: str = "texto") -> List[str]:
    """Persiste a ordem de fallback escolhida para um provedor.

    Lista vazia remove o override e volta para ambiente/YAML.
    """
    chave = str(provider or "").strip().lower()
    if not chave:
        raise ValueError("provedor vazio.")
    alvo = str(papel or "texto").strip().lower() or "texto"
    normalizados: List[str] = []
    for modelo in modelos or []:
        item = str(modelo or "").strip()
        if item and item not in normalizados:
            normalizados.append(item)
    with _LOCK:
        dados = carregar()
        if alvo == "texto":
            destino = dados.setdefault("modelos", {})
        else:
            destino = dados.setdefault("modelos_por_papel", {}).setdefault(alvo, {})
        if normalizados:
            destino[chave] = normalizados
        else:
            destino.pop(chave, None)
        _gravar(dados)
        _CACHE_MODELOS.update(mtime=None, valor={})
    return normalizados


# Estratégia de roteamento escolhida no painel.

ESTRATEGIAS = ("adaptive", "tier", "fixed", "round_robin")


def estrategia(padrao: str = "adaptive") -> str:
    """Estratégia ativa: adaptive, tier, fixed ou round_robin."""
    escolhida = str(carregar().get("estrategia") or "").strip().lower()
    return escolhida if escolhida in ESTRATEGIAS else str(padrao or "adaptive")


def definir_estrategia(valor: str) -> str:
    escolhida = str(valor or "").strip().lower()
    if escolhida not in ESTRATEGIAS:
        raise ValueError(f"estrategia deve ser uma de {', '.join(ESTRATEGIAS)}")
    with _LOCK:
        dados = carregar()
        dados["estrategia"] = escolhida
        _gravar(dados)
    return escolhida


def cadeia() -> List[str]:
    """Quem entra na cadeia, na ordem escolhida. Vazio = a do YAML."""
    bruto = carregar().get("cadeia")
    if not isinstance(bruto, list):
        return []
    return [str(item).strip().lower() for item in bruto if str(item).strip()]


def definir_cadeia(nomes: List[str], validos: Optional[List[str]] = None) -> List[str]:
    """Troca quem entra na cadeia e em que ordem."""
    permitidos = {str(n).strip().lower() for n in (validos or [])}
    limpa: List[str] = []
    for nome in nomes or []:
        chave = str(nome or "").strip().lower()
        if not chave or chave in limpa:
            continue
        if permitidos and chave not in permitidos:
            raise ValueError(f"provedor '{chave}' nao existe no catalogo")
        limpa.append(chave)
    with _LOCK:
        dados = carregar()
        dados["cadeia"] = limpa
        _gravar(dados)
    return limpa
