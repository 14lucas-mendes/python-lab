import json

import pytest


def test_arquivo_ausente(solution, tmp_path):
    with pytest.raises(FileNotFoundError):
        solution.load_inputs(tmp_path / "missing.csv", tmp_path / "missing.json")


def test_linha_invalida_nao_aborta_leitura(solution, tmp_path):
    csv_path = tmp_path / "eventos.csv"
    json_path = tmp_path / "inventario.json"
    csv_path.write_text("equipamento,minutos\nEQ-1,10\nEQ-1,abc\n", encoding="utf-8")
    json_path.write_text(
        '[{"id":"EQ-1","tipo":"servidor","status":"ativo"}]',
        encoding="utf-8",
    )
    eventos, inventario = solution.load_inputs(csv_path, json_path)
    assert eventos == [{"equipamento": "EQ-1", "minutos": 10}]
    assert inventario[0]["id"] == "EQ-1"


def test_equipamento_desconhecido(solution):
    eventos = [{"equipamento": "EQ-99", "minutos": 7}]
    inventario = [{"id": "EQ-1", "tipo": "servidor", "status": "ativo"}]
    report = solution.build_report(eventos, inventario)
    by_id = {item["id"]: item for item in report}
    assert by_id["EQ-99"]["status"] == "desconhecido"
    assert by_id["EQ-99"]["total_falhas"] == 7
    assert by_id["EQ-1"]["total_falhas"] == 0


def test_entrada_vazia(solution):
    assert solution.build_report([], []) == []


def test_round_trip_do_arquivo_final(solution, tmp_path):
    report = [{"id": "EQ-1", "total_falhas": 30, "status": "ativo"}]
    output = tmp_path / "relatorio.json"
    solution.write_report(report, output)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded == report


def test_eventos_repetidos_sao_agregados(solution):
    report = solution.build_report(
        [
            {"equipamento": "EQ-99", "minutos": 7},
            {"equipamento": "EQ-99", "minutos": 8},
        ],
        [],
    )

    assert report == [
        {"id": "EQ-99", "total_falhas": 15, "status": "desconhecido"}
    ]


def test_linha_invalida_e_seguida_por_linha_valida(solution, tmp_path):
    csv_path = tmp_path / "eventos.csv"
    json_path = tmp_path / "inventario.json"
    csv_path.write_text(
        "equipamento,minutos\nEQ-1,abc\nEQ-1,10\n", encoding="utf-8"
    )
    json_path.write_text("[]", encoding="utf-8")

    eventos, _ = solution.load_inputs(csv_path, json_path)

    assert eventos == [{"equipamento": "EQ-1", "minutos": 10}]
