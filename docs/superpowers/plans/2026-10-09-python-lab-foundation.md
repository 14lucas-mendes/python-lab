# Python Lab Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolver os problemas de integridade e recuperação necessários para desenvolver o assistente sobre uma base confiável.

**Architecture:** Separar catálogo e estado, migrar persistência para SQLite transacional e preservar as interfaces de aplicação. Centralizar ferramentas em runner cancelável e entrada/erro em contratos compartilhados.

**Tech Stack:** Python >=3.11, sqlite3, platformdirs, Rich, Textual e pytest.

**Spec:** [Design](../specs/2026-10-09-python-lab-assistant-design.md), seções Base, Ferramentas, Modos e aceite.

## Global Constraints

- Python >=3.11; rich>=13.7,<15, textual>=0.80,<1, pytest>=8,<9.
- Dados fora do checkout; JSON legado preservado, com backup e importação idempotente.
- Preservar comandos e comportamentos das 11 missões; não editar starters/referências para fazer testes passar.
- Ferramentas usam argv/shell=False; timeout/cancelamento não aprovam evidências.

## Review Focus

- Legado UTF-8/tipo inválido permanece intacto (A1/A2).
- Writers simultâneos nunca confirmam estados incompatíveis (A2).
- Modal vazio e disco indisponível não acionam stdin nem derrubam interface (A3).
- Timeout encerra descendentes e limita output (A4).
- CLI/TUI e Windows mantêm contratos de comandos/erros (A5).

---

## Mapa de arquivos

- Criar `python_lab/storage/{__init__.py,errors.py,codecs.py,paths.py,database.py,migration.py}`: contratos de erro, estado validado, diretórios, schema e migração.
- Criar `python_lab/runtime/{__init__.py,processes.py,windows.py}`: execução e limpeza por plataforma.
- Criar `python_lab/commands.py`: parsing, resultados e dispatcher neutro.
- Adaptar `progress.py`, `session.py`, `app.py`, `cli.py`, `learning.py`, `catalog.py`, `tui/{app.py,screens.py,widgets.py}` e `test_runner.py` mantendo responsabilidades existentes.
- Criar testes citados abaixo; atualizar fixtures/chamadores atuais para SQLite e APIs públicas, mantendo os cenários de validação de JSON nos testes do importer.

### A1 — Paths e validação de estado

**Files:** criar storage/paths.py, storage/codecs.py, storage/errors.py e __init__.py; modificar pyproject.toml; criar tests/test_state_codecs.py e tests/test_paths.py.

**Interfaces:** produzir `AppPaths(catalog_dir: Path, data_dir: Path)`, `resolve_paths(catalog_dir: Path, data_dir: Path | None) -> AppPaths`; `decode_progress(raw: bytes) -> AppProgress`, `decode_sessions(raw: bytes) -> tuple[dict[str, object], ...]`. Errors reexportam ProgressError/SessionError nos módulos antigos em A2. Validar tipos antes de set membership; schemas de tentativa/evidência/evento recusam payload malformado com mensagem específica.

- [ ] **Testes RED:** adicionar o teste abaixo; `test_data_dir_is_outside_catalog` exige paths.data_dir==explicit_dir e catalog intacto. Parametrizar status=[], attempts=True, eventos malformados, evidence não lista, UTF-8 inválido e JSON inválido, com exceções de domínio.

```python
def test_invalid_utf8_is_a_domain_error():
    with pytest.raises(ProgressError, match="UTF-8"):
        decode_progress(b"\xff")
```

- [ ] **Rodar RED:** `python -m pytest tests/test_state_codecs.py tests/test_paths.py -q`; falha inicial por módulo/função ausente, não por ambiente quebrado.
- [ ] **Implementar:** paths explícitos/default via platformdirs; declarar platformdirs diretamente. Decodificar bytes uma vez; manter defaults do seed atual e aceitar schemas legados realmente existentes. Estado desconhecido não é recuperado como vazio.
- [ ] **Rodar GREEN:** mesmos testes; esperar todos aprovados. Verificar bytes originais com teste de migração em A2.
- [ ] **Commit:** `git add python_lab/storage pyproject.toml tests/test_state_codecs.py tests/test_paths.py && git commit -m "feat: separate data paths and validate legacy state"`.

### A2 — SQLite, concorrência e migração

**Files:** criar storage/database.py e migration.py; modificar progress.py, session.py, cli.py:465–478, tests/conftest.py e todos os construtores de repositório/session nos testes existentes; criar tests/test_state_migration.py e tests/test_storage_concurrency.py; atualizar tests/test_progress.py e test_session.py.

**Interfaces:** consumir A1. `ProgressRepository(path: Path).load() -> AppProgress`, `.save(progress: AppProgress) -> None` usam SQLite; `SessionLog(path: Path)` mantém load/start/record/close/current_events/previous_sessions e expõe `current_session: dict | None`, `is_open: bool`. `MigrationReport(imported: bool, backup_paths: tuple[Path, ...])`; `migrate_json_state(legacy_dir: Path, database_path: Path) -> MigrationReport`. `build_app(project_root: Path | None=None, *, data_dir: Path | None=None) -> PythonLabApp` preserva o override de catálogo e usa AppPaths para estado.

