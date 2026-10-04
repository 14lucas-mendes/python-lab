# Mission 009 — Ler histórico de commits

Ciclo 3 · lesson_04-descoberta-processo

Um time colou a saída de `git log --oneline` num arquivo. Você não vai executar Git: vai ler o texto e extrair o que o histórico conta.

Cada linha tem um hash curto, um espaço e a mensagem. Muitas mensagens começam com um prefixo (`feat`, `fix`, `docs`, `chore`, `test`) seguido de dois pontos.

## Entrada

Uma string com várias linhas, no formato:

```
a1b2c3d feat: consolidar falhas
e4f5g6h fix: guardar lista vazia
```

Há um exemplo em `data/git_log.txt`.

## Saída

- `ler_historico(texto)` devolve uma lista de dicionários `{"hash": ..., "mensagem": ...}` na ordem do texto
- `contar_prefixos(commits)` devolve um dicionário `{prefixo: quantidade}` só para mensagens `prefixo: resto`

## Restrições

- Ignore linhas em branco.
- O prefixo é a palavra antes do primeiro `:`. Sem dois-pontos, a mensagem não entra na contagem.
- Não chame `git` nos testes nem na solução. Trabalhe só com o texto.

## Critérios de aceite

- Hash e mensagem são separados no primeiro espaço.
- A ordem dos commits é a do arquivo.
- Prefixos conhecidos são somados; mensagens sem `:` são ignoradas na contagem.

Edite `starter.py` e rode `/test`.
