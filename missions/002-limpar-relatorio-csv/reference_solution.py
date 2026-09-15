import csv
from pathlib import Path


def limpar_relatorio(caminho: Path) -> dict:
    validos = 0
    invalidos = 0
    totais: dict[str, int] = {}
    with caminho.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return {"validos": 0, "invalidos": 0, "totais": {}}
        for row in reader:
            try:
                equipamento = (row.get("equipamento") or "").strip()
                minutos_raw = row.get("minutos")
                if not equipamento or minutos_raw is None or str(minutos_raw).strip() == "":
                    raise ValueError("linha inválida")
                minutos = int(str(minutos_raw).strip())
            except (TypeError, ValueError):
                invalidos += 1
                continue
            validos += 1
            totais[equipamento] = totais.get(equipamento, 0) + minutos
    return {"validos": validos, "invalidos": invalidos, "totais": totais}
