# Missão 001 — Consolidar falhas

Ciclo 1 · Python core

## Objetivo de aprendizagem

Agrupar registros em um dicionário e justificar como selecionar o maior total, incluindo empates e lista vazia.

## Conhecimentos necessários

Funções, retorno de valores, listas, dicionários, laços e comparações. Se precisar retomar acumulação por chave, consulte `/concepts` no Lab. Esse apoio é opcional e não libera pistas.

## Problema

Uma operação de plantão precisa saber, a partir de uma lista de interrupções, quanto tempo cada equipamento ficou indisponível e qual deles é o mais crítico.

Implemente `consolidar_falhas(registros)` no arquivo `starter.py`. Planeje sua tentativa com `/plan`, implemente no Cursor e verifique com `/test`.

## Entrada

Uma lista de dicionários com as chaves:

- `equipamento`: identificador textual
- `minutos`: duração da indisponibilidade

## Saída

Um dicionário com:

- `totais`: mapa de equipamento para soma de minutos
- `mais_critico`: equipamento com a maior soma, ou `None` se a lista estiver vazia

## Restrições

- Minutos negativos devem gerar `ValueError`.
- Em caso de empate, escolha o identificador em ordem alfabética.
- Não use bibliotecas externas.

## Exemplos

Caso comum:

```python
# Entrada
[
    {"equipamento": "B02", "minutos": 8},
    {"equipamento": "A01", "minutos": 5},
    {"equipamento": "B02", "minutos": 4},
]

# Saída esperada
{"totais": {"B02": 12, "A01": 5}, "mais_critico": "B02"}
```

Caso extremo: `[]` retorna `{"totais": {}, "mais_critico": None}`.

Empate: se `B02` e `A01` acumularem 12 minutos cada, `mais_critico` será `"A01"`.

## Critérios de aceite

- Equipamentos repetidos são somados.
- Lista vazia não aponta equipamento crítico.
- Empates são resolvidos alfabeticamente.
- Minutos negativos geram erro.

O `/test` apresenta o resumo e as falhas. Use `/test details` para consultar a saída completa sem criar outra tentativa.

## Reflexão final

Na `/explain`, descreva suas decisões em uma resposta única:

- Como você acumula registros repetidos sem perder os valores anteriores?
- Como sua solução resolve empates e trata a lista vazia?

Se alterar a solução após os testes passarem, rode `/test` novamente antes de concluir.
