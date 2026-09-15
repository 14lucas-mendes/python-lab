def calcular_disponibilidade(eventos: list[dict]) -> dict:
    eventos.sort(key=lambda item: item["equipamento"])
    totais: dict[str, dict[str, float]] = {}
    media = sum(item["duracao"] for item in eventos) / len(eventos)
    for evento in eventos:
        duracao = round(evento["duracao"], 2)
        periodo = evento["periodo"]
        atual = totais.setdefault(evento["equipamento"], {"duracao": 0.0, "periodo": 0.0})
        atual["duracao"] += duracao
        atual["periodo"] += periodo
    resultado = {
        nome: round(100 * (1 - dados["duracao"] / dados["periodo"]), 2)
        for nome, dados in totais.items()
    }
    resultado["_media"] = round(media, 2)
    return resultado
