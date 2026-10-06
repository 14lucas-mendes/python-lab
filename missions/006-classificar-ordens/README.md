# Missão 006 — Classificar ordens de serviço

Ciclo 1 · Python core

## Objetivo de aprendizagem

Ordenar condições por precedência e verificar a existência de itens antes de acessar a lista.

## Conhecimentos necessários

Funções, dicionários, listas, booleanos, `if` / `elif` / `else` e `ValueError`. Consulte `/concepts` para revisar condições e acesso seguro. Esse apoio é opcional e não libera pistas.

## Problema

Uma central de manutenção recebe ordens de serviço e precisa classificá-las antes de encaminhar. A ordem das perguntas importa: a regra específica vem antes da geral, e você só lê o primeiro item depois de confirmar que a lista existe.

Implemente `classificar_ordem(ordem)` em `starter.py`. Registre seu plano, implemente no Cursor e execute `/test`.

## Entrada

Um dicionário com:

- `tipo`: `falha`, `preventiva` ou outro texto
- `prioridade`: `urgente` ou outro texto
- `itens`: lista de dicionários; cada item pode ter `bloqueado` (bool)

## Saída

Uma string:

- `bloqueada` se o primeiro item está bloqueado
- `emergencia` se o tipo é `falha` e a prioridade é `urgente`
- `corretiva` se o tipo é `falha`
- `preventiva` se o tipo é `preventiva`
- `administrativa` nos demais casos

## Restrições

- Se `itens` estiver ausente ou vazio, rejeite com `ValueError` **antes** de acessar `itens[0]`.
- Use `if` / `elif` / `else` exclusivos. Não empilhe `if` soltos para o mesmo resultado.
- A emergência é um caso especial de falha: teste-a antes da falha genérica.

## Exemplos

Caso comum:

```python
# Entrada
{"tipo": "falha", "prioridade": "urgente", "itens": [{"bloqueado": False}]}

# Saída esperada
"emergencia"
```

Regras sobrepostas: a mesma ordem com `"bloqueado": True` retorna `"bloqueada"`, mesmo sendo urgente.

Caso extremo: `{"tipo": "falha", "itens": []}` gera `ValueError`; não retorna uma categoria.

## Critérios de aceite

- Lista vazia ou ausente gera erro.
- Item bloqueado prevalece sobre emergência.
- Falha urgente é emergência; falha comum é corretiva.
- Preventiva e os demais tipos caem nas categorias certas.

Use `/test details` para examinar a saída completa de uma execução sem criar outra tentativa.

## Reflexão final

Na `/explain`, responda em um único texto:

- Por que um item bloqueado prevalece sobre uma falha urgente?
- Por que verificar a lista antes de acessar o primeiro item?
- O que mudaria se a falha genérica viesse antes da emergência?

Se editar a solução depois de uma aprovação, execute os testes novamente.
