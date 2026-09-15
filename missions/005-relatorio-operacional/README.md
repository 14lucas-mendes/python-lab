# Mission 005 — Gerar relatório operacional

Esta missão integra o que você já praticou: ler CSV, validar JSON, tratar exceções e organizar código em módulos. Não há tecnologia nova.

## Entrada

- CSV de eventos com `equipamento` e `minutos`
- JSON de inventário com `id`, `tipo` e `status`

## Saída

Um relatório JSON com um item por equipamento contendo:

- `id`
- `total_falhas`
- `status` cadastral, ou `desconhecido` se o equipamento só aparece nos eventos

Funções públicas do pacote `relatorio_operacional`:

- `load_inputs(csv_path, json_path)`
- `build_report(eventos, inventario)`
- `write_report(report, output_path)`

## Restrições

- Separe I/O e regras em `io.py`, `report.py` e `main.py`.
- Arquivo ausente deve gerar `FileNotFoundError`.
- Linha CSV inválida não aborta a leitura.
- `main.py` apenas orquestra; não duplique validação.

## Critérios de aceite

- Entrada vazia gera lista vazia.
- Equipamento fora do cadastro aparece como desconhecido.
- O arquivo gravado relê o mesmo conteúdo.

Edite os arquivos em `starter/relatorio_operacional/` e rode os testes pelo Lab com `/test`.
