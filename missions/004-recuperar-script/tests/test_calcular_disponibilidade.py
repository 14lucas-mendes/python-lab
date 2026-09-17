import pytest


def test_lista_vazia_retorna_dicionario_vazio(solution):
    assert solution.calcular_disponibilidade([]) == {}


def test_nao_muta_a_lista_recebida(solution):
    eventos = [
        {"equipamento": "S02", "duracao": 10, "periodo": 100},
        {"equipamento": "S01", "duracao": 5, "periodo": 100},
    ]
    original = [dict(item) for item in eventos]
    solution.calcular_disponibilidade(eventos)
    assert eventos == original


def test_arredonda_somente_o_resultado_final(solution):
    eventos = [
        {"equipamento": "S01", "duracao": 10.004, "periodo": 50},
        {"equipamento": "S01", "duracao": 10.004, "periodo": 50},
    ]
    assert solution.calcular_disponibilidade(eventos)["S01"] == 79.99


@pytest.mark.parametrize("duracao", [-1, -2, -100])
def test_duracao_negativa_e_rejeitada(solution, duracao):
    with pytest.raises(ValueError):
        solution.calcular_disponibilidade(
            [{"equipamento": "S01", "duracao": duracao, "periodo": 100}]
        )


def test_calcula_disponibilidade_agregada(solution):
    eventos = [
        {"equipamento": "S01", "duracao": 10, "periodo": 100},
        {"equipamento": "S01", "duracao": 10, "periodo": 100},
        {"equipamento": "S02", "duracao": 25, "periodo": 100},
    ]
    assert solution.calcular_disponibilidade(eventos) == {"S01": 90.0, "S02": 75.0}
