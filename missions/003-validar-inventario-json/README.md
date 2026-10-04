# Mission 003 — Validar inventário JSON

Ciclo 4 · lesson_02-arquivos-erros

O cadastro de equipamentos misturou registros completos com dados inconsistentes. Separe o que pode ser usado do que precisa de correção.

## Entrada

Caminho para um JSON contendo uma lista de objetos. Cada equipamento válido tem `id`, `tipo` e `status`.

## Saída

Uma tupla `(validos, inconsistencias)`:

- `validos`: lista dos equipamentos aproveitáveis
- `inconsistencias`: lista de dicionários com `index` e `errors`

## Restrições

- JSON malformado deve gerar `ValueError` com a mensagem `Inventário JSON inválido`.
- IDs duplicados não entram em `validos`.
- Lista vazia é um inventário vazio válido.

## Critérios de aceite

- Arquivo íntegro devolve todos os equipamentos.
- Campos obrigatórios ausentes geram inconsistência com índice.
- Duplicatas são apontadas.
- Lista vazia não produz erros.

Edite `starter.py` e rode os testes pelo Lab com `/test`.
