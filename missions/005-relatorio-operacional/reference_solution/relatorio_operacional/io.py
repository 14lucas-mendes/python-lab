import csv
import json
from pathlib import Path


def load_inputs(csv_path: Path, json_path: Path) -> tuple[list, list]:
    eventos: list[dict] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is not None:
            for row in reader:
                try:
                    equipamento = (row.get("equipamento") or "").strip()
                    minutos_raw = row.get("minutos")
                    if not equipamento or minutos_raw is None or str(minutos_raw).strip() == "":
                        raise ValueError("linha inválida")
                    minutos = int(str(minutos_raw).strip())
                except (TypeError, ValueError):
                    continue
                eventos.append({"equipamento": equipamento, "minutos": minutos})
    inventario = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(inventario, list):
        raise ValueError("Inventário JSON inválido")
    return eventos, inventario


def write_report(report: list, output_path: Path) -> None:
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
