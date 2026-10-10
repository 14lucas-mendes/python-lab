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
| `Ctrl+C` | Cancelar a ação ativa (aguarda limpeza); sem ação, salvar e encerrar |

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
| `/project <diretório>` | | Abrir projeto do assistente; `/project off` retorna às missões |
| `/mode assistant|tutor` | | Escolher modo da assistência |
| `/explain-code <arquivo>` | | Explicar código selecionado |
| `/diagnose --traceback <arquivo> --file <fonte>` | | Diagnosticar erro com contexto selecionado |
| `/check <arquivo>` | | Executar verificação local |
| `/cancel` | | Cancelar a ação ativa |
| `/help` | `/?` | Listar comandos disponíveis |
| `/exit` | `/q` | Salvar e encerrar com segurança |

## Assistente local (opcional)

`lab` sem `--project` continua abrindo as missões. `lab --project "C:\meus projetos\app"` abre a TUI no projeto indicado; o catálogo das 11 missões permanece separado. Use `/project <diretório>` para trocar de projeto e `/project off` para voltar à vista de missões. `tutor` é o modo padrão durante uma missão ativa; `assistant` é o padrão fora de missões. `/mode assistant|tutor` ou `--mode` escolhe um modo explícito que permanece na sessão. A missão ativa é preservada na troca de vista. `/explain` continua registrando a explicação **do aluno** e pode concluir a missão; `/explain-code` apenas explica arquivos selecionados e nunca conclui uma missão.

Ações de terminal de uma só execução:

```bash
lab check src/app.py --project "/caminho/com espaços/projeto" --json
lab explain src/app.py --project "/caminho/projeto" --mode tutor --level 0
lab diagnose --traceback erro.txt --file src/app.py --project "/caminho/projeto"
```

`--data-dir` escolhe o diretório local de configuração e histórico; `--json` retorna `schema_version: 1`, `action`, `ok`, `message` e `data`. Códigos de saída: 0 para verificação concluída (mesmo com achados), 2 para uso/configuração, 1 para falha de execução. Cada invocação `lab explain` ou `lab diagnose` começa um orçamento novo; TUI e prompt clássico compartilham um provider e orçamento por sessão local. `check` roda localmente sem chave, modelo ou SDK. Achados incluem ferramentas indisponíveis; sem o extra de análise, a análise continua usando seus checks locais disponíveis.

Para respostas de IA, instale o extra opcional e crie `config.toml` no diretório de dados do usuário:

```toml
provider = "openai"
model = "NOME-DO-MODELO-ESCOLHIDO"
timeout_seconds = 30
max_output_tokens = 2000
max_session_output_tokens = 20000
```

```bash
python -m pip install -c constraints/dev.txt -c constraints/assistant.txt -e '.[assistant]'
export LAB_API_KEY='sua chave'  # configure no ambiente seguro; nunca no TOML
```

No PowerShell, configure `LAB_API_KEY` como variável de ambiente do processo antes de iniciar `lab`. Nenhum modelo é escolhido automaticamente e a chave nunca entra no TOML. As respostas dependem de rede e consomem tokens; o limite configurado cobre tokens de **saída** por sessão, não custo total. Não há repetição automática após erro. Cada seleção é explícita e limitada a 20 arquivos, 32768 bytes por arquivo e 131072 bytes no total. Código, traceback e respostas são exibidos como texto literal; explicação, diagnóstico e revisão preservam os arquivos do projeto. Somente a aplicação confirmada de uma proposta altera um arquivo, sem concluir missão. Na TUI, `/cancel`, o botão Cancelar ou Ctrl+C interrompem a ação e aguardam a limpeza antes de liberar o campo. Ctrl+C durante `/test` aguarda a limpeza do processo de testes antes de sair. No prompt clássico, `/cancel` pode ser digitado enquanto a análise ou a resposta está em curso; o próximo comando só é aceito após a limpeza.

## Revisão, aplicação e verificação

```bash
lab review arquivo.py --project /caminho/do/projeto
lab apply ID --project /caminho/do/projeto
lab apply ID --yes --project /caminho/do/projeto
lab verify ID --check ast --check ruff --project /caminho/do/projeto
lab verify ID --check pytest --project /caminho/do/projeto
lab new cli meu-app --path /diretorio/pai
lab new fastapi minha-api --path /diretorio/pai
```

