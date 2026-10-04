def consolidar_turnos(eventos: list[dict]) -> list[int]:
    totais = [0, 0, 0]
    for evento in eventos:
        if evento["turno"] == "manha":
            totais[0] += evento["minutos"]
        elif evento["turno"] == "tarde":
            totais[1] += evento["minutos"]
    return totais
