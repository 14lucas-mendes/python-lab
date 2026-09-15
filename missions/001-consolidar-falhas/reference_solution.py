def consolidar_falhas(registros: list[dict]) -> dict:
    totais: dict[str, int] = {}
    for registro in registros:
        minutos = registro["minutos"]
        if minutos < 0:
            raise ValueError("Minutos negativos não são permitidos")
        equipamento = registro["equipamento"]
        totais[equipamento] = totais.get(equipamento, 0) + minutos
    mais_critico = None
    if totais:
        maior = max(totais.values())
        candidatos = [nome for nome, total in totais.items() if total == maior]
        mais_critico = min(candidatos)
    return {"totais": totais, "mais_critico": mais_critico}
