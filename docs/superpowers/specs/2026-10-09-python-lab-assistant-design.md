# Python Lab: assistente local e tutor — especificação proposta

Status: proposta para revisão; este documento não implementa funcionalidades. O pedido de plano autoriza a documentação desta especificação e dos planos associados. A execução do produto será uma etapa posterior.

## Objetivo e entendimento

Transformar o Lab em assistente de programação e apoio ao estudo de Python, inicialmente na CLI/TUI local, trabalhando em projetos do usuário. Preservar Goal/Skills/Missions, plano, testes, explicação e pistas progressivas. O usuário confirmou a interface local e solicitou diagnóstico, revisão/refatoração, criação de projetos e tutoria. A referência pyxl.pro não pôde ser inspecionada (HTTP 403); não se afirma equivalência com suas funcionalidades reais.

O núcleo será compartilhado por interfaces futuras. Extensão de IDE, web, modelo local, multiusuário, execução de código desconhecido em servidor e publicação automática ficam fora desta entrega.

## Entregas independentes

1. Base confiável: estado, migração, validação e execução de ferramentas.
2. MVP assistente/tutor: projeto, contexto, explicação e diagnóstico, com IA opcional.
3. Revisão e patches: análise verificável, aprovação explícita e proteção contra arquivos alterados.
4. Projetos: CLI/FastAPI primeiro; Flask, Django, biblioteca, bot e scraper depois, com templates testados.
5. Aprendizado: nível de assistência, exercícios revisados e recomendações determinísticas.

Cada entrega tem plano próprio. Concluir 1 e 2 já permite uma release útil; não é necessário implementar as demais para validar o MVP.

## Restrições globais

- Python >=3.11; manter rich>=13.7,<15, textual>=0.80,<1 e pytest>=8,<9 durante a primeira entrega.
- CLI/TUI local primeiro; preservar lab, python-lab, lab --classic e comandos de missões existentes.
- Português nas mensagens padrão; caminhos e código mostrados literalmente.
- Dados do usuário fora do checkout; dados legados preservados e importação transacional/idempotente.
- Testes automatizados de IA sem rede e sem credenciais; avaliação com modelo real é separada.
- Nenhum comando sugerido pela IA é executado como shell; ferramentas recebem argv explícito.
- Nenhuma alteração de projeto é aplicada sem escolha explícita do usuário e conferência do hash atual.
- Nenhuma competência é demonstrada automaticamente por uma resposta da IA ou por código gerado.
- Versões futuras dos extras de ferramentas/SDK devem ser resolvidas em constraints testadas na implementação; não mudar dependências existentes só para executar este planejamento.

## Base e persistência

`AppPaths(catalog_dir: Path, data_dir: Path)` separa conteúdo instalado do estado mutável. `resolve_paths(catalog_dir: Path, data_dir: Path | None) -> AppPaths` usa `--data-dir` quando informado e, caso contrário, diretório de dados do usuário via platformdirs. A dependência já é transitiva do Textual e passa a ser declarada diretamente quando o código a importar. Banco: `data_dir/lab.sqlite3`.

SQLite é acessado com uma conexão por operação/thread; não compartilhar conexão entre worker e UI. Habilitar foreign_keys e busy_timeout=5000; modo WAL no filesystem local. Progresso: uma linha com payload validado e revision inteiro. O read obtém payload/revision na mesma consulta; save usa transação e compare-and-swap. Writer desatualizado recebe ProgressError, sem substituir o estado novo. Sessions/events são linhas independentes por session_id, evitando sobrescrever o histórico de outra instância. Manter limites atuais de 20 sessões e 200 eventos; não remover sessão ainda aberta para cumprir retenção.

Preservar interfaces load/save de ProgressRepository e start/record/close de SessionLog, mas seus paths passam a indicar SQLite. Atualizar fixtures e chamadores; nunca abrir um JSON antigo como banco. SessionLog expõe current_session e is_open; close é idempotente. Progresso e sessão podem compartilhar o mesmo arquivo.

`migrate_json_state(legacy_dir: Path, database_path: Path) -> MigrationReport` valida UTF-8, tipos e relações antes de gravar. Copia os originais para backup dentro de data_dir e importa ambos em uma transação, somente para banco sem progresso/histórico de usuário. O marcador de origem/hash impede reimportação. Uma falha não substitui estado válido nem altera o JSON original. `lab migrate --from-dir DIR` é explícito; ao detectar legado na primeira abertura, orientar o comando em vez de ignorar progresso real. Seed vazio pode inicializar banco novo sem diálogo. Missão ativa removida do catálogo produz erro acionável; não apagar o registro.

