"""Contrato OAuth público do ChatGPT com PKCE e identidade validada."""
import base64
import hashlib
import json
import math
import secrets
import time
import uuid
from urllib.parse import urlencode, urlsplit

from .oauth_store import transacao

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


class LoginInvalido(ValueError):
    tipo = "auth"


def _json(url, *, data=None):
    import httpx
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as cliente:
            resposta = cliente.get(url) if data is None else cliente.post(url, data=data)
            if resposta.status_code >= 300:
                raise LoginInvalido("O provedor recusou a autorização. Conecte novamente.")
            valor = resposta.json() if resposta.content else {}
            if not isinstance(valor, dict):
                raise ValueError()
            return valor
    except LoginInvalido:
        raise
    except Exception:
        raise LoginInvalido("Não foi possível consultar a autorização no provedor.") from None


def discovery():
    dados = _json(ISSUER + "/.well-known/openid-configuration")
    if dados.get("issuer") != ISSUER:
        raise LoginInvalido("Emissor de autorização inesperado.")
    for campo in ("authorization_endpoint", "token_endpoint", "jwks_uri", "revocation_endpoint"):
        url = urlsplit(str(dados.get(campo) or ""))
        if url.scheme != "https" or url.netloc != "auth.openai.com" or url.fragment:
            raise LoginInvalido("Endereço de autorização inesperado.")
    return dados


def _b64(valor):
    return base64.urlsafe_b64encode(valor).decode("ascii").rstrip("=")


def _decodificar(valor):
    return base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))


def validar_id(token, client_id, nonce, jwks):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    try:
        cabecalho, conteudo, assinatura = token.split(".")
        header = json.loads(_decodificar(cabecalho))
        if header.get("alg") != "RS256" or not header.get("kid") or header.get("crit"):
            raise ValueError()
        chaves = [k for k in jwks["keys"] if k.get("kid") == header["kid"]
                  and k.get("kty") == "RSA" and k.get("use", "sig") == "sig"
                  and k.get("alg", "RS256") == "RS256"]
        if len(chaves) != 1:
            raise ValueError()
        chave = chaves[0]
        publica = rsa.RSAPublicNumbers(
            int.from_bytes(_decodificar(chave["e"]), "big"),
            int.from_bytes(_decodificar(chave["n"]), "big"),
        ).public_key()
        publica.verify(_decodificar(assinatura), (cabecalho + "." + conteudo).encode("ascii"),
                       padding.PKCS1v15(), hashes.SHA256())
        claims = json.loads(_decodificar(conteudo))
        agora = time.time()
        aud = claims.get("aud")
        if (claims.get("iss") != ISSUER or not isinstance(claims.get("sub"), str)
                or not claims["sub"] or client_id not in (aud if isinstance(aud, list) else [aud])
                or (isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != client_id)
                or (claims.get("azp") and claims["azp"] != client_id)):
            raise ValueError()
        for campo in ("exp", "iat"):
            valor = claims.get(campo)
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
                raise ValueError()
        if claims["exp"] <= agora or claims["iat"] > agora + 60 or claims.get("nbf", 0) > agora + 60:
            raise ValueError()
        if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError()
        return claims
    except Exception:
        raise LoginInvalido("A identidade devolvida pelo provedor não passou na validação.") from None


def _credenciais(tokens, anterior=None):
    scopes = str(tokens.get("scope", " ".join((anterior or {}).get("scopes", [])))).split()
    duracao = tokens.get("expires_in")
    if (tokens.get("token_type", "").lower() != "bearer" or not tokens.get("access_token")
            or "chatgpt.tokens.use.direct" not in scopes or "resource.invoke" not in scopes
            or isinstance(duracao, bool) or not isinstance(duracao, (int, float))
            or not math.isfinite(duracao) or duracao <= 0):
        raise LoginInvalido("A conta não autorizou o uso do plano ChatGPT neste aplicativo.")
    refresh = tokens.get("refresh_token") or (anterior or {}).get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise LoginInvalido("A autorização não permite renovar a conexão.")
    return {"access_token": tokens["access_token"], "refresh_token": refresh,
            "id_token": tokens.get("id_token") or (anterior or {}).get("id_token", ""),
            "scopes": scopes, "expires_at": time.time() + duracao}


