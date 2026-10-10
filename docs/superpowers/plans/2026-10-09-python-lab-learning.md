# Python Lab Adaptive Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar assistência com precisão, recomendar prática, criar exercícios revisados e ampliar o catálogo de projetos.

**Architecture:** Regras de aprendizagem permanecem determinísticas; eventos complementam progresso e evidências. IA produz drafts revisáveis, publicados somente após validação. Templates adicionais usam o ScaffoldService existente, sem novo gerador autônomo.

**Tech Stack:** Python >=3.11, SQLite, contratos de A/B/C, pytest e dependências dos projetos gerados.

**Spec:** [Design](../specs/2026-10-09-python-lab-assistant-design.md), seções Modos, Projetos e aprendizado, aceite.

## Global Constraints

- Depende de C completo; manter plano/testes/explicação e regras de desbloqueio.
- Resposta gerada não aprova competência; nível 4/aplicação de patch é ajuda completa.
- JSON legado permanece recuperável; campos novos têm defaults explícitos.
- Exercício gerado é draft até revisão e validação; código gerado só executa depois de confirmação.
- Templates adicionais continuam offline ao gerar e preservam destino existente.

## Review Focus

- Tentativa assistida não aparece como demonstração independente (D1).
- Migração de evidências antigas não inventa nível de ajuda nem apaga histórico (D1).
- Recomendação nunca desbloqueia missão nem fabrica nota (D2).
- Referência/testes modificados após validação impedem publicação de exercício (D3).
- Templates e interfaces novas funcionam sem provedor e sem credenciais de terceiros (D4/D5).

---

## Mapa de arquivos

- Criar `learning_events.py`, `recommendations.py`, `exercises/{__init__.py,models.py,service.py}` e testes correspondentes.
- Adaptar models.py, learning.py, app.py, storage/codecs.py e database.py; ampliar campos de evidência sem alterar semântica antiga.
- Adicionar templates flask/django/library/bot/scraper ao registro de C3, com smoke independente.
- Ampliar comandos/apresentação e documentação no último incremento.

### D1 — Nível de assistência e evidências

**Files:** criar learning_events.py; modificar models.py, learning.py, app.py, assistant/service.py, storage/codecs.py, storage/database.py; criar tests/test_learning_events.py e ampliar test_learning.py/test_state_migration.py.

**Interfaces:** `AssistanceEvent(mission_id: str | None, action: str, level: int, timestamp: str, request_id: str)`; `AssistanceRecorder(database_path: Path).record(event: AssistanceEvent) -> None`. MissionProgress ganha max_assistance_level: int=0; eventos atualizam máximo da tentativa. record_full_solution de B4 delega ao recorder; deduplicar por request_id para evitar duplo evento. Histórico de projeto não altera missão não associada.

- [ ] **Testes RED:** nível4 e patch fazem resultado practicing, nunca demonstrated/consolidated; níveis0..3 não concluem missão sozinhos. Reiniciar missão concluída limpa máximo da nova tentativa e preserva evidências anteriores. Migração: reference_viewed=True → máximo4; False → min(hints_revealed,3); evidências antigas sem dado ficam assistance_level=None. Importar novamente não duplica eventos.

```python
def test_full_help_is_not_independent_evidence(app):
    progress = MissionProgress(
        plan={key: "ok" for key in PLAN_KEYS}, tests_passed=True,
        explanation="Verifiquei o contrato", max_assistance_level=4)
    evidence = complete_mission(app.mission_by_id("001"), progress, [])
    assert evidence
    assert all(item["result"] == "practicing" for item in evidence)
```

- [ ] **Rodar RED:** `python -m pytest tests/test_learning_events.py tests/test_learning.py tests/test_state_migration.py -q`.
- [ ] **Implementar:** migração versionada de schema/payload, backup antes de atualizar; level4 mantém reference_viewed para compatibilidade. Evidência nova registra assistance_level e origem, além dos campos atuais. record é transacional e não conclui missão. Falha de persistência não deve ser anunciada como evento salvo.
- [ ] **Rodar GREEN:** testes novos, jornadas existentes, fixtures legadas e rollback de migração. Não rebaixar/reescrever evidências antigas sem dado confiável.
- [ ] **Commit:** `git commit -m "feat: track assistance levels in learning evidence"`.

### D2 — Recomendações justificadas e revisão de dificuldades

**Files:** criar recommendations.py; ampliar presentation.py; criar tests/test_recommendations.py.

