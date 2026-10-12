"""A conexão valida o provedor sem expor credenciais aos painéis."""
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from robinbandit import RobinConfig
from robinbandit.accounts import openai_oauth as oauth
from robinbandit.accounts.oauth_store import transacao
from robinbandit.providers import build_provider, claude_code_provider


@pytest.fixture
def assinatura():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numeros = chave.public_key().public_numbers()
    jwks = {"keys": [{"kid": "teste", "kty": "RSA", "alg": "RS256",
                      "n": oauth._b64(numeros.n.to_bytes(256, "big")), "e": oauth._b64(numeros.e.to_bytes(3, "big"))}]}

    def token(**mudancas):
        claims = {"iss": oauth.ISSUER, "sub": "pessoa", "aud": "oaiapp_teste", "nonce": "teste",
                  "exp": time.time() + 3600, "iat": time.time(), "email": "pessoa@example.com", **mudancas}
        body = oauth._b64(json.dumps({"alg": "RS256", "kid": "teste"}).encode()) + "." + oauth._b64(json.dumps(claims).encode())
        return body + "." + oauth._b64(chave.sign(body.encode(), padding.PKCS1v15(), hashes.SHA256()))
    return token, jwks


@pytest.mark.parametrize("mudancas", [{"iss": "https://outro.example.com"}, {"aud": "outro"}, {"exp": 1},
                                      {"nonce": "outro"}, {"sub": ""}, {"iat": float("inf")}, {"azp": "outro"}])
def test_identidade_invalida_nao_passa(assinatura, mudancas):
    token, jwks = assinatura
    with pytest.raises(oauth.LoginInvalido):
        oauth.validar_id(token(**mudancas), "oaiapp_teste", "teste", jwks)


def test_assinatura_precisa_ser_valida(assinatura):
    token, jwks = assinatura
    valido = token()
    assert oauth.validar_id(valido, "oaiapp_teste", "teste", jwks)["sub"] == "pessoa"
    with pytest.raises(oauth.LoginInvalido):
        oauth.validar_id(valido.rsplit(".", 1)[0] + ".invalida", "oaiapp_teste", "teste", jwks)


def _tokens(id_token=""):
    return {"id_token": id_token, "access_token": "acesso-ficticio", "refresh_token": "renovacao-ficticia",
            "token_type": "Bearer", "scope": oauth.SCOPES, "expires_in": 3600}


@pytest.fixture
def provedor(monkeypatch, assinatura):
    token, jwks = assinatura
    metadata = {"issuer": oauth.ISSUER, "authorization_endpoint": oauth.ISSUER + "/authorize",
                "token_endpoint": oauth.ISSUER + "/token", "jwks_uri": oauth.ISSUER + "/jwks",
                "revocation_endpoint": oauth.ISSUER + "/revoke"}
    vistos = []
    def responder(url, *, data=None):
        vistos.append((url, data))
        if url.endswith("openid-configuration"):
            return metadata
        if url.endswith("jwks"):
            return jwks
        if url.endswith("token"):
            return _tokens(token(nonce=tentativa.nonce))
        return {}
    monkeypatch.setattr(oauth, "_json", responder)
    tentativa = oauth.Autorizacao("http://127.0.0.1:34567/auth/callback")
    return tentativa, vistos


