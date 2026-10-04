# Mission 010 — Consultar falhas com SQL

Ciclo 5 · lesson_05-automacao-confiavel

O plantão passou a guardar falhas num SQLite. Você recebe uma conexão já aberta (`sqlite3` da biblioteca padrão) e devolve as linhas pedidas. O teste cria o banco; você só consulta.

A tabela `falhas` tem `equipamento`, `minutos` e `registrado_em`.

## Entrada

Uma conexão `sqlite3.Connection` e, em `listar_falhas`, um filtro opcional de equipamento.

## Saída

- `listar_falhas(conexao, equipamento=None)` devolve uma lista de tuplas `(equipamento, minutos, registrado_em)` em ordem decrescente de `minutos`
- `total_minutos(conexao)` devolve a soma de `minutos` (0 se a tabela estiver vazia)

## Restrições

- Use SQL. Não leia as linhas com `fetchall` só para filtrar em Python quando o banco puder filtrar.
- Quando `equipamento` for informado, filtre no `WHERE`.
- Sempre ordene por `minutos DESC`.

## Critérios de aceite

- Sem filtro, todas as falhas vêm da maior para a menor duração.
- Com filtro, só o equipamento pedido aparece.
- Tabela vazia soma 0.

Edite `starter.py` e rode `/test`.
