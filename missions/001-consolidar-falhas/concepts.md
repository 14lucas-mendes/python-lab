# Apoio conceitual — Acumulação por chave

Um dicionário associa uma chave a um valor. Quando vários registros pertencem ao mesmo grupo, você pode atualizar o valor dessa chave em vez de criar outro grupo.

Exemplo diferente da missão: uma papelaria registra unidades vendidas por produto.

```python
vendas = {"caderno": 3, "caneta": 5}
vendas["caderno"] = vendas["caderno"] + 2
# Agora o total de cadernos é 5; o de canetas continua 5.
```

Se a chave ainda não existe, `vendas.get("borracha", 0)` devolve o valor inicial `0`. Isso permite raciocinar sobre o primeiro registro de um grupo sem perder os seguintes.

Antes de escrever o laço, percorra um exemplo à mão: após cada registro, qual chave muda e qual valor ela deve guardar?

## Acumular e escolher são decisões diferentes

Primeiro descubra o total de cada grupo. Depois avalie qual total atende ao critério de seleção. Um maior valor pode aparecer em mais de uma chave: a regra de desempate precisa ser explícita.

Uma coleção vazia também precisa de um resultado definido; não há candidato a selecionar. Consulte o contrato da missão para decidir o que devolver.

Esse material é uma revisão de conceitos. Para ajuda específica sobre sua tentativa, execute `/test` e consulte `/hint` se precisar.
