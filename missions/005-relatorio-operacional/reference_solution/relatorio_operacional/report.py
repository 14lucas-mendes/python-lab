def build_report(eventos: list, inventario: list) -> list:
    totais: dict[str, int] = {}
    for evento in eventos:
        equipamento = evento["equipamento"]
        totais[equipamento] = totais.get(equipamento, 0) + evento["minutos"]
    report = []
    known: set[str] = set()
    for item in inventario:
        item_id = item["id"]
        known.add(item_id)
        report.append(
            {
                "id": item_id,
                "total_falhas": totais.get(item_id, 0),
                "status": item.get("status", "desconhecido"),
            }
        )
    for equipamento, total in totais.items():
        if equipamento not in known:
            report.append(
                {
                    "id": equipamento,
                    "total_falhas": total,
                    "status": "desconhecido",
                }
            )
    return report
