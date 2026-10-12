"""Autorizações próprias ficam separadas das chaves de API e dos CLIs."""
import json
import os
import threading
from contextlib import contextmanager

from . import secrets

_LOCK = threading.RLock()


@contextmanager
def transacao():
    """O bloqueio entre processos protege a rotação do refresh token."""
    caminho = secrets.caminho_do_cofre().with_name("chatgpt.json")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    trava = caminho.with_suffix(".lock")
    with _LOCK, open(trava, "a+b") as arquivo:
        os.chmod(trava, 0o600)
        if arquivo.seek(0, 2) == 0:
            arquivo.write(b"0")
            arquivo.flush()
        arquivo.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX)
        try:
            dados = {"contas": {}, "ativa": ""}
            if caminho.exists():
                bruto = caminho.read_bytes()
                if bruto.startswith(secrets._CABECALHO):
                    if not secrets._WINDOWS:
                        raise secrets.CofreInvalido("Abra a autorização na conta do Windows que a gravou.")
                    bruto = secrets._dpapi(bruto[len(secrets._CABECALHO):], False)
                elif secrets._WINDOWS:
                    raise secrets.CofreInvalido("A autorização não está protegida; o arquivo foi preservado.")
                try:
                    dados = json.loads(bruto)
                    if not isinstance(dados, dict) or not isinstance(dados.get("contas"), dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    raise secrets.CofreInvalido("Autorização inválida; o arquivo foi preservado.") from None
            original = json.dumps(dados, sort_keys=True)
            yield dados
            if json.dumps(dados, sort_keys=True) != original:
                bruto = json.dumps(dados, ensure_ascii=False).encode("utf-8")
                if secrets._WINDOWS:
                    bruto = secrets._CABECALHO + secrets._dpapi(bruto, True)
                else:
                    secrets._avisar_sem_protecao()
                secrets._trocar(caminho, bruto)
        finally:
            arquivo.seek(0)
            if os.name == "nt":
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)
