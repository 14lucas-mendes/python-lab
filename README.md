# Python Lab v0.3

Ambiente pessoal de prática deliberada em Python. O Lab não mede conteúdo consumido: ele registra competências demonstradas por meio de missões com planejamento, testes e explicação final.

A interface padrão é uma TUI centrada na missão: cabeçalho e etapas persistentes, conteúdo rolável, último resultado, ações da etapa e campo de comandos. O histórico fica acessível por `/session`. O prompt `lab>` continua disponível com `lab --classic`.

## Tripé

- **Goal** — competência demonstrável em Python, automação e integrações.
- **Skills** — estados sustentados por evidências: não avaliada, em prática, demonstrada, consolidada.
- **Missions** — problemas contextualizados com contrato verificável.

## Instalação (Windows / PowerShell)

Use o interpretador 3.11 com o qual o ambiente foi criado. Se `py -3.11` não estiver disponível, ative o `.venv` já existente.

```powershell
.venv\Scripts\python.exe -m pip install -c constraints\dev.txt -e ".[dev]"
```

Para abrir o Lab de qualquer pasta, sem ativar o venv:

```powershell
uv tool install --editable --constraint constraints\dev.txt ".[dev]"
```

Se o `uv` não estiver no PATH, use o script que adiciona `.venv\Scripts` ao PATH do usuário:

```powershell
.\scripts\install-lab.ps1
```

O script confere Python >=3.11, metadados e `lab --version`, inclusive o código de saída, antes de alterar o PATH. `-CheckOnly` valida a instalação sem gravar o PATH.

Abra um terminal novo e rode:

```powershell
lab
```

Atalhos equivalentes: `python-lab` e `python lab.py` (a partir do repositório). `lab --classic` abre o prompt linha a linha da v0.2.

A v0.3 é suportada a partir do checkout do repositório (inclusive pela instalação editável acima). O wheel ainda não é um artefato suportado, porque o catálogo de missões e seus dados vivem fora do pacote Python.

## Ciclo de uma sessão

1. `lab` abre a TUI com a missão atual e o próximo passo no rodapé. Uma missão em andamento já abre com o enunciado.
2. Digite `/` para ver os comandos. `/mission 001` consulta o enunciado sem iniciar; `/start 001` inicia uma missão desbloqueada.
3. `/plan` registra entrada, saída, etapas e possíveis erros.
4. Edite `starter.py` (ou o pacote em `starter/` na missão 005) no Cursor. O caminho do arquivo editável aparece no enunciado.
5. `/test` executa o pytest da missão depois que o planejamento estiver completo. A tela mostra resumo e diagnósticos; `/test details` apresenta a saída completa sem executar novamente.
6. `/hint` libera pistas progressivas depois da primeira execução de testes, se precisar.
7. `/explain` registra a explicação final quando os testes passam. Se plano, testes e explicação estiverem completos, a missão é concluída na hora, com evidências; se faltar algo, a TUI diz o que está pendente.
8. A missão só conclui com plano, testes e explicação.

O rodapé mostra `Próximo:` depois de cada ação.

Se você editar a solução depois de uma execução aprovada, rode `/test` novamente antes de `/explain`.

A TUI verifica periodicamente se a solução mudou e atualiza a indicação de testes atuais. O planejamento permite várias linhas nos campos de etapas e riscos. Esc cancela o formulário sem salvar.

## Piloto didático: missões 001 e 006

Essas duas missões incluem objetivo observável, conhecimentos necessários, exemplos de entrada e saída, critérios de aceite e perguntas para a reflexão final. A edição da solução continua no Cursor; o Lab apresenta o problema e registra suas tentativas.

Use `/concepts` para revisar conceitos da missão atual ou `/concepts 001` para consultar outra missão. O apoio é opcional, pode ser lido antes de testar e não contabiliza uma pista. `/mission` retoma o enunciado. Sem missão atual, informe um ID; consultar uma missão bloqueada não a inicia nem a desbloqueia.