def test_pkce_host_estavel_e_callback_exato(provedor):
    tentativa, _ = provedor
    params = parse_qs(urlsplit(tentativa.url()).query)
    assert params["client_id"] == ["dynamic_agent_client"]
    assert params["agent_name_hint"] == ["RobinBandit"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [tentativa.redirect_uri]
    outra = oauth.Autorizacao("http://127.0.0.1:34568/auth/callback")
    assert outra.host == tentativa.host
    assert outra.state != tentativa.state and outra.verifier != tentativa.verifier


def test_cadastro_guarda_identidade_e_nao_devolve_token(provedor):
    tentativa, vistos = provedor
    tid = tentativa.concluir({"state": tentativa.state, "code": "codigo-ficticio", "client_id": "oaiapp_teste"})
    troca = next(data for url, data in vistos if url.endswith("token"))
    assert troca["client_id"] == "oaiapp_teste"
    assert troca["code_verifier"] == tentativa.verifier
    assert troca["redirect_uri"] == tentativa.redirect_uri
    publico = oauth.situacao()
    assert publico["ativa"] == tid and publico["configurada"]
    assert "acesso-ficticio" not in json.dumps(publico)
    assert "renovacao-ficticia" not in json.dumps(publico)
    assert oauth.access_token() == "acesso-ficticio"


@pytest.mark.parametrize("params", [{"state": "outro"}, {"client_id": "dynamic_agent_client"}, {"client_id": ""}, {"error": "access_denied"}])
def test_callback_recusado_nao_troca_a_conta(provedor, params):
    tentativa, vistos = provedor
    with pytest.raises(oauth.LoginInvalido):
        tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste", **params})
    assert not oauth.situacao()["configurada"]
    assert not any(url.endswith("token") for url, _ in vistos)


def test_sem_permissao_de_plano_nao_salva(provedor, monkeypatch):
    tentativa, _ = provedor
    original = oauth._json
    def responder(url, **kwargs):
        resultado = original(url, **kwargs)
        return {**resultado, "scope": "openid email"} if url.endswith("token") else resultado
    monkeypatch.setattr(oauth, "_json", responder)
    with pytest.raises(oauth.LoginInvalido, match="plano ChatGPT"):
        tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"})
    assert not oauth.situacao()["configurada"]


def test_renovacao_grava_rotacao_e_saida_preserva_cadastro(provedor, monkeypatch):
    tentativa, _ = provedor
    tid = tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"})
    with transacao() as dados:
        dados["contas"][tid]["expires_at"] = 0
    original = oauth._json
    vistos = []
    def responder(url, *, data=None):
        vistos.append(data)
        resultado = original(url, data=data)
        if data and data.get("grant_type") == "refresh_token":
            return {**resultado, "access_token": "acesso-renovado", "refresh_token": "renovacao-nova"}
        return resultado
    monkeypatch.setattr(oauth, "_json", responder)
    assert oauth.access_token() == "acesso-renovado"
    assert oauth.access_token() == "acesso-renovado"
    assert len([d for d in vistos if d and d.get("grant_type") == "refresh_token"]) == 1
    assert oauth.sair(tid)["revogacao_confirmada"]
    assert not oauth.situacao()["configurada"]
    with transacao() as dados:
        registro = dados["contas"][tid]
        assert registro["client_id"] == "oaiapp_teste" and "refresh_token" not in registro


def test_cofre_corrompido_nao_e_sobrescrito(tmp_path, monkeypatch):
    from robinbandit.accounts import secrets
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "cofre.json"))
    caminho = tmp_path / "chatgpt.json"
    caminho.write_bytes(b"corrompido")
    with pytest.raises(secrets.CofreInvalido):
        oauth.situacao()
    assert caminho.read_bytes() == b"corrompido"


@pytest.mark.parametrize("conectado", [False, True])
def test_claude_consulta_login_em_vez_de_versao(monkeypatch, conectado):
    vistos = []
    monkeypatch.setattr(claude_code_provider, "resolve_claude_binary", lambda _: "claude-teste")
    def rodar(cmd, **kwargs):
        vistos.append((cmd, kwargs))
        return SimpleNamespace(returncode=0 if conectado else 1, stdout="dado que não deve aparecer")
    monkeypatch.setattr(claude_code_provider.subprocess, "run", rodar)
    claude_code_provider._STATUS_CACHE.clear()
    status = claude_code_provider.claude_code_auth_status()
    assert status.configured == conectado
    assert vistos[0][0] == ["claude-teste", "auth", "status"]
    assert vistos[0][1]["shell"] is False
    assert "dado" not in status.detail


def test_fabrica_direta_nao_depende_de_cli(provedor, monkeypatch):
    tentativa, _ = provedor
    cfg = RobinConfig.from_mapping({"providers": {"chatgpt": {"adapter": "chatgpt", "auth_type": "chatgpt_oauth", "models": ["modelo-teste"]}}})
    assert build_provider(cfg, "chatgpt") is None
    tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"})
    provider = build_provider(cfg, "chatgpt")
    assert provider.supports_tools and provider.models == ["modelo-teste"]


