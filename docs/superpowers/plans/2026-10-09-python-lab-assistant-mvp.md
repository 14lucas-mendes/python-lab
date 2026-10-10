# Python Lab Assistant and Tutor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explicar código e diagnosticar erros em projetos locais, com tutor e IA opcional, sem alterar arquivos.

**Architecture:** Workspace produz contexto delimitado; AnalysisService produz achados locais; AssistantService orquestra provedor tipado e histórico. CLI/TUI usam o mesmo comando e cancelamento, preservando sessões de missões.

**Tech Stack:** Python >=3.11, asyncio, AST, SDK OpenAI opcional, Ruff/Mypy opcionais e SQLite da entrega A.

**Spec:** [Design](../specs/2026-10-09-python-lab-assistant-design.md), seções Contexto, Provedor, Modos e critérios.

## Global Constraints

- Depende de A1–A5; não executar com migração/persistência pendentes.
- Contexto: 20 arquivos, 32768 bytes por arquivo, 131072 bytes combinados; seleção explícita.
- Provider opcional; chave LAB_API_KEY fora do TOML; model obrigatório e sem default inventado.
- Timeout 30 s, max_output_tokens=2000, max_session_output_tokens=20000; sem retry automático.
- Nenhuma escrita de projeto ou conclusão automática de missão; nível 4 exige pedido explícito.

## Review Focus

- Symlink/arquivo ignorado não sai do perímetro do projeto (B1).
- Tool ausente não vira sucesso nem bloqueia AST local (B2).
- Chave ausente, resposta inválida e orçamento não derrubam missões (B3).
- Referência inventada e texto de traceback não são instruções de execução (B4).
- Cancelamento libera UI e não grava resposta parcial como concluída (B5).

---

## Mapa de arquivos

- Criar `assistant/{__init__.py,errors.py,models.py,workspace.py,settings.py,provider.py,openai_provider.py,policy.py,service.py,history.py}` sob python_lab/.
- Criar `analysis/{__init__.py,models.py,service.py}` para achados locais.
- Criar `assistant/commands.py` e integrar commands.py/cli.py/tui/app.py em B5.
- Testes usam provider controlado, subprocessos locais e banco temporário; nenhum segredo é necessário.

### B1 — Contexto explícito e tipos compartilhados

**Files:** criar assistant/models.py, workspace.py, errors.py e __init__.py; criar tests/test_workspace.py e tests/test_assistant_models.py.

**Interfaces:** produzir SourceFile, WorkspaceSnapshot, CodeReference, Usage, AssistantRequest e AssistantAnswer exatamente como na spec. `Workspace(root: Path).snapshot(paths: Sequence[Path]) -> WorkspaceSnapshot`; `ContextError`/`AssistantError` como erros públicos. Helper `validate_answer(payload: Mapping[str, object], snapshot: WorkspaceSnapshot) -> AssistantAnswer` rejeita tipos inválidos, level fora de 0..4, usage negativo, references ausentes do contexto e linhas fora dos arquivos.

- [ ] **Testes RED:** testar path traversal, symlink para arquivo externo, .gitignore, .env/.pem, binário, 21 arquivos, 32769 bytes e total >131072. `test_response_reference_must_exist` exige AssistantError para linha inexistente. Arquivo válido conserva texto/hash e path relativo.

```python
def test_external_path_is_rejected(tmp_path):
    root = tmp_path / "project"; root.mkdir()
    outside = tmp_path / "outside.py"; outside.write_text("x=1\n")
    with pytest.raises(ContextError):
        Workspace(root).snapshot([outside])
```

- [ ] **Rodar RED:** `python -m pytest tests/test_workspace.py tests/test_assistant_models.py -q`.
- [ ] **Implementar:** paths resolvidos, seleção limitada, exclusões fixas e Git check-ignore para repos; sem Git, manter limites/perímetro. Hash dos bytes enviados, não segunda leitura. Não varrer o repo inteiro, não truncar silenciosamente e não executar conteúdo.
- [ ] **Rodar GREEN:** mesmos testes; incluir UTF-8 e arquivo alterado durante leitura como snapshot consistente dos bytes capturados.
- [ ] **Commit:** `git commit -m "feat: build bounded project context for assistant"` com módulos/testes da tarefa.

### B2 — Ferramentas locais e achados estruturados

**Files:** criar analysis/models.py, service.py e __init__.py; modificar pyproject.toml; criar tests/test_analysis.py.

**Interfaces:** consumir WorkspaceSnapshot e ProcessRunner. `Issue(path: str, line: int | None, code: str, message: str, source: str)`; `ToolCheck(tool: str, status: Literal['passed','failed','unavailable'], issues: tuple[Issue, ...])`; `AnalysisReport(checks: tuple[ToolCheck, ...])`; `AnalysisService.inspect(snapshot: WorkspaceSnapshot, *, typing: bool=False) -> AnalysisReport`.

