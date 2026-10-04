import sqlite3


def test_lista_todas_ordenadas_por_minutos(solution, conexao):
    assert solution.listar_falhas(conexao) == [
        ("S01", 40, "2026-03-01"),
        ("S03", 15, "2026-03-02"),
        ("S01", 10, "2026-03-03"),
    ]


def test_filtra_por_equipamento(solution, conexao):
    assert solution.listar_falhas(conexao, equipamento="S01") == [
        ("S01", 40, "2026-03-01"),
        ("S01", 10, "2026-03-03"),
    ]
    assert solution.listar_falhas(conexao, equipamento="S99") == []


def test_total_minutos(solution, conexao):
    assert solution.total_minutos(conexao) == 65


def test_tabela_vazia_soma_zero(solution):
    vazia = sqlite3.connect(":memory:")
    vazia.execute(
        "CREATE TABLE falhas (id INTEGER PRIMARY KEY, equipamento TEXT, "
        "minutos INTEGER, registrado_em TEXT)"
    )
    try:
        assert solution.total_minutos(vazia) == 0
        assert solution.listar_falhas(vazia) == []
    finally:
        vazia.close()
