# Mission 011 — Reincidências com JOIN e agregação

Ciclo 5 · lesson_05-automacao-confiavel

Agora o banco tem duas tabelas: `equipamentos` e `falhas`. Uma reincidência é um equipamento com várias falhas. Você vai juntar as tabelas, agregar e consultar um código sem interpolar SQL.

## Entrada

Conexão SQLite já aberta. Esquema em `data/plantao.sql`.

- `equipamentos(codigo, nome)`
- `falhas(id, equipamento, minutos)` — `equipamento` aponta para `equipamentos.codigo`

## Saída

- `reincidencias(conexao, minimo=2)` devolve `(codigo, nome, quantidade)` para equipamentos com `COUNT(*) >= minimo`, ordenado pela quantidade decrescente
- `falhas_do_equipamento(conexao, codigo)` devolve as falhas daquele código como `(equipamento, minutos)`, usando consulta parametrizada

## Restrições

- Use `JOIN`, `GROUP BY` e `HAVING`. Não monte a agregação em Python.
- O código do equipamento entra como `?`. Um valor malicioso não pode devolver todas as linhas.

## Critérios de aceite

- Só entram equipamentos com pelo menos `minimo` falhas.
- O nome vem da tabela de equipamentos.
- `falhas_do_equipamento("S01' OR '1'='1")` devolve lista vazia.

Edite `starter.py` e rode `/test`.