def test_rotas_nao_aceitam_inicio_remoto_ou_csrf(monkeypatch):
    from fastapi.testclient import TestClient
    from robinbandit.server import create_app
    cfg = RobinConfig.from_mapping({"providers": {"chatgpt": {"adapter": "chatgpt", "auth_type": "chatgpt_oauth"}}})
    app = create_app([], None, config=cfg)
    with TestClient(app) as cliente:
        assert cliente.post("/login/chatgpt", json={}).status_code == 403
        assert cliente.post("/login/chatgpt", json={}, headers={"X-RobinBandit-Login": "1", "Origin": "https://malicioso.example.com"}).status_code == 403
        assert cliente.post("/login/desconhecido", json={}, headers={"X-RobinBandit-Login": "1"}).status_code == 400
    from fastapi import HTTPException
    from starlette.requests import Request
    from robinbandit.server.logins import _local
    request = Request({"type": "http", "method": "POST", "scheme": "http", "path": "/login/chatgpt", "query_string": b"",
                       "server": ("127.0.0.1", 8000), "client": ("203.0.113.1", 1000),
                       "headers": [(b"host", b"127.0.0.1:8000"), (b"x-robinbandit-login", b"1")]})
    with pytest.raises(HTTPException) as recusado:
        _local(request)
    assert recusado.value.status_code == 403


def test_discovery_nao_redireciona_para_outro_host(monkeypatch):
    monkeypatch.setattr(oauth, "_json", lambda *a, **k: {
        "issuer": oauth.ISSUER, "authorization_endpoint": "https://malicioso.example.com/login"})
    with pytest.raises(oauth.LoginInvalido):
        oauth.discovery()


def test_contas_com_o_mesmo_email_continuam_separadas(provedor, monkeypatch, assinatura):
    primeira, _ = provedor
    primeira.concluir({"state": primeira.state, "code": "codigo", "client_id": "oaiapp_teste"})
    segunda = oauth.Autorizacao("http://127.0.0.1:34568/auth/callback")
    token, _ = assinatura
    original = oauth._json
    monkeypatch.setattr(oauth, "_json", lambda url, **kw: _tokens(token(aud="oaiapp_outro", nonce=segunda.nonce)) if url.endswith("token") else original(url, **kw))
    outra = segunda.concluir({"state": segunda.state, "code": "codigo", "client_id": "oaiapp_outro"})
    assert len(oauth.situacao()["contas"]) == 2
    assert oauth.situacao()["ativa"] == outra


def test_cancelamento_antes_de_gravar_nao_conecta(provedor):
    tentativa, _ = provedor
    with pytest.raises(oauth.LoginInvalido, match="cancelada"):
        tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"}, lambda: True)
    assert not oauth.situacao()["configurada"]


def test_reentrada_nao_aceita_outro_client_id(provedor):
    tentativa, _ = provedor
    conta = tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"})
    reentrada = oauth.Autorizacao("http://127.0.0.1:34568/auth/callback", conta)
    assert reentrada.client_id == "oaiapp_teste"
    assert "agent_name_hint" not in parse_qs(urlsplit(reentrada.url()).query)
    with pytest.raises(oauth.LoginInvalido):
        reentrada.concluir({"state": reentrada.state, "code": "codigo", "client_id": "oaiapp_outro"})


def test_callback_local_rejeita_state_errado_e_fecha_apos_login(provedor, assinatura, monkeypatch):
    import httpx
    from robinbandit.accounts.login import LoginChatGPT
    from urllib.parse import urlencode
    abertas = []
    monkeypatch.setattr("webbrowser.open", lambda url, **kwargs: abertas.append(url) or True)
    login = LoginChatGPT()
    token, _ = assinatura
    original = oauth._json
    monkeypatch.setattr(oauth, "_json", lambda url, **kw: _tokens(token(nonce=login.auth.nonce)) if url.endswith("token") else original(url, **kw))
    login.iniciar()
    try:
        with httpx.Client(trust_env=False) as cliente:
            assert cliente.get(login.auth.redirect_uri + "?state=outro", timeout=5).status_code == 400
            assert login.estado == "aguardando" and not oauth.situacao()["configurada"]
            query = urlencode({"state": login.auth.state, "code": "codigo", "client_id": "oaiapp_teste"})
            assert cliente.get(login.auth.redirect_uri + "?" + query, timeout=5).status_code == 200
        assert login.estado == "conectado"
        assert len(abertas) == 1
        assert urlsplit(abertas[0]).hostname == "auth.openai.com"
    finally:
        login.cancelar()


