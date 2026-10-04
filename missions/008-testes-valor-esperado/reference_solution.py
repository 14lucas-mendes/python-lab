import os
from pathlib import Path

from python_lab.solution_loader import load_solution

impl = load_solution(Path(os.environ["PYTHON_LAB_IMPL"]))


def test_tres_turnos_com_literal_calculado():
    eventos = [
        {"turno": "manha", "minutos": 10},
        {"turno": "tarde", "minutos": 5},
        {"turno": "noite", "minutos": 20},
    ]
    assert impl.consolidar_turnos(eventos) == [10, 5, 20]


def test_apenas_noite():
    eventos = [{"turno": "noite", "minutos": 8}]
    assert impl.consolidar_turnos(eventos) == [0, 0, 8]


def test_lista_vazia_zera_os_tres_turnos():
    assert impl.consolidar_turnos([]) == [0, 0, 0]


def test_mesmo_turno_acumula():
    eventos = [
        {"turno": "manha", "minutos": 4},
        {"turno": "manha", "minutos": 6},
        {"turno": "tarde", "minutos": 1},
    ]
    assert impl.consolidar_turnos(eventos) == [10, 1, 0]