class Autorizacao:
    def __init__(self, redirect_uri, conta=""):
        self.metadata = discovery()
        self.state, self.nonce, self.verifier = (secrets.token_urlsafe(32) for _ in range(3))
        self.redirect_uri = redirect_uri
        with transacao() as dados:
            self.host = dados.setdefault("host", "urn:uuid:" + str(uuid.uuid4()))
            self.anterior = dict(dados["contas"].get(conta) or {})
        if conta and not self.anterior:
            raise LoginInvalido("Conta não encontrada.")
        self.client_id = self.anterior.get("client_id") or "dynamic_agent_client"

    def url(self):
        params = {"client_id": self.client_id, "ext_agent_host_id": self.host,
                  "response_type": "code", "redirect_uri": self.redirect_uri, "scope": SCOPES,
                  "resource": RESOURCE, "state": self.state, "nonce": self.nonce,
                  "code_challenge_method": "S256", "code_challenge": _b64(hashlib.sha256(self.verifier.encode()).digest())}
        if self.client_id == "dynamic_agent_client":
            params["agent_name_hint"] = "RobinBandit"
        elif self.anterior.get("id_token"):
            params["id_token_hint"] = self.anterior["id_token"]
        return self.metadata["authorization_endpoint"] + "?" + urlencode(params)

    def concluir(self, params, cancelado=lambda: False):
        if not secrets.compare_digest(str(params.get("state", "")), self.state):
            raise LoginInvalido("A resposta não pertence a esta tentativa de login.")
        if params.get("error"):
            raise LoginInvalido("O login foi recusado ou cancelado no provedor.")
        client_id = params.get("client_id") or (self.client_id if self.anterior else "")
        if (not isinstance(client_id, str) or not client_id.startswith("oaiapp_")
                or (self.anterior and client_id != self.client_id) or not params.get("code")):
            raise LoginInvalido("O cadastro não devolveu uma identificação válida.")
        tokens = _json(self.metadata["token_endpoint"], data={
            "grant_type": "authorization_code", "client_id": client_id, "code": params["code"],
            "code_verifier": self.verifier, "redirect_uri": self.redirect_uri, "resource": RESOURCE})
        claims = validar_id(tokens.get("id_token", ""), client_id, self.nonce, _json(self.metadata["jwks_uri"]))
        if self.anterior and claims["sub"] != self.anterior["subject"]:
            raise LoginInvalido("O login pertence a outra conta. Adicione-a separadamente.")
        cred = _credenciais(tokens)
        identidade = hashlib.sha256((ISSUER + client_id + claims["sub"]).encode()).hexdigest()
        with transacao() as dados:
            if cancelado():
                raise LoginInvalido("A tentativa de login foi cancelada.")
            cred.update({"client_id": client_id, "subject": claims["sub"], "issuer": ISSUER,
                         "email": str(claims.get("email") or ""),
                         "label": self.anterior.get("label") or "ChatGPT " + str(len(dados["contas"]) + 1)})
            dados["contas"][identidade] = cred
            dados["ativa"] = identidade
            dados["metodo"] = "direto"
        return identidade


def situacao():
    with transacao() as dados:
        ativa = dados.get("ativa", "")
        contas = [{"id": k, "label": v["label"], "email": v.get("email", ""),
                   "configurada": bool(v.get("refresh_token"))} for k, v in dados["contas"].items()]
        return {"configurada": any(c["id"] == ativa and c["configurada"] for c in contas),
                "ativa": ativa, "contas": contas}


def selecionar(conta):
    with transacao() as dados:
        if conta not in dados["contas"] or not dados["contas"][conta].get("refresh_token"):
            raise LoginInvalido("Conecte esta conta antes de selecioná-la.")
        dados["ativa"] = conta
        dados["metodo"] = "direto"


def metodo():
    with transacao() as dados:
        return dados.get("metodo") or ("direto" if dados.get("ativa") else "cli")


def usar_cli():
    with transacao() as dados:
        dados["metodo"] = "cli"


def access_token():
    with transacao() as dados:
        conta = dados["contas"].get(dados.get("ativa"))
        if not conta or not conta.get("refresh_token"):
            raise LoginInvalido("Conecte uma conta ChatGPT nas configurações.")
        if conta.get("expires_at", 0) <= time.time() + 60:
            meta = discovery()
            tokens = _json(meta["token_endpoint"], data={"grant_type": "refresh_token",
                "client_id": conta["client_id"], "refresh_token": conta["refresh_token"], "resource": RESOURCE})
            if tokens.get("id_token"):
                claims = validar_id(tokens["id_token"], conta["client_id"], None, _json(meta["jwks_uri"]))
                if claims["sub"] != conta["subject"]:
                    raise LoginInvalido("A renovação pertence a outra conta.")
            conta.update(_credenciais(tokens, conta))
        return conta["access_token"]


def sair(conta):
    confirmado = True
    with transacao() as dados:
        registro = dados["contas"].get(conta)
        if not registro:
            raise LoginInvalido("Conta não encontrada.")
        if registro.get("refresh_token"):
            try:
                _json(discovery()["revocation_endpoint"], data={"token": registro["refresh_token"],
                      "token_type_hint": "refresh_token", "client_id": registro["client_id"]})
            except LoginInvalido:
                confirmado = False
        for campo in ("access_token", "refresh_token", "id_token", "expires_at"):
            registro.pop(campo, None)
        if dados.get("ativa") == conta:
            dados["ativa"] = ""
    return {"revogacao_confirmada": confirmado}
