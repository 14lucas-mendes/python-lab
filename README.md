# Python Lab v0.3

Ambiente pessoal de prática deliberada em Python. O Lab não mede conteúdo consumido: ele registra competências demonstradas por meio de missões com planejamento, testes e explicação final.

A interface padrão é uma TUI no estilo Claude Code: histórico da sessão em cima e um campo de digitação embaixo. O prompt `lab>` continua disponível com `lab --classic`.

## Tripé

- **Goal** — competência demonstrável em Python, automação e integrações.
- **Skills** — estados sustentados por evidências: não avaliada, em prática, demonstrada, consolidada.
- **Missions** — problemas contextualizados com contrato verificável.

## Instalação (Windows / PowerShell)

Use o interpretador 3.11 com o qual o ambiente foi criado. Se `py -3.11` não estiver disponível, ative o `.venv` já existente.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Para abrir o Lab de qualquer pasta, sem ativar o venv:

```powershell
uv tool install --editable ".[dev]"
```

Se o `uv` não estiver no PATH, use o script que adiciona `.venv\Scripts` ao PATH do usuário:

```powershell
.\scripts\install-lab.ps1
```

Abra um terminal novo e rode:

```powershell
lab
```

Atalhos equivalentes: `python-lab` e `python lab.py` (a partir do repositório). `lab --classic` abre o prompt linha a linha da v0.2.

A v0.3 é suportada a partir do checkout do repositório (inclusive pela instalação editável acima). O wheel ainda não é um artefato suportado, porque o catálogo de missões e seus dados vivem fora do pacote Python.

## Ciclo de uma sessão

1. `lab` abre a TUI com o objetivo, a missão atual e o próximo passo no rodapé.
2. Digite `/` para ver os comandos. `/start 001` inicia uma missão desbloqueada.
3. `/plan` registra entrada, saída, etapas e possíveis erros.
4. Edite `starter.py` (ou o pacote em `starter/` na missão 005) no VS Code.
5. `/test` executa o pytest da missão depois que o planejamento estiver completo.
6. `/hint` libera pistas progressivas depois da primeira execução de testes, se precisar.
7. `/explain` registra a explicação final quando os testes passam. Se plano, testes e explicação estiverem completos, a missão é concluída na hora, com evidências; se faltar algo, a TUI diz o que está pendente.
8. A missão só conclui com plano, testes e explicação.

O rodapé mostra `Próximo:` depois de cada ação.

Se você editar a solução depois de uma execução aprovada, rode `/test` novamente antes de `/explain`.

No relatório CSV, linhas sem identificador de equipamento são consideradas inválidas.

## TUI

O campo de baixo aceita os mesmos comandos com barra da CLI. Digite `/` para filtrar a lista; Enter escolhe o item destacado. `/start` completa o comando e espera o id da missão.

| Tecla | Ação |
|---|---|
| `/` | Abrir e filtrar a lista de comandos |
| `Enter` | Executar o comando ou escolher o item do menu |
| `Esc` | Fechar o menu ou limpar o campo |
| `q` | Sair, se o campo estiver vazio |
| `Ctrl+C` | Salvar e encerrar |

A TUI lê os campos de texto em Unicode, então acentos no plano e na explicação são gravados corretamente.

## Prompt clássico

`lab --classic` mantém os comandos com barra da v0.2.

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

## Ajuda e evidências

As pistas vêm em cinco níveis. Usar pistas não é fracasso. A quinta pista é a solução de referência e exige confirmação. Consultar a referência impede que a tentativa atual marque a Skill como demonstrada; ela fica em prática.

As soluções de referência ficam em cada pasta de missão (`reference_solution.py` ou `reference_solution/`). Não as copie para `starter.py` se quiser evidência de competência.

## Progresso

O progresso fica em `data/progress.json`, gravado de forma atômica. O histórico de sessões fica em `data/sessions.json`. Não faça commit do progresso real nem do histórico de sessões: o arquivo versionado de progresso é só o seed vazio, e `data/sessions.json` está no `.gitignore`.

Para ajuda fora da sessão, use `lab --help`. O ambiente suportado é Python 3.11 ou mais recente; pytest é instalado pelo extra `dev` e é necessário para executar as missões.
