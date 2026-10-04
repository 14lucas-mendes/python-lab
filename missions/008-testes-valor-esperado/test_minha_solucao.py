import os
from pathlib import Path

from python_lab.solution_loader import load_solution

impl = load_solution(Path(os.environ["PYTHON_LAB_IMPL"]))


def test_escreva_valores_esperados_calculados_a_mao():
    raise NotImplementedError(
        "Escreva testes com totais calculados à mão, por exemplo [10, 5, 20]"
    )
