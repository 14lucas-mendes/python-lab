# Python Lab Review and Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revisar código, propor patches verificáveis e gerar estruturas executáveis de CLI/FastAPI.

**Architecture:** AnalysisService e AssistantService alimentam propostas tipadas; PatchService controla diff/hash/escrita e VerificationService executa checks escolhidos. ScaffoldService gera projetos por templates empacotados e testados, sem depender de IA ou instalar código automaticamente.

**Tech Stack:** Contratos de A/B, difflib, hashlib, importlib.resources, string.Template, pytest e dependências dos projetos gerados em venv separado.

**Spec:** [Design](../specs/2026-10-09-python-lab-assistant-design.md), seções Revisão e patches, Projetos e aprendizado.

## Global Constraints

- Depende de B1–B5 completo; não confundir sugestão com verificação executada.
- Aplicação MVP de um arquivo por proposta; sem rename/delete e sem escrita fora do projeto selecionado.
- Confirmação explícita reconfere hash; não sobrescrever edição mais recente.
- Template só cria destino inexistente; não instala nem executa nada automaticamente.
- Testes de IA sem rede; smoke dos templates separado dos testes de SDK.

## Review Focus

- Hash mudou depois do preview: patch recusado e bytes novos intactos (C1).
- Escrita falhou: backup/rollback ou erro de recuperação explícito (C1).
- Check falhou/cancelou: status não vira passed (C2).
- Destino contém arquivos: scaffold não os modifica (C3).
- UI/JSON mostram proposta, aplicação e verificação como estados distintos (C4).

---

## Mapa de arquivos

- Criar `assistant/{patches.py,review.py,verification.py}` e testes correspondentes.
- Criar `scaffolding/{__init__.py,models.py,service.py,templates/registry.json,templates/cli/**,templates/fastapi/**}` sob python_lab/.
- Integrar assistant/commands.py, commands.py, cli.py e tui/{app.py,screens.py}; ampliar package-data, README e CI.

### C1 — Propostas tipadas, diff e aplicação

**Files:** criar assistant/patches.py; criar tests/test_patches.py; adaptar assistant/models.py para tipos de proposta.

**Interfaces:** `FileChange(path: str, before_sha256: str, after_text: str)`; `PatchProposal(id: str, change: FileChange, reason: str, selected_paths: tuple[str, ...])`; `PatchService(workspace: Workspace, data_dir: Path).preview(proposal: PatchProposal) -> str`, `.save(proposal: PatchProposal) -> None`, `.load(proposal_id: str) -> PatchProposal`, `.apply(proposal: PatchProposal, *, confirmed: bool) -> Path`. selected_paths vem do snapshot local e nunca do modelo. Backup sob data_dir; proposta/cache pertencem ao workspace e ID é chave opaca, não path fornecido pelo modelo.

- [ ] **Testes RED:** `test_stale_patch_preserves_new_edit`, traversal/symlink externo, UTF-8/limite, missing confirmation e falha em os.replace. Preview não escreve. Destino do patch precisa pertencer aos sources selecionados; verificar isso na criação e aplicação. Aplicação válida produz exatamente after_text e backup dos bytes antigos.

```python
def test_stale_patch_preserves_new_edit(tmp_path):
    root = tmp_path / "project"; root.mkdir()
    source = root / "a.py"; source.write_text("x=1\n")
    snapshot = Workspace(root).snapshot([source])
    proposal = PatchProposal("p1", FileChange("a.py", snapshot.sources[0].sha256, "x=2\n"), "fix", ("a.py",))
    source.write_text("x=3\n")
    with pytest.raises(AssistantError, match="alterad"):
        PatchService(Workspace(root), tmp_path / "state").apply(proposal, confirmed=True)
    assert source.read_text() == "x=3\n"
```

- [ ] **Rodar RED:** `python -m pytest tests/test_patches.py -q`.
- [ ] **Implementar:** gerar diff literal com difflib, validar substituição única/limites, guardar base selecionada e hash, criar backup e substituir atomicamente. Validar novamente antes de escrever; não prometer proteção contra editores externos que não usam locks. Em conflito, pedir novo snapshot/proposta. Em falha, preservar original ou apresentar caminho de recuperação comprovado.
- [ ] **Rodar GREEN:** mesmos testes; testar falhas em backup e replace. Nenhum teste pode “passar” ignorando a falha de escrita.
- [ ] **Commit:** `git commit -m "feat: preview and apply versioned code patches"`.