- [ ] **Testes RED:** transformar as reproduções R1/R2 em regressões. `test_simultaneous_progress_writers` inicia dois processos com snapshot igual e barreira: exatamente um save sucede, outro recebe ProgressError. `test_session_interleaving_preserves_both` exige dois IDs/eventos após start/start/record/close. `test_migration_is_idempotent` exige import único e JSON original idêntico; `test_bad_migration_rolls_back` exige banco anterior e arquivos intactos.

```python
def test_sessions_survive_interleaving(tmp_path):
    first = SessionLog(tmp_path / "lab.sqlite3")
    second = SessionLog(tmp_path / "lab.sqlite3")
    first.start(); second.start()
    first.record("/status", "A")
    second.record("/help", "B")
    assert len(first.load()) == 2
    assert {s["events"][0]["summary"] for s in first.load()} == {"A", "B"}
```

- [ ] **Rodar RED:** `python -m pytest tests/test_storage_concurrency.py tests/test_state_migration.py -q`; esperar perda de sessão/ausência do importer no código antigo.
- [ ] **Implementar:** schema/revision conforme spec; CAS dentro de transação, payload/revision na mesma leitura. Conexão por operação, busy_timeout=5000, foreign keys. Migração lê bytes únicos por origem, faz backup desses bytes fora do checkout e importa em uma transação com marcador; rejeita banco com estado de usuário. Adicionar `lab migrate --from-dir DIR --data-dir DIR`. Não remover validação antiga: transferi-la aos codecs/importer.
- [ ] **Rodar GREEN:** testes novos + `python -m pytest`; adaptar tests/test_end_to_end.py, test_pilot_journey.py, test_didactic_pilot.py e test_tui.py para SQLite, sem enfraquecer seus asserts. Comparar JSON exportável do progresso antigo/importado.
- [ ] **Commit:** adicionar somente módulos/testes da tarefa e `git commit -m "feat: persist lab state transactionally and migrate JSON"`.

### A3 — Recuperação de erros e entrada da TUI

**Files:** modificar cli.py:122–164,316–340,498–546; tui/app.py:118–121,249–297,491–507; tui/screens.py:83–117; app.py:146–154; catalog.py:62–78; tests/test_cli.py, test_tui.py, test_catalog.py e test_cli_entrypoint.py.

**Interfaces:** adicionar `SessionLog.try_record(command: str, summary: str) -> str | None` (mensagem de falha, sem tentar registrar o próprio erro); consumir APIs públicas A2. `validate_active_mission(progress: AppProgress, missions: list[Mission]) -> None` em app.py; normalizar fingerprint ilegível para ApplicationError. Explicação vazia permanece no modal com erro, sem chamar CLI.input.

- [ ] **Testes RED:** `test_blank_explanation_never_reads_stdin` usa helper _drive/_submit existente, Console.input monkeypatched para lançar AssertionError, TextArea vazia/whitespace e Concluir; exigir modal aberto e progress.explanation is None. `test_log_failure_keeps_cli_alive` injeta SessionError em record e exige execute('/status')==True, mensagem de falha e ausência de Traceback. Testar q, /exit, EOF e conflito de progresso: erro visível e possibilidade de sair sem sobrescrever. `test_removed_active_mission_is_actionable` exige ApplicationError antes de renderizar banner. Catálogo recusa ID duplicado, future="false" e skill desconhecida.

```python
def test_duplicate_skill_is_rejected(tmp_path):
    path = tmp_path / "skills.json"
    row = {"id": "x", "name": "X", "category": "core", "future": False}
    path.write_text(json.dumps([row, row]), encoding="utf-8")
    with pytest.raises(CatalogError, match="duplicad"):
        load_skills(path)
```

- [ ] **Rodar RED:** `python -m pytest tests/test_cli.py tests/test_tui.py tests/test_catalog.py tests/test_cli_entrypoint.py -q`; verificar falhas nas novas regressões.
- [ ] **Implementar:** log best-effort com mensagem explícita; erro de progresso continua bloqueando mutação. Modal valida vazio antes do callback. Encerramento idempotente e recuperável; validar catálogo/progresso no bootstrap. Tipo de future estritamente bool; validar referências de skills ao construir app.
- [ ] **Rodar GREEN:** mesmos testes + jornadas existentes. q/EOF não podem depender de salvar estado antigo após conflito.
- [ ] **Commit:** arquivos da tarefa; `git commit -m "fix: recover from input and persistence failures"`.

### A4 — Runner com árvore de processos e limites

**Files:** criar runtime/processes.py, runtime/windows.py e __init__.py; modificar test_runner.py:83–149 e tui/app.py:299–355; criar tests/test_process_runner.py; ampliar tests/test_test_runner.py.