- [ ] **Testes RED:** AST identifica SyntaxError sem SDK/Ruff; tools ausentes geram unavailable. Fake output Ruff JSON conserva path/linha/código; Mypy só roda quando typing=True. `test_project_code_is_not_imported` usa módulo que escreve marker ao importar; marker deve permanecer ausente. Arquivos README/TOML selecionados não recebem análise de sintaxe Python. `test_changed_source_invalidates_tool_results` modifica a fonte durante o runner fake e exige ContextError, sem associar achados ao hash antigo.

```python
def test_inspection_does_not_import_code(tmp_path):
    path = tmp_path / "demo.py"
    marker = tmp_path / "executed"
    path.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    AnalysisService().inspect(Workspace(tmp_path).snapshot([path]))
    assert not marker.exists()
```

- [ ] **Rodar RED:** `python -m pytest tests/test_analysis.py -q`.
- [ ] **Implementar:** AST sempre disponível, aplicado ao texto capturado dos sources .py; extra analysis para Ruff/Mypy com versões resolvidas/testadas em constraints. Invocar ferramentas por argv, cwd do snapshot e arquivos .py selecionados; conferir seus hashes antes/depois e recusar resultado desatualizado. Mypy usa configuração controlada sem plugins do projeto. Não fazer `ruff --fix`, import de módulos do usuário nem pytest automático. Mensagens de sintaxe são achados, não AssistantError.
- [ ] **Rodar GREEN:** testes fake + smoke real de Ruff/Mypy no extra instalado e teste sem extra. Registrar separadamente absent/passed/failed.
- [ ] **Commit:** `git commit -m "feat: inspect Python projects with local tools"`.

### B3 — Provider, configuração e orçamento

**Files:** criar assistant/settings.py, provider.py, openai_provider.py; modificar pyproject.toml e constraints/assistant.txt na implementação; criar tests/test_assistant_provider.py, test_assistant_settings.py e tests/helpers/{__init__.py,assistant.py}; adicionar tests/__init__.py para imports explícitos dos helpers.

**Interfaces:** `AssistantSettings(provider: str, model: str | None, timeout_seconds: int=30, max_output_tokens: int=2000, max_session_output_tokens: int=20000)`; `load_settings(data_dir: Path) -> AssistantSettings`; Protocol LLMProvider.generate conforme spec. `OpenAIProvider(settings: AssistantSettings)` lê LAB_API_KEY apenas na construção. `UsageBudget(limit: int).reserve(tokens: int) -> str`, `.settle(reservation: str, output_tokens: int | None) -> None`; entrada reportada separadamente. Helpers `RecordingProvider(answer: AssistantAnswer)` guarda requests; `BlockingProvider(started: asyncio.Event)` bloqueia até cancelamento, sem rede. `sample_request(snapshot: WorkspaceSnapshot, *, level: int=0, mission_id: str | None=None) -> AssistantRequest` usa action=explain, prompt='Explique', mode=tutor. `sample_answer(snapshot: WorkspaceSnapshot, *, level: int=0) -> AssistantAnswer` usa referência real à linha 1 do primeiro source e Usage(10, 5).

- [ ] **Testes RED:** sem SDK/chave/model, orientação de configuração e missões intactas; chave não aparece em erro/log. Resposta inválida, timeout, 429 e autenticação viram AssistantError, sem retry. Reserva insuficiente impede generate; usage desconhecido mantém reserva. Tests simulam SDK e validam schema/referências via B1.

```python
def test_output_budget_prevents_another_request():
    budget = UsageBudget(limit=20000)
    for _ in range(10):
        reservation = budget.reserve(2000)
        budget.settle(reservation, 2000)
    with pytest.raises(AssistantError, match="orçamento"):
        budget.reserve(2000)
```

- [ ] **Rodar RED:** `python -m pytest tests/test_assistant_provider.py tests/test_assistant_settings.py -q`.
- [ ] **Implementar:** extra assistant, SDK lazy, API suportada pelo SDK oficial e resposta estruturada convertida aos tipos B1. Config TOML via tomllib, nenhum segredo persistido. Timeout/cancelamento e UsageBudget envolvem cada requisição; sem execução de ferramentas via tool-calls do modelo no MVP.
- [ ] **Rodar GREEN:** testes sem rede com SDK fake; `lab --help` e suites de missão em venv sem extra. Smoke com modelo real é etapa manual opcional, usando configuração segura, e não substitui estes testes.
- [ ] **Commit:** `git commit -m "feat: add optional AI provider with usage controls"`.

### B4 — Serviços de diagnóstico, explicação e tutoria

**Files:** criar assistant/policy.py, service.py e history.py; adaptar app.py/learning.py para registrar ajuda completa associada à missão; criar tests/test_assistant_service.py e tests/test_tutor_policy.py.

**Interfaces:** consumir contratos B1/B2/B3. `TutorPolicy.prepare(request: AssistantRequest) -> AssistantRequest` define nível/prompt pedagógico; `ConversationRepository(database_path: Path).append(request: AssistantRequest, answer: AssistantAnswer) -> str`; `AssistantService(provider: LLMProvider, analysis: AnalysisService, history: ConversationRepository, *, on_full_solution: Callable[[str], None] | None=None).execute(request: AssistantRequest) -> Awaitable[AssistantAnswer]`. Callback `PythonLabApp.record_full_solution(mission_id: str) -> None` recebe ID local após resposta válida nível 4 e marca reference_viewed/persiste, sem concluir missão. Registro inclui workspace, hashes, modo, action, nível e usage, sem texto integral dos sources.