### C2 — Revisão estruturada e verificação escolhida

**Files:** criar assistant/review.py, verification.py; ampliar assistant/models.py, provider.py e provider schema em openai_provider.py; criar tests/test_review.py e test_verification.py.

**Interfaces:** `ReviewReply(answer: AssistantAnswer, changes: tuple[FileChange, ...])`; Protocol `ReviewProvider.review(request: AssistantRequest) -> Awaitable[ReviewReply]`, implementado por OpenAIProvider com uma chamada estruturada e o mesmo orçamento B3. `ReviewResult(analysis: AnalysisReport, advice: AssistantAnswer | None, proposals: tuple[PatchProposal, ...])`; `ReviewService(analysis: AnalysisService, provider: ReviewProvider | None, patches: PatchService, history: ConversationRepository).review(request: AssistantRequest) -> Awaitable[ReviewResult]`. Provider None produz somente análise local. `VerificationService(runner: ProcessRunner).run(proposal: PatchProposal, workspace: Workspace, *, checks: tuple[str, ...], cancel: Event | None=None) -> VerificationResult`; VerificationResult contém status unverified/passed/failed/cancelled e checks executados. Nomes permitidos: ast, ruff, pytest; argv é construído localmente. Propostas têm schema separado validado como C1, não extraídas arbitrariamente de Markdown.

- [ ] **Testes RED:** achados de AST/Ruff aparecem sem IA; sem checks, status unverified. Pytest falho, ausente, sem JUnit ou cancelado não pode produzir passed; preservar semântica zero/skipped de A4. Resposta que propõe arquivo fora da seleção é rejeitada. Alteração desde o último teste invalida status verificado.

```python
def test_no_check_is_not_a_verified_patch(tmp_path):
    source = tmp_path / "a.py"; source.write_text("x=1\n")
    snapshot = Workspace(tmp_path).snapshot([source])
    proposal = PatchProposal("p1", FileChange("a.py", snapshot.sources[0].sha256, "x=2\n"), "fix", ("a.py",))
    result = VerificationService(ProcessRunner()).run(proposal, Workspace(tmp_path), checks=())
    assert result.status == "unverified"
    assert result.checks == ()
```

- [ ] **Rodar RED:** `python -m pytest tests/test_review.py tests/test_verification.py -q`.
- [ ] **Implementar:** analysis+advice separados; oferecer extração estruturada opcional de propostas. Prompt refactor preserva API/comportamento e explica tradeoffs; não pedir otimização sem evidência. Verificação calcula fingerprint do arquivo aplicado e guarda resultado nesse hash. Pytest precisa de seleção explícita; use JUnit do run atual.
- [ ] **Rodar GREEN:** testes com provider fake + projeto temporário com regressão real: patch errado falha, patch correto passa e edição posterior desatualiza resultado.
- [ ] **Commit:** `git commit -m "feat: review code and verify selected changes"`.

### C3 — Templates CLI/FastAPI

**Files:** criar scaffolding/models.py, service.py, __init__.py e templates/registro; ampliar pyproject.toml package-data; criar tests/test_scaffolding.py e tests/test_template_smoke.py.

**Interfaces:** `ScaffoldResult(target: Path, files: tuple[Path, ...], template: str)`; `ScaffoldService.create(template: str, target: Path) -> ScaffoldResult`. IDs iniciais cli/fastapi. Normalizar nome de distribuição/import para identificador válido; rejeitar basename vazio, nome Python inválido, template desconhecido e destino já existente. Ler templates com importlib.resources; copiar somente manifestos/paths registrados.

- [ ] **Testes RED:** estrutura inclui pyproject, README, .gitignore, pacote src e tests; CLI possui comando --name e testa saudação; FastAPI possui GET /health → {'status':'ok'} e teste com cliente. Provar geração offline, sem subprocesso de instalação; testar path malicioso de template e falta de recurso empacotado.

