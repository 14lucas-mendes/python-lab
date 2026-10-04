def consolidar_turnos(eventos: list[dict]) -> list[int]:
    ordem = ("manha", "tarde", "noite")
    totais = {turno: 0 for turno in ordem}
    for evento in eventos:
        totais[evento["turno"]] += evento["minutos"]
    return [totais[turno] for turno in ordem]
