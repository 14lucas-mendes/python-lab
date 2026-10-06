# Apoio conceitual — Condições e acesso seguro

## Condições exclusivas e precedência

Uma cadeia `if` / `elif` / `else` seleciona o primeiro ramo verdadeiro. As condições seguintes não são avaliadas quando um ramo já foi escolhido.

Imagine uma biblioteca com regras de empréstimo: um cadastro suspenso impede qualquer empréstimo; um leitor com reserva tem prioridade sobre a fila comum. Um leitor pode estar suspenso e ter uma reserva ao mesmo tempo. A regra que deve prevalecer precisa vir primeiro.

Antes de programar, monte uma pequena tabela: condição específica, condição geral e resultado esperado quando ambas são verdadeiras. Isso ajuda a perceber regras que ficariam inacessíveis.

## Verificar antes de acessar

O índice `0` só existe se uma lista tiver pelo menos um elemento. Em outro contexto, uma fila de leitores pode estar vazia:

```python
fila = []
bool(fila)  # False
# fila[0] levantaria IndexError.
```

Também há diferença entre uma chave ausente no dicionário e uma lista vazia. Consulte o contrato para saber como tratar os dois casos.

Uma guarda é uma verificação que impede continuar com dados que não satisfazem as condições necessárias. Ela deve acontecer antes da operação que depende desses dados. Esconder um erro após acessar a lista não substitui essa verificação.

Use `/mission` para retomar o contrato. As pistas específicas continuam disponíveis com `/hint` após a primeira execução de `/test`.