**Interfaces:** `LearningRecommendation(mission_id: str, reason: str, skills: tuple[str, ...])`; `recommend_practice(missions: list[Mission], progress: AppProgress) -> tuple[LearningRecommendation, ...]`. Sem IA. Excluir bloqueadas/concluídas da fila principal; manter atual iniciada primeiro, depois tentativas/pistas descendentes, desempate por cycle/id. Revisão de concluídas é lista distinta e opt-in, nunca altera status automaticamente.

- [ ] **Testes RED:** catálogo atual e estados synthetic: recomendações respeitam pré-requisitos, têm motivo derivado dos dados e ordem estável. `test_review_does_not_reset_progress` compara estado antes/depois. Sem histórico, recomendar primeira desbloqueada com motivo neutro, sem chamar usuário de iniciante/fraco por ausência de dados.

```python
def test_recommendation_does_not_change_state(app):
    before = copy.deepcopy(app.progress)
    items = recommend_practice(app.missions, app.progress)
    assert items
    assert app.progress == before
    assert items[0].mission_id == app.recommended().id
```

- [ ] **Rodar RED:** `python -m pytest tests/test_recommendations.py -q`.
- [ ] **Implementar:** regras simples e motivos com números observados, sem score fictício de domínio. Expor histórico de erros por referências locais às conversas de B4, não copiar segredos/conteúdo integral do projeto.
- [ ] **Rodar GREEN:** ordem/desbloqueio/ausência de mutação; conteúdos da recomendação traduzidos e referenciados.
- [ ] **Commit:** `git commit -m "feat: recommend practice from recorded learning data"`.

### D3 — Exercícios gerados como drafts revisáveis

**Files:** criar exercises/models.py, service.py e __init__.py; ampliar assistant/openai_provider.py; criar tests/test_exercise_drafts.py e tests/test_exercise_validation.py.

**Interfaces:** `ExerciseDraft(id: str, mission: dict[str, object], briefing: str, starter: str, reference: str, tests: str)`; Protocol `ExerciseProvider.draft(request: AssistantRequest) -> Awaitable[ExerciseDraft]`, implementado por OpenAIProvider com mesmo orçamento. `ExerciseService(data_dir: Path, runner: ProcessRunner).save_draft(draft: ExerciseDraft) -> Path`, `.validate(draft_path: Path, *, execution_confirmed: bool) -> DraftValidation`, `.publish(draft_path: Path, catalog_dir: Path, *, approved: bool) -> Path`. DraftValidation contém passed e fingerprint de todos os arquivos verificados. Publicação destina catálogo personalizado em data_dir, nunca modifica catálogo instalado/tracked.

- [ ] **Testes RED:** IDs/skills/prereqs/cycle/lesson_id seguem catálogo; inicial é exercício de arquivo único. Sem confirmação, não executar tests/reference; sem aprovação, não publicar. Referência deve passar suite não vazia; starter incompleto deve falhar pelo contrato, não por infraestrutura. Depois de validar, editar reference/tests invalida publish. Payload com traversal não cria arquivo externo. Falha conserva draft para revisão.

```python
def test_exercise_requires_review_before_execution(tmp_path, monkeypatch):
    runner = ProcessRunner()
    monkeypatch.setattr(runner, "run", lambda *a, **k: pytest.fail("executou sem revisão"))
    service = ExerciseService(tmp_path, runner)
    with pytest.raises(AssistantError, match="confirma"):
        service.validate(tmp_path / "draft", execution_confirmed=False)
```

- [ ] **Rodar RED:** `python -m pytest tests/test_exercise_drafts.py tests/test_exercise_validation.py -q`.
- [ ] **Implementar:** schema de draft, enunciado/critério/testes/referência em paths controlados; validação transacional do catálogo composto. Usar conftest/solution_loader do padrão existente para escolher starter/reference. Esconder referência no fluxo normal; leitura explícita segue nível4. Publish reconfere hashes, IDs, prereqs e aprovação; modelo não autoriza a operação.
- [ ] **Rodar GREEN:** draft real temporário passa referência e reprova starter, publicação adiciona missão sem alterar as 11 atuais; cenários skipped/vazio e edição posterior recusados. Documentar que teste técnico não prova qualidade didática.
- [ ] **Commit:** `git commit -m "feat: validate and publish reviewed exercise drafts"`.

### D4 — Templates adicionais

