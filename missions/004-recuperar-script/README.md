# Mission 004 — Recuperar script defeituoso

Um script de disponibilidade foi gerado às pressas e passa no caminho principal, mas quebra em casos reais. Seu trabalho é ler o código, entender os testes e corrigir o comportamento.

## Entrada

Uma lista de eventos com `equipamento`, `duracao` (minutos indisponíveis) e `periodo` (janela observada).

## Saída

Um dicionário `equipamento -> disponibilidade percentual`, com duas casas decimais.

A fórmula é `100 * (1 - soma_duracao / soma_periodo)`.

## Restrições

- Lista vazia deve devolver `{}`.
- A lista recebida não pode ser alterada.
- Duração negativa deve ser rejeitada.
- Arredonde somente o resultado final.

## Critérios de aceite

Os testes nomeiam cada comportamento esperado. Corrija `starter.py` até todos passarem.

Edite `starter.py` e rode os testes pelo Lab com `/test`.
