import pytest


def test_consolida_equipamentos_repetidos(solution):
    registros = [
        {"equipamento": "S01", "minutos": 10},
        {"equipamento": "S01", "minutos": 20},
        {"equipamento": "S03", "minutos": 15},
    ]
    assert solution.consolidar_falhas(registros) == {
        "totais": {"S01": 30, "S03": 15},
        "mais_critico": "S01",
    }


def test_lista_vazia_nao_tem_mais_critico(solution):
    assert solution.consolidar_falhas([]) == {"totais": {}, "mais_critico": None}


def test_empate_escolhe_ordem_alfabetica(solution):
    registros = [
        {"equipamento": "B02", "minutos": 12},
        {"equipamento": "A01", "minutos": 12},
    ]
    assert solution.consolidar_falhas(registros)["mais_critico"] == "A01"


def test_minutos_negativos_sao_rejeitados(solution):
    with pytest.raises(ValueError):
        solution.consolidar_falhas([{"equipamento": "S01", "minutos": -1}])