**Files:** adicionar scaffolding/templates/{flask,django,library,bot,scraper}/**; ampliar registry.json e package-data; criar/ampliar tests/test_template_smoke.py e test_scaffolding.py.

**Interfaces:** manter ScaffoldService.create e ScaffoldResult de C3. IDs adicionais: flask, django, library, bot, scraper. Todos têm pyproject, README, .gitignore e tests. Flask/Django: endpoint de health; library: função exemplo tipada/testada; bot: echo local; scraper: extrair título de HTML local. Adaptadores de Telegram/Discord e fetch HTTP ficam fora deste incremento.

- [ ] **Testes RED:** cada ID gera estrutura, README corresponde aos comandos reais, não há dependência de segredo/rede para gerar ou rodar testes. Smoke parametrizado por template; Flask/Django validam health; bot transforma 'olá' em resposta; scraper usa fixture HTML e não faz HTTP.

```python
@pytest.mark.parametrize("template", ["flask", "django", "library", "bot", "scraper"])
def test_additional_template_has_contract(tmp_path, template):
    result = ScaffoldService().create(template, tmp_path / "example")
    assert (result.target / "pyproject.toml").is_file()
    assert (result.target / "README.md").is_file()
    assert any("tests" in path.parts for path in result.files)
```

- [ ] **Rodar RED:** `python -m pytest tests/test_scaffolding.py -q` com novos casos.
- [ ] **Implementar:** um template por commit/sub-PR, reutilizando registry/serviço C3. Dependências restritas ao projeto gerado, sem import obrigatório desses frameworks pelo Lab.
- [ ] **Rodar GREEN:** smoke em venv limpo por ID, Ubuntu/Windows; usar testes funcionais de cada framework, não somente assert de arquivo. Resolver constraints dos templates durante implementação e guardar resultados reproduzíveis.
- [ ] **Commit:** um `feat: add tested <template> project template` por template validado.

### D5 — Interface de aprendizado e avaliação da release

**Files:** criar learning_commands.py; modificar catalog.py, commands.py, assistant/commands.py, cli.py, tui/app.py, tui/screens.py, presentation.py, README.md e CI; criar tests/test_learning_cli.py, test_learning_tui.py e docs/evaluations/tutor-scenarios.md na implementação.

**Interfaces:** CLI `lab practice`, `lab exercises draft --topic TEXT`, `lab exercises validate ID --yes`, `lab exercises publish ID --yes`; TUI /practice, /exercise TOPIC, /exercise-validate ID e /exercise-publish ID com modal. `LearningCommands(app: PythonLabApp, provider: ExerciseProvider | None, exercises: ExerciseService).register(dispatcher: CommandDispatcher) -> None` registra /practice como síncrono e geração de draft como assíncrona usando A5/B5; validação/publicação usam D3. CLI adapta argparse para os mesmos handlers. Provider None não bloqueia recomendações ou drafts já salvos. ID resolve somente dentro do store local. `load_catalog(installed_dir: Path, custom_dir: Path) -> list[Mission]` em catalog.py compõe missões e rejeita duplicações/relações inválidas.

- [ ] **Testes RED:** /practice é somente leitura; drafts/validação/publicação têm estados distintos e confirmações claras; sem provider, catálogo/testes/recomendações funcionam. `test_assisted_learning_journey` usa provider fake: pista → tentativa → explicação → evidência; solução completa produz practicing. Testar catálogo composto e conflito de ID com missão instalada.

```python
def test_practice_command_does_not_unlock_missions(app, tmp_path):
    before = copy.deepcopy(app.progress)
    dispatcher = CommandDispatcher()
    LearningCommands(app, None, ExerciseService(tmp_path, ProcessRunner())).register(dispatcher)
    result = dispatcher.dispatch(parse_command('/practice'))
    assert result.ok
    assert result.data['recommendations']
    assert app.progress == before
```

O adapter TUI deve ter o mesmo teste usando /practice via _submit, sem depender de SDK ou chave.

- [ ] **Rodar RED:** `python -m pytest tests/test_learning_cli.py tests/test_learning_tui.py -q`.
- [ ] **Implementar:** exibir nível de ajuda, motivos de recomendações e revisão de draft; referência não aparece sem solicitação. Catálogo composto não altera arquivos instalados. Documentar bot/scraper locais e diferenças entre estrutura inicial e aplicação completa.
- [ ] **Rodar GREEN:** suite/matriz/smokes; preencher avaliação manual com casos de sintaxe, nomes, tipos, importação, lógica e pytest. Verificar clareza, referência correta, graduação de pistas e ausência de falsa alegação de execução. Registrar falhas do modelo e ajustar prompts, sem substituir testes por opinião.
- [ ] **Commit:** `git commit -m "feat: expose adaptive practice and reviewed exercises"`.

## Aceite da entrega D

Sistema acompanha ajuda sem superestimar competências, recomenda prática explicável e permite criar exercício revisado sem publicar automaticamente. Sete templates executam seus contratos em ambiente limpo. A avaliação pedagógica é documentada como observação, separada da aprovação técnica das suites.
