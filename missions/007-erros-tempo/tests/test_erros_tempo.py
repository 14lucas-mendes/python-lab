def _source(solution_dir, name: str) -> str:
    return (solution_dir / name).read_text(encoding="utf-8")


def test_sintaxe_compila_antes_de_executar(solution_dir):
    compile(_source(solution_dir, "sintaxe.py"), "sintaxe.py", "exec")


def test_formatar_linhas_remove_espacos(solution_dir, load_module):
    modulo = load_module(solution_dir, "sintaxe.py")
    assert modulo.formatar_linhas(["  alarme  ", "bomba"]) == ["alarme", "bomba"]


def test_formatar_total_converte_numero_em_texto(solution_dir, load_module):
    modulo = load_module(solution_dir, "tipos.py")
    assert modulo.formatar_total(12) == "12 min"
    assert modulo.formatar_total(0) == "0 min"


def test_primeiro_alerta_usa_o_nome_certo(solution_dir, load_module):
    modulo = load_module(solution_dir, "nomes.py")
    assert modulo.primeiro_alerta(["S01 parado", "S03 ruído"]) == "S01 parado"
    assert modulo.primeiro_alerta([]) is None
