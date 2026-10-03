import json
import os

import pytest

from robinbandit import secrets as cofre


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(tmp_path / "cofre.json"))
    monkeypatch.setattr(cofre, "_PATH_ENV", "ROBINBANDIT_VAULT_PATH")


@pytest.mark.skipif(os.name != "nt", reason="DPAPI exige Windows")
def test_dpapi_real_ida_e_volta():
    cofre.guardar("CHAVE", "segredo-para-teste")
    assert b"segredo-para-teste" not in cofre.caminho_do_cofre().read_bytes()
    assert cofre.ler("CHAVE") == "segredo-para-teste"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI exige Windows")
def test_migracao_preserva_backup_ate_confirmar_leitura():
    caminho = cofre.caminho_do_cofre()
    bruto = json.dumps({"CHAVE": ["primeira", "segunda"]}).encode()
    caminho.write_bytes(bruto)
    assert cofre.listar("CHAVE") == ["primeira", "segunda"]
    backup = caminho.with_name(caminho.name + ".bak")
    assert backup.read_bytes() == bruto
    assert caminho.read_bytes().startswith(cofre._CABECALHO)
    assert cofre.listar("CHAVE") == ["primeira", "segunda"]
    assert not backup.exists()


@pytest.mark.skipif(os.name != "nt", reason="DPAPI exige Windows")
def test_protegido_corrompido_preserva_arquivo_e_backup():
    caminho = cofre.caminho_do_cofre()
    bruto = cofre._CABECALHO + b"invalido"
    caminho.write_bytes(bruto)
    backup = caminho.with_name(caminho.name + ".bak")
    backup.write_bytes(b'{"CHAVE":"original"}')
    with pytest.raises(cofre.CofreInvalido, match="Windows"):
        cofre.guardar("CHAVE", "outra")
    assert caminho.read_bytes() == bruto
    assert backup.exists()


def test_sem_dpapi_avisa_uma_vez_e_continua_lendo(monkeypatch, caplog):
    monkeypatch.setattr(cofre, "_WINDOWS", False)
    monkeypatch.setattr(cofre, "_AVISOU", False)
    cofre.guardar("CHAVE", "segredo")
    assert cofre.ler("CHAVE") == "segredo"
    assert json.loads(cofre.caminho_do_cofre().read_text()) == {
        "CHAVE": [{"valor": "segredo", "nome": "", "paga": False}]}
    assert sum("sem criptografia" in r.message for r in caplog.records) == 1


def test_falha_na_protecao_nao_substitui_original(monkeypatch):
    caminho = cofre.caminho_do_cofre()
    bruto = b'{"CHAVE":"original"}'
    caminho.write_bytes(bruto)
    monkeypatch.setattr(cofre, "_WINDOWS", True)
    def falhar(*args):
        raise cofre.CofreInvalido("falha de teste")
    monkeypatch.setattr(cofre, "_dpapi", falhar)
    with pytest.raises(cofre.CofreInvalido):
        cofre.ler("CHAVE")
    assert caminho.read_bytes() == bruto
    assert caminho.with_name(caminho.name + ".bak").read_bytes() == bruto