Na TUI e no prompt clássico, use `/review`, `/apply`, `/verify` e `/new` com
os mesmos argumentos. A revisão funciona sem IA: mostra a análise local e informa
que a IA está indisponível, sem inventar sugestões. Com o assistente configurado,
mostra propostas com ID local, destino resolvido e diff literal. Cada proposta
altera apenas um arquivo selecionado. A CLI exige `--yes`; sem essa opção exibe
o diff e preserva os bytes. A TUI sempre abre uma confirmação com destino e diff;
Cancelar ou Esc preservam o arquivo. Uma edição posterior à revisão exige nova
proposta. IDs pertencem ao workspace original; mantenha `--project` e `--data-dir`
entre as invocações.

Review e apply deixam a proposta **não verificada**. `verify` só executa os
checks explicitamente selecionados (`ast`, `ruff`, `pytest`); sem `--check`, retorna
não verificada. **`--check pytest` autoriza descoberta e execução dos testes e
conftest do projeto no diretório raiz resolvido exibido, com seus privilégios.**
Revisão, aplicação e checks padrão não executam pytest. Os resultados distinguem
falhas de assertions, infraestrutura indisponível, timeout e cancelamento nos
detalhes dos checks. A aprovação corresponde ao hash aplicado e às fontes
selecionadas daquele snapshot; novas edições invalidam esse resultado.

Aplicar a solução editável da missão ativa registra ajuda completa, sem produzir
evidência de teste ou concluir missão. Continue com `/test` e `/explain` para as
evidências da missão. Comandos externos aceitam `--json` (schema_version 1):
código 0 para resultado/findings, 2 para uso/configuração inválidos e 1 para falha
de execução. `--help` e `--version` dispensam configuração e SDK.

`new` usa apenas templates do registro curado, cria um destino inexistente e
imprime os arquivos e próximos comandos. Não instala dependências nem executa
código. Siga as instruções do README gerado para preparar o ambiente e iniciar
a CLI ou o FastAPI. A sessão compartilha um provider e orçamento opcionais entre
explicação, diagnóstico e revisão.

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

Os comandos são interpretados igualmente no prompt clássico e na TUI. Aspas simples ou duplas agrupam argumentos; caminhos Windows mantêm as barras invertidas. `/project` seleciona um workspace do assistente sem mudar o catálogo de missões.

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

O workflow primeiro prova ajuda, versão e missão clássica sem extras; depois instala os extras opcionais de análise e SDK oficial sob as constraints e roda provas offline com mocks. A existência do workflow não confirma uma execução: os resultados de cada célula dependem do CI. Não é necessário instalar SDK de assistente para ajuda, versão, missões, prática clássica ou `check`.

Os scaffolds curados `cli` e `fastapi` estão disponíveis pela API
`ScaffoldService().create(template, Path(destino))`, em `python_lab.scaffolding`.
O destino deve ser inexistente e ter nome Python válido (hífens viram underscores
no pacote). Nomes que conflitam com módulos da biblioteca padrão ou com as
dependências e ferramentas conhecidas do template são rejeitados antes da criação.
A geração lê recursos empacotados e só cria arquivos: instalação e execução ficam
nos comandos Linux/Windows do README gerado.

A suíte normal mantém a geração offline e pula os smokes que instalam
projetos, incluindo as regressões de nomes que contêm tokens literais do template.
Para validar o artefato suportado (checkout instalado em modo editável),
execute separadamente a preparação e os testes funcionais em um venv novo por
template; esse comando acessa o índice de pacotes na instalação:

```bash
PYTHON_LAB_TEMPLATE_SMOKE=1 .venv/bin/python -m pytest tests/test_template_smoke.py -q -s
```

No PowerShell, defina `$env:PYTHON_LAB_TEMPLATE_SMOKE = "1"` e use
`.venv\Scripts\python.exe -m pytest tests/test_template_smoke.py -q -s`.
O CI executa esse estágio separado com `constraints/template-smoke.txt`, sem
adicionar dependências de framework ao runtime obrigatório do Lab. Os smokes
verificam a saudação CLI e `GET /health` com cliente interno, sem chaves ou
requisições externas após a instalação. A execução independente de um wheel do
Lab ainda não é coberta: o catálogo de missões exige o checkout editável.
