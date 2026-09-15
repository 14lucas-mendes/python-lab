import json
from pathlib import Path


REQUIRED_FIELDS = ("id", "tipo", "status")


def validar_inventario(caminho: Path) -> tuple[list, list]:
    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Inventário JSON inválido") from exc
    if not isinstance(payload, list):
        raise ValueError("Inventário JSON inválido")
    validos: list[dict] = []
    inconsistencias: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(payload):
        errors: list[str] = []
        if not isinstance(item, dict):
            errors.append("registro deve ser um objeto")
            inconsistencias.append({"index": index, "errors": errors})
            continue
        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or str(value).strip() == "":
                errors.append(f"campo obrigatório ausente: {field}")
        record_id = str(item.get("id", "")).strip()
        if record_id and record_id in seen:
            errors.append("id duplicado")
        if errors:
            inconsistencias.append({"index": index, "errors": errors})
            continue
        seen.add(record_id)
        validos.append(item)
    return validos, inconsistencias