def test_consulta_da_tentativa_atualiza_provedores_uma_vez(monkeypatch):
    from robinbandit.accounts.login import Logins
    cfg = RobinConfig.from_mapping({"providers": {"chatgpt": {"adapter": "chatgpt", "auth_type": "chatgpt_oauth"}}})
    chamadas = []
    gestor = Logins(cfg, lambda: chamadas.append(True))
    tentativa = SimpleNamespace(publico=lambda: {"estado": "conectado", "configurada": True})
    gestor.tentativas["teste"] = ("chatgpt", tentativa, time.monotonic(), False)
    assert gestor.consultar("teste")["configurada"]
    assert gestor.consultar("teste")["configurada"]
    assert chamadas == [True]


def test_saida_sem_rede_limpa_tokens_sem_apagar_identidade(provedor, monkeypatch):
    tentativa, _ = provedor
    conta = tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"})
    def falhar(*args, **kwargs):
        raise oauth.LoginInvalido("Sem rede")
    monkeypatch.setattr(oauth, "discovery", falhar)
    assert oauth.sair(conta)["revogacao_confirmada"] is False
    assert not oauth.situacao()["configurada"]


def test_catalogo_oferece_so_um_chatgpt():
    from robinbandit.config import caminho_do_catalogo
    cfg = RobinConfig.from_yaml(caminho_do_catalogo())
    assert "chatgpt" not in cfg.providers and "chatgpt" not in cfg.chain_order
    spec = cfg.providers["chatgpt_codex"]
    assert spec["label"] == "ChatGPT" and spec["login_direto"] is True
    assert cfg.chain_order.count("chatgpt_codex") == 1


def test_conexao_direta_preserva_identidade_do_provedor(provedor, monkeypatch):
    from robinbandit.config import caminho_do_catalogo
    from robinbandit.accounts import catalogo_efetivo
    from robinbandit.providers import codex_provider
    from robinbandit.providers.chatgpt_provider import ChatGPTProvider
    tentativa, _ = provedor
    monkeypatch.setattr(codex_provider, "codex_auth_status", lambda *_: SimpleNamespace(configured=True))
    cfg = RobinConfig.from_yaml(caminho_do_catalogo())
    assert type(build_provider(cfg, "chatgpt_codex")).__name__ == "CodexProvider"
    tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"})
    provider = build_provider(cfg, "chatgpt_codex")
    assert isinstance(provider, ChatGPTProvider) and provider.name == "chatgpt_codex"
    conta = catalogo_efetivo(None, cfg).obter("chatgpt_codex")
    assert conta.para_painel()["origem"] == "chatgpt_oauth"
    assert conta.para_painel()["id"] == "chatgpt_codex"


def test_sair_do_direto_nao_assume_outra_conta_do_cli(provedor, monkeypatch):
    from robinbandit.config import caminho_do_catalogo
    from robinbandit.providers import codex_provider
    tentativa, _ = provedor
    conta = tentativa.concluir({"state": tentativa.state, "code": "codigo", "client_id": "oaiapp_teste"})
    cfg = RobinConfig.from_yaml(caminho_do_catalogo())
    monkeypatch.setattr(codex_provider, "codex_auth_status", lambda *_: SimpleNamespace(configured=True))
    oauth.sair(conta)
    assert oauth.metodo() == "direto"
    assert build_provider(cfg, "chatgpt_codex") is None
    oauth.usar_cli()
    assert type(build_provider(cfg, "chatgpt_codex")).__name__ == "CodexProvider"


def test_cli_ja_conectado_nao_abre_outro_login(monkeypatch):
    from robinbandit.accounts import login_cli
    monkeypatch.setattr(login_cli, "consultar", lambda *_: {"instalado": True, "configurada": True})
    def nao_abrir(*args, **kwargs):
        raise AssertionError("Não deve iniciar outro processo de login.")
    monkeypatch.setattr(login_cli.subprocess, "Popen", nao_abrir)
    tentativa = login_cli.LoginCLI("codex_cli", "codex")
    tentativa.iniciar()
    assert tentativa.publico()["estado"] == "conectado"


def test_mudar_para_cli_e_uma_escolha_explicita(monkeypatch):
    from robinbandit.config import caminho_do_catalogo
    from robinbandit.accounts.login import Logins
    from robinbandit.accounts import login_cli
    monkeypatch.setattr(login_cli, "consultar", lambda *_: {"instalado": True, "configurada": True})
    gestor = Logins(RobinConfig.from_yaml(caminho_do_catalogo()))
    tid = gestor.iniciar("chatgpt_codex", metodo="cli")["id"]
    assert gestor.consultar(tid)["configurada"]
    assert oauth.metodo() == "cli"
