def listar_falhas(conexao, equipamento=None) -> list[tuple]:
    if equipamento is None:
        cursor = conexao.execute(
            "SELECT equipamento, minutos, registrado_em FROM falhas ORDER BY minutos DESC"
        )
    else:
        cursor = conexao.execute(
            "SELECT equipamento, minutos, registrado_em FROM falhas "
            "WHERE equipamento = ? ORDER BY minutos DESC",
            (equipamento,),
        )
    return list(cursor.fetchall())


def total_minutos(conexao) -> int:
    (total,) = conexao.execute("SELECT COALESCE(SUM(minutos), 0) FROM falhas").fetchone()
    return int(total)
