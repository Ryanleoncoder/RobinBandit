from __future__ import annotations

import json

from robinbandit.accounts import account_config


def test_contas_e_preferencias_sao_gravadas_por_assunto(monkeypatch, tmp_path):
    contas = tmp_path / "contas.json"
    monkeypatch.setattr(account_config, "caminho_da_config", lambda: contas)

    account_config.salvar_conta({
        "id": "groq-pessoal",
        "provider": "groq",
        "key_env": "GROQ_API_KEY",
    })
    account_config.definir_estrategia("fixed")
    account_config.definir_cadeia(["groq"], ["groq"])

    preferencias = tmp_path / "preferencias.json"
    dados_contas = json.loads(contas.read_text(encoding="utf-8"))
    dados_preferencias = json.loads(preferencias.read_text(encoding="utf-8"))

    assert dados_contas["contas"][0]["id"] == "groq-pessoal"
    assert "estrategia" not in dados_contas
    assert "cadeia" not in dados_contas
    assert dados_preferencias["estrategia"] == "fixed"
    assert dados_preferencias["cadeia"] == ["groq"]
    assert "contas" not in dados_preferencias


def test_formato_antigo_e_migrado_sem_sobrescrever_preferencia(monkeypatch, tmp_path):
    contas = tmp_path / "contas.json"
    preferencias = tmp_path / "preferencias.json"
    monkeypatch.setattr(account_config, "caminho_da_config", lambda: contas)
    contas.write_text(json.dumps({
        "contas": [],
        "tiers": {"ultra": "claude"},
        "estrategia": "adaptive",
        "cadeia": ["groq", "gemini"],
        "idioma": "pt",
    }), encoding="utf-8")
    preferencias.write_text(json.dumps({"estrategia": "fixed"}), encoding="utf-8")

    dados = account_config.carregar()

    assert dados["estrategia"] == "fixed"
    assert dados["cadeia"] == ["groq", "gemini"]
    assert dados["idioma"] == "pt"
    assert json.loads(contas.read_text(encoding="utf-8")) == {
        "contas": [], "tiers": {"ultra": "claude"}
    }
    migradas = json.loads(preferencias.read_text(encoding="utf-8"))
    assert migradas["estrategia"] == "fixed"
    assert migradas["cadeia"] == ["groq", "gemini"]
    assert migradas["idioma"] == "pt"
