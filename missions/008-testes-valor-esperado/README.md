# Mission 008 — Testes com valor esperado

Ciclo 2 · lesson_03-testes-git

A função `consolidar_turnos` já existe em duas versões escondidas: uma correta e uma com defeito. O seu trabalho **não** é implementar a função. É escrever testes que a julguem.

Some os minutos na ordem `manha`, `tarde`, `noite` **à mão** e escreva o resultado como literal de lista: `[10, 5, 20]`. Não chame a função para descobrir o número e depois colar.

## Entrada

Cada evento é um dicionário:

```python
{"turno": "manha", "minutos": 10}
```

A função devolve uma lista de três inteiros: totais da manhã, da tarde e da noite.

## Saída

Edite `test_minha_solucao.py`. Os testes da missão vão rodar a sua suíte duas vezes:

- contra uma implementação correta — precisa passar
- contra uma implementação com defeito — precisa falhar

## Restrições

- Calcule os totais no papel ou de cabeça. Escreva o valor esperado na asserção.
- Use literais de lista (`[0, 0, 8]`), não o retorno de outra chamada.
- Cubra pelo menos um caso com os três turnos, um caso só com noite e a lista vazia.

## Critérios de aceite

- A suíte passa na implementação correta.
- A suíte falha na implementação com defeito.
- Há asserções com valores esperados explícitos.

Edite `test_minha_solucao.py` e rode `/test`.
