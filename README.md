# Python Lab v0.2

Ambiente pessoal de prática deliberada em Python. O Lab não mede conteúdo consumido: ele registra competências demonstradas por meio de missões com planejamento, testes e explicação final.

## Tripé

- **Goal** — competência demonstrável em Python, automação e integrações.
- **Skills** — estados sustentados por evidências: não avaliada, em prática, demonstrada, consolidada.
- **Missions** — problemas contextualizados com contrato verificável.

## Instalação (Windows / PowerShell)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python lab.py
```

Se `py -3.11` não estiver disponível, use o interpretador 3.11 com o qual o ambiente foi criado.

A v0.2 é suportada a partir do checkout do repositório (inclusive pela instalação editável acima). O wheel ainda não é um artefato suportado, porque o catálogo de missões e seus dados vivem fora do pacote Python; essa distribuição será revisitada quando esses recursos tiverem um contrato próprio.

## Ciclo de uma sessão

1. `python lab.py` mostra o Goal, a missão atual, a recomendada e o próximo passo.
2. `/start 001` inicia uma missão desbloqueada.
3. `/plan` (ou `/p`) registra entrada, saída, etapas e possíveis erros.
4. Edite `starter.py` (ou o pacote em `starter/` na missão 005) no VS Code.
5. `/test` (ou `/t`) executa o pytest da missão depois que o planejamento estiver completo.
6. `/hint` (ou `/h`) libera pistas progressivas depois da primeira execução de testes, se precisar.
7. `/explain` (ou `/e`) registra a explicação final quando os testes passam. Se plano, testes e explicação estiverem completos, a missão é concluída na hora, com evidências e a próxima missão indicada; se faltar algo, a CLI diz o que está pendente.
8. A missão só conclui com plano, testes e explicação.

A CLI imprime `Próximo:` depois de cada comando para indicar o passo seguinte do ciclo.

Se você editar a solução depois de uma execução aprovada, rode `/test` novamente antes de `/explain`.

No relatório CSV, linhas sem identificador de equipamento são consideradas inválidas.

## Comandos

| Comando | Atalho | Responsabilidade |
|---|---|---|
| `/goal` | `/g` | Exibir objetivo e critérios de sucesso |
| `/skills` | `/sk` | Exibir mapa de competências e evidências |
| `/missions` | `/ms` | Listar missões e estados |
| `/start <id>` | | Iniciar ou repetir uma missão desbloqueada |
| `/plan` | `/p` | Registrar ou revisar o planejamento |
| `/test` | `/t` | Executar os testes da missão atual |
| `/hint` | `/h` | Liberar a próxima pista |
| `/explain` | `/e` | Registrar a explicação final |
| `/status` | `/st` | Exibir estado da sessão |
| `/history` | `/hi` | Exibir histórico de tentativas da missão atual |
| `/session` | `/se` | Exibir o histórico desta sessão (`/session all` lista as anteriores) |
| `/evidence` | `/ev` | Exibir evidências de competências |
| `/help` | `/?` | Listar comandos disponíveis |
| `/exit` | `/q` | Salvar e encerrar com segurança |

Digite o comando com barra. Se você escrever `test` sem `/`, a CLI sugere `/test`.

`/history` é o histórico de tentativas de teste da missão atual. `/session` é a sequência de comandos desta execução do `python lab.py`.

## Ajuda e evidências

As pistas vêm em cinco níveis. Usar pistas não é fracasso. A quinta pista é a solução de referência e exige confirmação (`/hint confirm`). Consultar a referência impede que a tentativa atual marque a Skill como demonstrada; ela fica em prática.

As soluções de referência ficam em cada pasta de missão (`reference_solution.py` ou `reference_solution/`). Não as copie para `starter.py` se quiser evidência de competência.

## Progresso

O progresso fica em `data/progress.json`, gravado de forma atômica. O histórico de sessões fica em `data/sessions.json`. Não faça commit do progresso real nem do histórico de sessões: o arquivo versionado de progresso é só o seed vazio, e `data/sessions.json` está no `.gitignore`.

Para ajuda fora da sessão, use `python lab.py --help`. O ambiente suportado é Python 3.11 ou mais recente; pytest é instalado pelo extra `dev` e é necessário para executar as missões.