## Ferramentas e runner

`ProcessRunner.run(argv: Sequence[str], cwd: Path, *, timeout: float=30.0, output_limit: int=1048576, cancel: Event | None=None) -> ProcessResult` mantém shell=False, timeout, cancelamento, coleta limitada e encerramento da árvore de processos. Implementações POSIX/Windows devem ser testadas; não presumir que matar pytest encerra os filhos. ProcessResult contém return_code, output, timed_out, cancelled e truncated.

Continuar interpretando JUnit de cada execução; zero testes, erros, skipped ou relatório inválido não aprovam evidências. Truncamento de apresentação não altera o resultado JUnit. O runner local não é sandbox de segurança para código desconhecido.

## Contexto e contratos de assistência

`Workspace(root: Path).snapshot(paths: Sequence[Path]) -> WorkspaceSnapshot`: aceitar somente arquivos selecionados, UTF-8, dentro de root após resolver symlinks; respeitar .gitignore em repos Git. Excluir .git, .venv, __pycache__, .env, .env.*, *.pem e *.key. Limites: 20 arquivos, 32768 bytes por arquivo e 131072 bytes totais. Exceder limite gera ContextError, sem enviar dados silenciosamente truncados. Git é opcional fora de um repo; nesses casos continuam valendo seleção explícita e exclusões fixas.

`SourceFile(path: str, text: str, sha256: str)` usa path relativo POSIX. WorkspaceSnapshot contém root e sources. IDs de conversa por workspace resolvido, sem compartilhar contexto entre projetos. Não indexar o repo inteiro nem adicionar banco vetorial no MVP.

Contratos em assistant/models.py:

- `AssistantMode = Literal['assistant', 'tutor']`; `Action = Literal['explain', 'diagnose', 'review', 'exercise']`.
- `CodeReference(path: str, start_line: int, end_line: int)` deve referenciar intervalo existente no snapshot.
- `AssistantRequest(action: Action, prompt: str, mode: AssistantMode, level: int, snapshot: WorkspaceSnapshot, traceback: str | None=None, mission_id: str | None=None)`; level 0..4. mission_id vem da sessão local, nunca da resposta do modelo.
- `AssistantAnswer(summary: str, explanation: str, steps: tuple[str, ...], references: tuple[CodeReference, ...], assistance_level: int, usage: Usage)`.
- `Usage(input_tokens: int, output_tokens: int)`; limites e valores não negativos.
- `LLMProvider.generate(request: AssistantRequest) -> Awaitable[AssistantAnswer]`.

IA não marca execução, correção ou teste como verificado. Apenas ProcessResult/TestResult de ferramenta executada pode fazê-lo. Persistir resposta, hashes e metadados de uso; não armazenar chave, configuração secreta ou cópia integral do contexto por padrão.

## Provedor e disponibilidade

Implementar primeiro OpenAIProvider via SDK oficial, em extra opcional `assistant`. Configuração explícita em config.toml de data_dir: provider='openai', model obrigatório, timeout_seconds=30, max_output_tokens=2000, max_session_output_tokens=20000. O modelo será escolhido pelo usuário/configurador; não presumir disponibilidade de uma versão. Chave lida somente de LAB_API_KEY, nunca do TOML ou histórico. No ambiente cloud, sua configuração segura é trabalho posterior; não solicitar valores em chat.

SDK só é importado ao construir o provedor. Sem extra, chave ou modelo, missões/testes/análise local continuam disponíveis e ações de IA mostram orientação curta. Sem retry automático no MVP; assim o custo e o cancelamento são previsíveis. Falha, timeout, limite ou resposta fora do schema geram AssistantError sem traceback na interface. O orçamento de sessão limita tokens de saída: reservar max_output_tokens antes de enviar, ajustar pelo usage recebido e manter a reserva se o uso real for desconhecido. Tokens de entrada são reportados separadamente. Documentar que isso não é teto de custo monetário total.

## Modos e interação

Tutor é padrão dentro de missão, assistant fora dela. Pistas: 0 pergunta, 1 conceito, 2 orientação, 3 exemplo parcial, 4 solução completa somente quando solicitada. Prompts e respostas estruturadas ajudam a aplicar a política; eficácia pedagógica requer avaliação humana, não promessa de controle perfeito do modelo.

