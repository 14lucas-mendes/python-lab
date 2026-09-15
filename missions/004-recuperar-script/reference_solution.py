def calcular_disponibilidade(eventos: list[dict]) -> dict:
    totais: dict[str, dict[str, float]] = {}
    for evento in eventos:
        duracao = evento["duracao"]
        if duracao < 0:
            raise ValueError("Duração negativa não é permitida")
        atual = totais.setdefault(evento["equipamento"], {"duracao": 0.0, "periodo": 0.0})
        atual["duracao"] += duracao
        atual["periodo"] += evento["periodo"]
    return {
        nome: round(100 * (1 - dados["duracao"] / dados["periodo"]), 2)
        for nome, dados in totais.items()
    }
