def listar_falhas(conexao, equipamento=None) -> list[tuple]:
    """Liste (equipamento, minutos, registrado_em) ordenado por minutos DESC."""
    raise NotImplementedError("Implemente listar_falhas")


def total_minutos(conexao) -> int:
    """Some a coluna minutos. Tabela vazia vale 0."""
    raise NotImplementedError("Implemente total_minutos")
