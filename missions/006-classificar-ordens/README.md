# Mission 006 — Classificar ordens de serviço

Ciclo 1 · lesson_01-python-core

Uma central de manutenção recebe ordens de serviço e precisa classificá-las antes de encaminhar. A ordem das perguntas importa: a regra específica vem antes da geral, e você só lê o primeiro item depois de confirmar que a lista existe.

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

## Critérios de aceite

- Lista vazia ou ausente gera erro.
- Item bloqueado prevalece sobre emergência.
- Falha urgente é emergência; falha comum é corretiva.
- Preventiva e os demais tipos caem nas categorias certas.

Edite `starter.py` e rode os testes pelo Lab com `/test`.
