# Mission 002 — Limpar relatório CSV

Um relatório operacional chegou com linhas incompletas. Você precisa ler o arquivo, aproveitar só o que for confiável e contar o que foi rejeitado.

## Entrada

Caminho para um CSV com as colunas `equipamento` e `minutos`.

## Saída

Um dicionário com:

- `validos`: quantidade de linhas aproveitadas
- `invalidos`: quantidade de linhas rejeitadas
- `totais`: soma de minutos por equipamento nas linhas válidas

## Restrições

- Uma linha inválida não pode abortar a leitura do restante.
- Arquivo vazio deve produzir totais vazios e contagens zero.
- Use a biblioteca padrão.

## Critérios de aceite

- CSV íntegro soma os minutos corretamente.
- Duração vazia ou não numérica conta como inválida.
- Campo ausente conta como inválido.
- Arquivo vazio não quebra a função.

Edite `starter.py` e rode os testes pelo Lab com `/test`.
