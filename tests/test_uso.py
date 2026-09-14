from robinbandit import uso


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
