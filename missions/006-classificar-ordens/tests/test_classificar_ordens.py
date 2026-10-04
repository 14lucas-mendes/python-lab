import pytest


def test_falha_urgente_e_emergencia(solution):
    ordem = {
        "tipo": "falha",
        "prioridade": "urgente",
        "itens": [{"bloqueado": False}],
    }
    assert solution.classificar_ordem(ordem) == "emergencia"


def test_falha_comum_e_corretiva(solution):
    ordem = {
        "tipo": "falha",
        "prioridade": "normal",
        "itens": [{"bloqueado": False}],
    }
    assert solution.classificar_ordem(ordem) == "corretiva"


def test_item_bloqueado_prevalece_sobre_emergencia(solution):
    ordem = {
        "tipo": "falha",
        "prioridade": "urgente",
        "itens": [{"bloqueado": True}],
    }
    assert solution.classificar_ordem(ordem) == "bloqueada"


def test_preventiva_e_demais_tipos(solution):
    preventiva = {
        "tipo": "preventiva",
        "prioridade": "normal",
        "itens": [{"bloqueado": False}],
    }
    administrativa = {
        "tipo": "inspecao",
        "prioridade": "urgente",
        "itens": [{"bloqueado": False}],
    }
    assert solution.classificar_ordem(preventiva) == "preventiva"
    assert solution.classificar_ordem(administrativa) == "administrativa"


@pytest.mark.parametrize("itens", [None, [], ])
def test_itens_ausentes_ou_vazios_sao_rejeitados(solution, itens):
    ordem = {"tipo": "falha", "prioridade": "urgente"}
    if itens is not None:
        ordem["itens"] = itens
    with pytest.raises(ValueError):
        solution.classificar_ordem(ordem)
