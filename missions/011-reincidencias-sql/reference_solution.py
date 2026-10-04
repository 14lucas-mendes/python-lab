def reincidencias(conexao, minimo: int = 2) -> list[tuple]:
    cursor = conexao.execute(
        """
        SELECT equipamentos.codigo, equipamentos.nome, COUNT(*) AS quantidade
        FROM equipamentos
        JOIN falhas ON falhas.equipamento = equipamentos.codigo
        GROUP BY equipamentos.codigo, equipamentos.nome
        HAVING COUNT(*) >= ?
        ORDER BY quantidade DESC
        """,
        (minimo,),
    )
    return list(cursor.fetchall())


def falhas_do_equipamento(conexao, codigo: str) -> list[tuple]:
    cursor = conexao.execute(
        "SELECT equipamento, minutos FROM falhas WHERE equipamento = ? ORDER BY minutos DESC",
        (codigo,),
    )
    return list(cursor.fetchall())
