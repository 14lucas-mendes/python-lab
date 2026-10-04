# Mission 007 — Erros antes e durante a execução

Ciclo 2 · lesson_03-testes-git

Três módulos de um plantão chegaram quebrados. Um nem chega a executar: o interpretador recusa o arquivo. Os outros dois abrem, mas explodem quando uma função é chamada.

O objetivo não é só fazer o código passar. É perceber **quando** o erro aparece.

- Erro **antes** da execução: o arquivo não compila (`SyntaxError`).
- Erro **durante** a execução: o arquivo carrega, mas uma chamada levanta `TypeError` ou `NameError`.

## Entrada

Edite os três arquivos em `starter/`:

- `sintaxe.py`: `formatar_linhas(linhas)` devolve cada linha sem espaços nas pontas
- `tipos.py`: `formatar_total(minutos)` devolve um texto como `"12 min"`
- `nomes.py`: `primeiro_alerta(alertas)` devolve o primeiro alerta ou `None`

## Saída

As três funções passam nos testes. Na `/explain`, classifique cada erro: qual foi detectado antes da execução e quais só aparecem durante a execução.

## Restrições

- Não reescreva a intenção das funções; corrija o defeito.
- Não capture o erro só para escondê-lo. A função deve funcionar.

## Critérios de aceite

- `sintaxe.py` compila.
- `formatar_linhas` devolve as linhas limpas.
- `formatar_total(12)` devolve `"12 min"`.
- `primeiro_alerta` usa o nome certo da variável e trata lista vazia.

Edite os arquivos em `starter/` e rode `/test`.