**Interfaces:** `ProcessResult(return_code: int, output: str, timed_out: bool, cancelled: bool, truncated: bool)`; `ProcessRunner.run(argv: Sequence[str], cwd: Path, *, timeout: float=30.0, output_limit: int=1048576, cancel: threading.Event | None=None) -> ProcessResult`. Manter `run_tests(test_path, project_root, solution_path=None, timeout=30.0) -> TestResult`; adicionar cancel keyword-only sem mudar chamadores antigos.

- [ ] **Testes RED:** `test_timeout_stops_descendants` converte a prova marker de R6 em assert de ausência após timeout; confirmar primeiro que o filho iniciou. `test_cancel_stops_descendants` cancela depois de sinal de readiness. `test_output_is_bounded` usa filho que produz 2 MiB, exige truncated e captura <=1 MiB. Zero testes/skipped/JUnit inválido continuam reprovados.

```python
def test_output_is_bounded(tmp_path):
    result = ProcessRunner().run(
        [sys.executable, "-c", "print('x' * 2097152)"], tmp_path)
    assert result.truncated
    assert len(result.output.encode("utf-8")) <= 1048576
    assert result.return_code == 0
```

- [ ] **Rodar RED:** `python -m pytest tests/test_process_runner.py tests/test_test_runner.py -q`.
- [ ] **Implementar:** grupo POSIX e gerenciamento equivalente de descendentes no Windows, incluindo limpeza em finally. Spool/captura limitada sem pipe bloqueado. Integrar cancelamento do worker da TUI; status interrompido não aprova teste. Manter relatório JUnit separado do output truncado.
- [ ] **Rodar GREEN:** testes nas duas plataformas; confirmar readiness antes de provar cleanup, para evitar falsos positivos. Sem skips de timeout/descendentes nos runners suportados.
- [ ] **Commit:** `git commit -m "fix: cancel test process trees and bound output"` com módulos/testes explícitos.

### A5 — Comandos comuns, status e validação contínua

**Files:** criar commands.py e tests/test_commands.py; modificar cli.py, tui/app.py, tui/widgets.py, learning.py, app.py, scripts/install-lab.ps1, README.md e pyproject.toml; criar .github/workflows/tests.yml e constraints/dev.txt na implementação.

**Interfaces:** `Command(name: str, args: tuple[str, ...])`, `CommandResult(ok: bool, message: str, data: dict[str, object], exit_requested: bool=False)`; `parse_command(line: str) -> Command`; `CommandDispatcher.register(name: str, handler: Callable[[tuple[str, ...]], CommandResult]) -> None`, `.dispatch(command: Command) -> CommandResult`. Expor `plan_is_complete(plan: dict[str, str] | None) -> bool`. `StatusSnapshot` contém current_mission_id, plan_complete, tests_current, next_step e last_result; `PythonLabApp.status_snapshot() -> StatusSnapshot` calcula fingerprint uma vez. CLI.execute continua retornando bool para compatibilidade.

- [ ] **Testes RED:** aliases e path com espaços têm parsing comum, Windows sem perder backslash. `test_status_hashes_once` conta chamadas a solution_fingerprint e exige uma por snapshot. Preservar /mission, /concepts, /plan, /test details e pistas. `test_classic_without_assistant_extra` prova que help/version/missões não importam SDK opcional.

```python
def test_parser_preserves_quoted_path():
    command = parse_command('/project "C:\\Meus Projetos\\lab"')
    assert command.name == "/project"
    assert command.args == ("C:\\Meus Projetos\\lab",)
```

- [ ] **Rodar RED:** `python -m pytest tests/test_commands.py tests/test_next_step.py tests/test_cli_entrypoint.py -q` e a regressão de snapshot.
- [ ] **Implementar:** dispatcher independente de Rich/Textual; adaptadores renderizam resultados e coletam formulário. Mover aliases/registro neutro, consolidar plano/status e versão via metadata. Script PowerShell verifica versão e LASTEXITCODE antes de persistir PATH. CI Ubuntu/Windows × Python 3.11/3.12, instalação editável dev por constraints geradas/testadas; não afirmar suporte wheel ainda inexistente.
- [ ] **Rodar GREEN:** `python -m pytest`, `python -m pip check`, smoke `lab --help`/`lab --version` e entrada/saída classic/TUI em estado temporário. Verificar configuração CI estática e executar PowerShell no job Windows.
- [ ] **Commit:** `git commit -m "refactor: share lab commands and enforce cross-platform checks"` com arquivos explícitos.

## Aceite da entrega A

Reproduções R1–R7 viraram regressões corretas; nenhuma perda confirmada entre instâncias. Migração tem backup e rollback; dados inválidos não viram vazio. Fluxos e referências existentes continuam passando. Registrar resultados reais, diferenças de schema e instruções de migração na PR; não chamar a base pronta antes de validar Windows e cleanup de descendentes.