As perguntas de reflexão aparecem no `/explain`, que continua recebendo uma resposta textual única. As regras de conclusão, pistas e evidências permanecem as mesmas. Os detalhes dos testes ficam apenas na memória da sessão, separados por missão; ao fechar o Lab, a saída completa deixa de estar disponível.

### Conteúdo opcional para autores

`mission.json` aceita `learning_objectives` e `reflection_questions`, listas opcionais de textos não vazios. O catálogo encontra o enunciado em `README.md` e o apoio em `concepts.md`, na pasta da missão. Conteúdo ausente recebe uma mensagem explicativa e não impede carregar missões antigas.

O piloto deve ser observado em sessões reais antes de aplicar esse padrão às outras missões. Verifique se o aluno encontra o contrato e o arquivo editável, consulta apoio sem se perder e explica as decisões da solução. Testes aprovados verificam funcionamento técnico, não eficácia didática.

No relatório CSV, linhas sem identificador de equipamento são consideradas inválidas.

## TUI

O campo de baixo aceita os mesmos comandos com barra da CLI. Digite `/` para filtrar a lista; Enter escolhe o item destacado. `/start` completa o comando e espera o id da missão.

| Tecla | Ação |
|---|---|
| `/` | Abrir e filtrar a lista de comandos |
| `Enter` | Executar o comando ou escolher o item do menu |
| `Esc` | Fechar o menu ou limpar o campo |
| `PageUp` / `PageDown` | Rolar o conteúdo mantendo o campo de comandos ativo |
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
| `/mission [id]` | | Consultar o enunciado sem iniciar a missão |
| `/concepts [id]` | | Consultar apoio conceitual opcional |
| `/plan` | `/p` | Registrar ou revisar o planejamento |
| `/test` | `/t` | Executar os testes da missão atual |
| `/test details` | | Exibir a saída completa sem nova tentativa |
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

O progresso e o histórico de sessões ficam juntos em `lab.sqlite3`, no diretório de dados do usuário fora do checkout. Use `lab --data-dir <pasta>` para escolher uma pasta; sem override, o Lab usa o diretório de dados da plataforma. A escolha do catálogo e a dos dados são independentes.

Se houver progresso JSON legado no checkout, migre explicitamente:

```powershell
lab migrate --from-dir .\data --data-dir C:\MeusDados\python-lab
```

A importação preserva os JSON e cria backups; repetir a mesma importação não duplica os registros. Não faça commit dos dados reais.

Para ajuda fora da sessão, use `lab --help`. O ambiente suportado é Python 3.11 ou mais recente; pytest é instalado pelo extra `dev` e é necessário para executar as missões.

## Desenvolvimento e validação

Os comandos são interpretados igualmente no prompt clássico e na TUI. Aspas simples ou duplas agrupam argumentos; caminhos Windows mantêm as barras invertidas. `/project` fica reservado para uma etapa futura e ainda não executa ações.

Instalação Linux a partir do checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints/dev.txt -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python -m pytest -ra
.venv/bin/lab --help
.venv/bin/lab --version
```

No Windows, use `.venv\Scripts\python.exe` e `.venv\Scripts\lab.exe`. `constraints/dev.txt` foi gerado no ambiente Linux Python 3.12, mantendo os limites declarados em `pyproject.toml`; as quatro células do workflow verificam instalação editável e suíte completa em Ubuntu/Windows com Python 3.11/3.12. Os testes incluem as 11 referências, jornadas reais 001/006, entrada/saída da TUI e cancelamento de árvores de processos. Ubuntu precisa de `cc` para a regressão nativa de threads. No Windows, o job também executa PowerShell e testa validação, falhas e idempotência do instalador, restaurando o PATH do usuário.

A existência do workflow não confirma uma execução: os resultados de cada célula dependem do CI. Não é necessário instalar SDK de assistente para ajuda, versão, missões ou prática clássica.
