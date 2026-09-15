import json

import pytest


def test_json_valido_separa_registros(solution, tmp_path):
    caminho = tmp_path / "inventario.json"
    caminho.write_text(
        json.dumps(
            [
                {"id": "EQ-1", "tipo": "servidor", "status": "ativo"},
                {"id": "EQ-2", "tipo": "switch", "status": "inativo"},
            ]
        ),
        encoding="utf-8",
    )
    validos, inconsistencias = solution.validar_inventario(caminho)
    assert [item["id"] for item in validos] == ["EQ-1", "EQ-2"]
    assert inconsistencias == []


def test_arquivo_malformado_gera_value_error(solution, tmp_path):
    caminho = tmp_path / "inventario.json"
    caminho.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="Inventário JSON inválido"):
        solution.validar_inventario(caminho)


def test_campos_obrigatorios_ausentes(solution, tmp_path):
    caminho = tmp_path / "inventario.json"
    caminho.write_text(
        json.dumps([{"id": "EQ-1", "tipo": "servidor"}]),
        encoding="utf-8",
    )
    validos, inconsistencias = solution.validar_inventario(caminho)
    assert validos == []
    assert inconsistencias[0]["index"] == 0
    assert "status" in inconsistencias[0]["errors"][0]


def test_ids_duplicados(solution, tmp_path):
    caminho = tmp_path / "inventario.json"
    caminho.write_text(
        json.dumps(
            [
                {"id": "EQ-1", "tipo": "servidor", "status": "ativo"},
                {"id": "EQ-1", "tipo": "switch", "status": "ativo"},
            ]
        ),
        encoding="utf-8",
    )
    validos, inconsistencias = solution.validar_inventario(caminho)
    assert len(validos) == 1
    assert inconsistencias[0]["index"] == 1


def test_lista_vazia(solution, tmp_path):
    caminho = tmp_path / "inventario.json"
    caminho.write_text("[]", encoding="utf-8")
    validos, inconsistencias = solution.validar_inventario(caminho)
    assert validos == []
    assert inconsistencias == []
