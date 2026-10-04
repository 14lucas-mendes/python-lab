def reincidencias(conexao, minimo: int = 2) -> list[tuple]:
    """Liste (codigo, nome, quantidade) com HAVING COUNT(*) >= minimo."""
    raise NotImplementedError("Implemente reincidencias")


def falhas_do_equipamento(conexao, codigo: str) -> list[tuple]:
    """Liste (equipamento, minutos) do código com consulta parametrizada."""
    raise NotImplementedError("Implemente falhas_do_equipamento")
