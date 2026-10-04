# Mission 001 — Consolidar falhas

Ciclo 1 · lesson_01-python-core

Uma operação de plantão precisa saber, a partir de uma lista de interrupções, quanto tempo cada equipamento ficou indisponível e qual deles é o mais crítico.

## Entrada

Uma lista de dicionários com as chaves:

- `equipamento`: identificador textual
- `minutos`: duração da indisponibilidade

## Saída

Um dicionário com:

- `totais`: mapa de equipamento para soma de minutos
- `mais_critico`: equipamento com a maior soma, ou `None` se a lista estiver vazia

## Restrições

- Minutos negativos devem ser rejeitados.
- Em caso de empate, escolha o identificador em ordem alfabética.
- Não use bibliotecas externas.

## Critérios de aceite

- Equipamentos repetidos são somados.
- Lista vazia não aponta equipamento crítico.
- Empates são resolvidos alfabeticamente.
- Minutos negativos geram erro.

Edite `starter.py` e rode os testes pelo Lab com `/test`.