```python
def test_existing_target_is_preserved(tmp_path):
    target = tmp_path / "my_app"; target.mkdir()
    original = target / "keep.txt"; original.write_text("keep")
    with pytest.raises(AssistantError, match="exist"):
        ScaffoldService().create("cli", target)
    assert original.read_text() == "keep"
```

- [ ] **Rodar RED:** `python -m pytest tests/test_scaffolding.py -q`.
- [ ] **Implementar:** templates curados, substituição restrita ao nome, criação exclusiva do diretório. Rollback remove somente arquivos gerados pela chamada; nunca apagar arquivos preexistentes ou introduzidos pelo usuário. README inclui comandos Linux/Windows para venv/install/tests/run. Dependências de FastAPI ficam no projeto gerado, não no runtime obrigatório do Lab.
- [ ] **Rodar GREEN:** unit tests offline; CI de smoke cria venv limpo por template, instala do manifesto gerado, executa suite e funcionalidade. CLI: stdout='Olá, Ana!' e exit0; FastAPI: cliente interno confirma /health=200. Validar recursos no artefato instalado suportado do Lab.
- [ ] **Commit:** `git commit -m "feat: scaffold tested CLI and FastAPI projects"`.

### C4 — Comandos, confirmação e jornada completa

**Files:** modificar assistant/commands.py, cli.py, commands.py, tui/app.py, tui/screens.py, README.md e .github/workflows/tests.yml; criar tests/test_review_cli.py, test_review_tui.py e test_scaffolding_cli.py.

**Interfaces:** CLI `lab review FILE`, `lab apply ID --yes`, `lab verify ID --check ast|ruff|pytest` (check repetível) e `lab new cli|fastapi NAME --path PARENT`; TUI /review FILE, /apply ID, /verify ID --check CHECK e /new TEMPLATE NAME --path PARENT. Todos usam serviços C1/C2/C3, mesmos códigos de saída/JSON de B5. Aplicar solução na missão ativa chama record_full_solution de B4 quando o path pertence à solução, sem concluir missão.

- [ ] **Testes RED:** TUI confirma diff/path antes da escrita; cancelar modal conserva bytes. CLI sem --yes não escreve e explica opção. IDs de outro workspace são rejeitados. `test_review_apply_verify_journey` usa provider fake e bug real, demonstra preview sem escrita → confirmação → pytest aprovado; fonte editada depois exige nova verificação.

```python
def test_apply_requires_explicit_confirmation(tmp_path):
    source = tmp_path / "a.py"; source.write_text("x=1\n")
    snapshot = Workspace(tmp_path).snapshot([source])
    proposal = PatchProposal("p1", FileChange("a.py", snapshot.sources[0].sha256, "x=2\n"), "fix", ("a.py",))
    with pytest.raises(AssistantError, match="confirma"):
        PatchService(Workspace(tmp_path), tmp_path / "state").apply(proposal, confirmed=False)
    assert source.read_text() == "x=1\n"
```

- [ ] **Rodar RED:** testes novos de CLI/TUI/jornada; `python -m pytest tests/test_review_cli.py tests/test_review_tui.py tests/test_scaffolding_cli.py -q`.
- [ ] **Implementar:** comandos sem executar output de modelo como shell, modal com diff literal, resultado e próximo passo. Scaffold imprime caminhos/comandos, não instala. Verificação expõe infra failure vs assertions/timeout; composer/cancelamento seguem B5.
- [ ] **Rodar GREEN:** suite completa, matriz CI, smoke dos dois templates e venv sem IA. Nenhuma evidência é aprovada por review/apply; missões usam /test + /explain e nível de ajuda.
- [ ] **Commit:** `git commit -m "feat: expose reviewed patches and project templates"`.

## Aceite da entrega C

Um projeto real pequeno pode ser revisado, ter um patch escolhido aplicado e ser verificado por testes, com hashes e resultados explícitos. CLI/FastAPI gerados executam em venv limpo. Cancelar ou falhar preserva arquivos e estado. Frameworks adicionais e exercícios adaptativos são a entrega D, não requisitos ocultos desta release.
