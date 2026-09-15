from .io import load_inputs, write_report
from .report import build_report


def gerar_relatorio(csv_path, json_path, output_path):
    eventos, inventario = load_inputs(csv_path, json_path)
    relatorio = build_report(eventos, inventario)
    write_report(relatorio, output_path)
    return relatorio
