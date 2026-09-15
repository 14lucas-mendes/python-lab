from pathlib import Path


def load_inputs(csv_path: Path, json_path: Path) -> tuple[list, list]:
    raise NotImplementedError("Implemente load_inputs")


def write_report(report: list, output_path: Path) -> None:
    raise NotImplementedError("Implemente write_report")