- [ ] **Testes RED:** requests explain/diagnose incluem contexto selecionado e checks locais; strings do traceback são dados. Sem resposta válida não persistir sucesso. `test_full_solution_marks_mission_assisted` exige callback só para mission_id presente +level4; `test_hint_does_not_complete_mission` exige current_mission/status intactos. Testar referências fora do contexto, limite combinado com traceback, persistência falha e modos sem contaminação entre projetos.

```python
def test_full_solution_marks_existing_mission(app, tmp_path):
    app.start("001")
    path = tmp_path / "demo.py"; path.write_text("x=1\n")
    snapshot = Workspace(tmp_path).snapshot([path])
    service = AssistantService(
        RecordingProvider(sample_answer(snapshot, level=4)), AnalysisService(),
        ConversationRepository(tmp_path / "assistant.sqlite3"),
        on_full_solution=app.record_full_solution)
    asyncio.run(service.execute(sample_request(snapshot, level=4, mission_id="001")))
    assert app.current_progress().reference_viewed
    assert app.progress.current_mission_id == "001"
    assert app.current_progress().status == "started"
```

Adicionar cenário com provider inválido que prova ausência de callback, e erro de persistência convertido para AssistantError antes de retornar sucesso.

- [ ] **Rodar RED:** `python -m pytest tests/test_assistant_service.py tests/test_tutor_policy.py -q`.
- [ ] **Implementar:** prompts por action/mode/level, validação do envelope, erros úteis, histórico por workspace. Sem validação por execução, escrever “sugestão”, nunca “corrigido/verificado”. Missões continuam exigindo plano/testes/explain; no MVP, nível4 integra a regra reference_viewed existente.
- [ ] **Rodar GREEN:** testes de service/policy + tests/test_learning.py e test_end_to_end.py. Avaliar manualmente seis classes de erro com modelo real quando disponível; não usar igualdade textual como métrica.
- [ ] **Commit:** `git commit -m "feat: diagnose and explain code with guided tutoring"`.

### B5 — CLI/TUI, cancelamento e release MVP

**Files:** criar assistant/commands.py; modificar commands.py, cli.py, tui/app.py, tui/screens.py, README.md; criar tests/test_assistant_cli.py, test_assistant_tui.py e test_assistant_journey.py.

**Interfaces:** adicionar `CommandDispatcher.register_async(name: str, handler: Callable[[tuple[str, ...]], Awaitable[CommandResult]]) -> None` e `.dispatch_async(command: Command) -> Awaitable[CommandResult]`, sem alterar dispatch dos comandos síncronos A5. `AssistantCommands(service: AssistantService, workspace: Workspace, mode: AssistantMode)` constrói requests e handlers; mode/request mission_id vêm da sessão local. Construção em cli.py seleciona serviço real ou erro unavailable sem importar SDK no modo legado.

- [ ] **Testes RED:** `lab explain FILE`, `lab diagnose --traceback FILE --file SOURCE`, `lab check FILE`, --project/--mode/--level/--data-dir/--json; JSON schema_version=1 e exit 0/1/2 conforme spec. TUI /project, /mode, /explain-code, /diagnose e /check usam mesmos handlers. `test_cancel_releases_composer` usa BlockingProvider, cancela após started e exige composer.disabled==False, sem histórico de resposta concluída. Projeto com espaços/Windows e arquivo ilegível têm erro útil.

```python
def test_missing_assistant_configuration_keeps_version_available(capsys):
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert "python-lab" in capsys.readouterr().out
```

- [ ] **Rodar RED:** `python -m pytest tests/test_assistant_cli.py tests/test_assistant_tui.py tests/test_assistant_journey.py -q`.
- [ ] **Implementar:** workers async canceláveis, progresso explícito, respostas/erros literais; /cancel disponível durante ação e Ctrl+C limpa worker antes de sair. /explain de missão continua distinto de /explain-code. Interação padrão sem --project continua mostrando missões; --project abre assistente. Documentar configuração local e limitações offline/token budget.
- [ ] **Rodar GREEN:** suite inteira, matriz CI e duas jornadas com RecordingProvider: diagnosticar erro → explicar causa; missão → hint → testes → explicação. Nenhuma modificação de projeto deve ocorrer no MVP.
- [ ] **Commit:** `git commit -m "feat: expose assistant and tutor in CLI and TUI"`.

## Aceite da entrega B

Usuário seleciona projeto/arquivo, recebe explicação/diagnóstico referenciado, alterna modo e cancela sem perder sessão. Sem IA, missões e checks locais funcionam. Tokens e ausência de verificação são visíveis. Avaliação pedagógica manual é registrada separadamente dos testes determinísticos; nova ajuda completa não gera evidência independente.
