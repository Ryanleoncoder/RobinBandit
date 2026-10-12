from robinbandit.state import uso


def test_uso_separa_entrada_saida_e_custo_informado():
    uso.registrar("provedor-a", {
        "entrada": 120, "saida": 30, "total": 150, "custo_usd": 0.0042,
    })
    uso.registrar("provedor-b", {"entrada": 50, "saida": 10, "total": 60})

    medido = uso.total(1)
    assert medido["entrada"] == 170
    assert medido["saida"] == 40
    assert medido["total"] == 210
    assert medido["custo_usd"] == 0.0042
    assert medido["chamadas_com_custo"] == 1


def test_uso_nao_confunde_custo_desconhecido_com_gratis():
    uso.registrar("sem-preco", {"entrada": 10, "saida": 2, "total": 12})
    linha = uso.por_provedor(1)[0]
    assert linha["custo_usd"] == 0
    assert linha["chamadas_com_custo"] == 0


def test_chamada_sem_tokens_conta_sem_inventar_consumo():
    uso.registrar("chatgpt_codex", None)
    resumo = uso.total(1)
    assert resumo["chamadas"] == 1
    assert resumo["chamadas_sem_uso"] == 1
    assert resumo["chamadas_com_uso"] == 0
    assert resumo["total"] == 0 and resumo["chamadas_com_custo"] == 0
    assert uso.calendario(1)[0]["chamadas_sem_uso"] == 1


def test_medicao_parcial_conta_so_tokens_informados():
    uso.registrar("chatgpt_codex", None)
    uso.registrar("chatgpt_codex", {"entrada": 20, "saida": 4, "total": 24})
    resumo = uso.total(1)
    assert resumo["chamadas"] == 2
    assert resumo["chamadas_com_uso"] == 1 and resumo["chamadas_sem_uso"] == 1
    assert resumo["total"] == 24


def test_formato_antigo_continua_com_medicao(tmp_path):
    import json
    uso.caminho().parent.mkdir(parents=True, exist_ok=True)
    uso.caminho().write_text(json.dumps({uso._hoje(): {"teste": {"entrada": 2, "saida": 1, "total": 3,
        "chamadas": 1, "custo_usd": 0, "chamadas_com_custo": 0}}}), encoding="utf-8")
    assert uso.total(1)["chamadas_com_uso"] == 1


def test_processos_nao_perdem_chamadas(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    casa = tmp_path / "paralelo"
    script = "from robinbandit.state.uso import registrar; [registrar('teste',None) for _ in range(20)]"
    env = {**os.environ, "ROBINBANDIT_HOME": str(casa), "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    processos = [subprocess.Popen([sys.executable, "-c", script], env=env) for _ in range(3)]
    assert all(p.wait(timeout=20) == 0 for p in processos)
    import json
    dados = json.loads((casa / "uso.json").read_text(encoding="utf-8"))
    assert dados[uso._hoje()]["teste"]["chamadas"] == 60


def test_raciocinio_persiste_sem_ser_contado_duas_vezes():
    uso.registrar("gemini", {"entrada": 359, "saida": 2, "raciocinio": 490, "total": 851})
    for linha in (uso.total(1), uso.por_provedor(1)[0], uso.calendario(1)[0]):
        assert linha["raciocinio"] == 490
        assert linha["total"] == 851
        assert linha["nao_detalhados"] == 0
        assert linha["chamadas_com_raciocinio"] == 1


def test_historico_sem_raciocinio_nao_e_regravado_ou_rotulado_por_estimativa():
    import json

    alvo = uso.caminho()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({uso._hoje(): {"gemini": {"entrada": 359, "saida": 2, "total": 851, "chamadas": 1}}})
    alvo.write_text(original, encoding="utf-8")
    linha = uso.total(1)
    assert linha["chamadas_com_raciocinio"] == 0
    assert linha["nao_detalhados"] == 490
    assert alvo.read_text(encoding="utf-8") == original
