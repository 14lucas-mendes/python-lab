def test_reincidencias_padrao_exige_duas_falhas(solution, conexao):
    assert solution.reincidencias(conexao) == [
        ("S01", "Bomba principal", 3),
        ("S03", "Ventilador leste", 2),
    ]


def test_reincidencias_respeitam_minimo(solution, conexao):
    assert solution.reincidencias(conexao, minimo=3) == [
        ("S01", "Bomba principal", 3),
    ]
    assert solution.reincidencias(conexao, minimo=4) == []


def test_falhas_do_equipamento(solution, conexao):
    assert solution.falhas_do_equipamento(conexao, "S03") == [
        ("S03", 20),
        ("S03", 15),
    ]


def test_consulta_nao_interpola_codigo(solution, conexao):
    assert solution.falhas_do_equipamento(conexao, "S01' OR '1'='1") == []
    assert solution.falhas_do_equipamento(conexao, "S09") == []
