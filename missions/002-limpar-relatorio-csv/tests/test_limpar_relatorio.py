def test_csv_valido_soma_por_equipamento(solution, tmp_path):
    caminho = tmp_path / "relatorio.csv"
    caminho.write_text("equipamento,minutos\nS01,10\nS01,20\nS03,15\n", encoding="utf-8")
    assert solution.limpar_relatorio(caminho) == {
        "validos": 3,
        "invalidos": 0,
        "totais": {"S01": 30, "S03": 15},
    }


def test_duracao_vazia_conta_invalido(solution, tmp_path):
    caminho = tmp_path / "relatorio.csv"
    caminho.write_text("equipamento,minutos\nS01,\nS02,8\n", encoding="utf-8")
    result = solution.limpar_relatorio(caminho)
    assert result["validos"] == 1
    assert result["invalidos"] == 1
    assert result["totais"] == {"S02": 8}


def test_duracao_nao_numerica_conta_invalido(solution, tmp_path):
    caminho = tmp_path / "relatorio.csv"
    caminho.write_text("equipamento,minutos\nS01,abc\nS02,5\n", encoding="utf-8")
    result = solution.limpar_relatorio(caminho)
    assert result["validos"] == 1
    assert result["invalidos"] == 1
    assert result["totais"] == {"S02": 5}


def test_campo_ausente_conta_invalido(solution, tmp_path):
    caminho = tmp_path / "relatorio.csv"
    caminho.write_text("equipamento,minutos\nS01\nS02,4\n", encoding="utf-8")
    result = solution.limpar_relatorio(caminho)
    assert result["validos"] == 1
    assert result["invalidos"] == 1
    assert result["totais"] == {"S02": 4}


def test_arquivo_vazio(solution, tmp_path):
    caminho = tmp_path / "relatorio.csv"
    caminho.write_text("", encoding="utf-8")
    assert solution.limpar_relatorio(caminho) == {"validos": 0, "invalidos": 0, "totais": {}}