CLI proposta: `lab --project DIR`, `lab explain FILE`, `lab diagnose --traceback FILE --file SOURCE`, `lab check FILE` e `lab review FILE`. Ações externas aceitam --project, --mode, --data-dir e --json; argparse usa nomes reais definidos no plano. Explain/diagnose aceitam --level 0..4; nível 4 é pedido explícito de solução. Traceback UTF-8 selecionado explicitamente tem limite de 32768 bytes; prompt+traceback+sources têm limite combinado de 131072 bytes. Exit codes: 0 ação concluída (mesmo se houver achados), 2 uso/configuração inválida, 1 falha de execução. Schema JSON inclui schema_version=1.

TUI preserva comandos existentes e acrescenta /project DIR, /mode assistant|tutor, /explain-code FILE, /diagnose TRACEBACK SOURCE, /check FILE e /review FILE. Explain-code/diagnose aceitam --level 0..4. Paths com espaços usam parser baseado em shlex com cobertura Windows. Um worker por ação; status/progresso visível, cancelamento acessível, entrada novamente utilizável após erro. Nunca executar Console.input dentro de callbacks da TUI. Uma resposta de nível 4 vinculada à missão já marca reference_viewed no MVP; o acompanhamento detalhado vem na entrega de aprendizado.

## Revisão e patches

AnalysisService combina AST, `ruff check --output-format json`, `ruff format --check` e `mypy` opcional, somente nos sources .py; ferramentas ausentes produzem status unavailable. AST usa o texto capturado; ferramentas que leem disco exigem hashes iguais antes/depois para associar achados ao snapshot. Mypy usa configuração controlada sem plugins do projeto. Execução de pytest para projeto depende de seleção explícita do usuário; código do projeto roda com seus privilégios. Testes e respostas se associam ao hash do snapshot.

PatchProposal contém ID, mudanças tipadas por arquivo, hashes-base, justificativa e selected_paths derivado do snapshot local, nunca do modelo. Cada FileChange(path, before_sha256, after_text) é substituição completa de arquivo selecionado; MVP não suporta delete/rename. after_text contém texto UTF-8, validado, e tamanho dentro dos limites do contexto. PatchService valida todos os paths/hash antes de escrever, produz diff e aplica com backups/rollback em falha. Confirmação reconfere hashes. No MVP, suportar um arquivo por aplicação; patches múltiplos são propostas separadas para não prometer transação entre arquivos. `lab apply ID --yes` confirma; /apply ID abre modal. Verificação posterior é escolhida explicitamente; status unverified/failed/passed depende da ferramenta, nunca da opinião do modelo.

## Projetos e aprendizado

`ScaffoldService.create(template: str, target: Path) -> ScaffoldResult` só cria destino inexistente; templates empacotados incluem pyproject, README, tests e .gitignore. Registro inicial: cli e fastapi. Não instalar nem executar automaticamente código/dependências gerados. README contém comandos exatos de instalação, testes e execução. Depois adicionar flask, django, library, bot e scraper como templates separados, cada um com smoke e testes. Bot inicial é echo local sem token; integrações Telegram/Discord ficam fora da primeira geração. Scraper inicial transforma HTML local; requisições HTTP são evolução explícita.

AssistanceEvent registra mission_id opcional, action, level, timestamp e request_id. Level 4 ou aplicação de patch marca tentativa como assistida e reference_viewed para compatibilidade; uma resposta jamais conclui missão. Recomendações usam os estados atuais e priorizam missões desbloqueadas com tentativas/pistas, sem gerar nota fictícia. Exercícios de IA são drafts, com enunciado, critérios, testes e referência, revisados pelo usuário e verificados antes de entrar no catálogo; não publicar automaticamente nem abrir referências no fluxo normal.

## Critérios gerais de aceite

- Manter os comportamentos dos 123 testes do baseline; atualizar contratos de armazenamento sem remover sua cobertura.
- Referências das 11 missões e jornadas reais 001/006 passam.
- Cobrir atualização simultânea, legado inválido, modal vazio, erro de histórico, descendentes, cancelamento, limites de contexto e patch desatualizado.
- Rodar Ubuntu e Windows em Python 3.11/3.12; nenhum segredo/rede necessários para a suíte.
- Avaliação manual de IA em casos pequenos de sintaxe, nome, tipo, importação, lógica e falha pytest; avaliar referência ao código, utilidade e nível de ajuda, sem exigir igualdade textual.
- Smoke dos templates em ambiente limpo; sucesso de scaffolding não significa aplicação pronta para deploy.

## Origem e planos

Base: revisão em docs/reviews/2026-10-09-production-readiness.md, commit c6c9fd7 e proposta de produto desta conversa. Índice: ../plans/2026-10-09-python-lab-implementation.md. Escolhas de SQLite, provedor OpenAI inicial e limites são defaults concretos propostos para revisão, não funcionalidades existentes.
