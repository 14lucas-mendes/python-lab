# Python Lab v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir uma CLI local que conecte um Goal profissional, um mapa de Skills e cinco Missions avaliadas por planejamento, pytest e explicação final.

**Architecture:** O núcleo será um pacote Python independente da interface. Dados declarativos em JSON descrevem Goal, Skills, Missions e progresso; serviços de domínio cuidam de recomendação, pistas, testes e evidências; a CLI Rich apenas recebe comandos e apresenta resultados.

**Tech Stack:** Python 3.11+, pytest, Rich, biblioteca padrão (`dataclasses`, `json`, `pathlib`, `subprocess`, `tempfile`).

**Spec:** `docs/superpowers/specs/2026-09-15-python-lab-v0.1-design.md`

## Global Constraints

- Uso pessoal e local; sem autenticação, nuvem, banco de dados ou interface web.
- Goal fixo em dados, sem geração por IA.
- Cinco Missions progressivas com planejamento, testes e explicação obrigatórios.
- Pistas pré-escritas; consultar a solução impede evidência `demonstrated` na tentativa.
- Progresso persistido em JSON com substituição atômica.
- Recomendação determinística: missão iniciada; caso contrário, primeira desbloqueada.
- A CLI não edita a solução; o usuário trabalha no VS Code.
- Compatibilidade com Windows: usar `pathlib` e `sys.executable`, sem comandos exclusivos de shell Unix.

---

## Mapa de arquivos

```text
python-lab/
├── lab.py                         # entry point
├── pyproject.toml                 # pacote e dependências
├── python_lab/
│   ├── cli.py                     # loop interativo e apresentação Rich
│   ├── app.py                     # fachada dos casos de uso
│   ├── models.py                  # modelos Goal, Skill, Mission e Progress
│   ├── catalog.py                 # leitura/validação do catálogo JSON
│   ├── progress.py                # persistência atômica
│   ├── learning.py                # recomendação, pistas, conclusão e evidências
│   └── test_runner.py             # execução isolada do pytest
├── data/
│   ├── goal.json
│   ├── skills.json
│   └── progress.json
├── missions/
│   ├── 001-consolidar-falhas/
│   ├── 002-limpar-relatorio-csv/
│   ├── 003-validar-inventario-json/
│   ├── 004-recuperar-script/
│   └── 005-relatorio-operacional/
└── tests/                          # testes do motor e da CLI
```

## Contratos compartilhados

```python
@dataclass(frozen=True)
class Mission:
    id: str
    slug: str
    title: str
    summary: str
    skills: tuple[str, ...]
    prerequisites: tuple[str, ...]
    test_path: Path
    solution_path: Path
    hints: tuple[str, ...]

@dataclass
class MissionProgress:
    status: str = "available"
    plan: dict[str, str] | None = None
    attempts: int = 0
    tests_passed: bool = False
    hints_revealed: int = 0
    reference_viewed: bool = False
    explanation: str | None = None

@dataclass(frozen=True)
class TestResult:
    passed: bool
    return_code: int
    output: str
```

---

### Task 1: Base do projeto e modelos de domínio

**Files:**
- Create: `pyproject.toml`
- Create: `lab.py`
- Create: `python_lab/__init__.py`
- Create: `python_lab/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Goal`, `Skill`, `Mission`, `MissionProgress`, `AppProgress`, `TestResult`.
- Consumes: nenhum componente anterior.

- [ ] **Step 1: Criar um teste que expresse os estados iniciais**

```python
from python_lab.models import MissionProgress


def test_new_mission_progress_starts_available():
    progress = MissionProgress()
    assert progress.status == "available"
    assert progress.attempts == 0
    assert progress.tests_passed is False
    assert progress.reference_viewed is False
```

- [ ] **Step 2: Executar o teste e confirmar a falha**

Run: `python -m pytest tests/test_models.py -v`

Expected: FAIL com `ModuleNotFoundError: No module named 'python_lab'`.

- [ ] **Step 3: Criar configuração, modelos e entry point mínimo**

`pyproject.toml`:

```toml
[project]
name = "python-lab"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["rich>=13.7,<15"]

[project.optional-dependencies]
dev = ["pytest>=8,<9"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`python_lab/models.py` deve implementar os contratos compartilhados e:

```python
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Goal:
    title: str
    statement: str
    success_criteria: tuple[str, ...]


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str
    future: bool = False


@dataclass
class AppProgress:
    current_mission_id: str | None = None
    missions: dict[str, MissionProgress] = field(default_factory=dict)
    evidence: list[dict[str, object]] = field(default_factory=list)
```

`lab.py`:

```python
from python_lab.cli import main


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Executar o teste e confirmar sucesso**

Run: `python -m pytest tests/test_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml lab.py python_lab tests/test_models.py
git commit -m "feat: establish Python Lab domain models"
```

---

### Task 2: Catálogo declarativo de Goal, Skills e Missions

**Files:**
- Create: `python_lab/catalog.py`
- Create: `data/goal.json`
- Create: `data/skills.json`
- Create: `tests/fixtures/catalog/missions/001-example/mission.json`
- Create: `tests/fixtures/catalog/missions/001-example/hints.json`
- Create: `tests/test_catalog.py`

**Interfaces:**
- Consumes: modelos de `python_lab.models`.
- Produces: `load_goal(path: Path) -> Goal`, `load_skills(path: Path) -> dict[str, Skill]`, `load_missions(root: Path) -> list[Mission]` e `CatalogError`.

- [ ] **Step 1: Escrever testes para leitura e erro de catálogo**

```python
from pathlib import Path
import pytest
from python_lab.catalog import CatalogError, load_goal, load_missions


FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


def test_load_goal_returns_typed_goal(tmp_path):
    path = tmp_path / "goal.json"
    path.write_text('{"title":"Python","statement":"Aprender","success_criteria":["Resolver"]}', encoding="utf-8")
    goal = load_goal(path)
    assert goal.title == "Python"
    assert goal.success_criteria == ("Resolver",)


def test_invalid_goal_raises_actionable_error(tmp_path):
    path = tmp_path / "goal.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(CatalogError, match="JSON inválido"):
        load_goal(path)


def test_load_missions_orders_by_id():
    missions = load_missions(FIXTURES / "missions")
    assert [mission.id for mission in missions] == ["001"]
```

- [ ] **Step 2: Executar os testes e confirmar a falha**

Run: `python -m pytest tests/test_catalog.py -v`

Expected: FAIL porque `python_lab.catalog` não existe.

- [ ] **Step 3: Implementar leitores validados**

Use `json.loads(path.read_text(encoding="utf-8"))`, converta listas em tuplas e valide explicitamente campos obrigatórios. `load_missions` deve procurar `*/mission.json`, carregar `hints.json` da mesma pasta e resolver `test_path` e `solution_path` relativamente à pasta da missão.

Formato de `data/goal.json`:

```json
{
  "title": "Python para automação e integrações",
  "statement": "Desenvolver competência demonstrável em Python, automação e integrações para conquistar uma oportunidade profissional, criando base para evoluir posteriormente até engenharia de IA.",
  "success_criteria": [
    "Resolver problemas sem depender de código pronto",
    "Testar e depurar as próprias soluções",
    "Explicar decisões técnicas com clareza"
  ]
}
```

`data/skills.json` deve conter os IDs: `problem_understanding`, `inputs_outputs`, `decomposition`, `edge_cases`, `technical_explanation`, `functions`, `collections`, `strings_validation`, `files`, `csv`, `json`, `exceptions`, `debugging`, `pytest`, `modules`, `ai_code_review`; e marcar `sql`, `rest_apis`, `git`, `selenium`, `ai_systems` com `future: true`.

- [ ] **Step 4: Rodar os testes de catálogo**

Run: `python -m pytest tests/test_catalog.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python_lab/catalog.py data tests/fixtures tests/test_catalog.py
git commit -m "feat: load goal skills and mission catalog"
```

---

### Task 3: Persistência atômica do progresso

**Files:**
- Create: `python_lab/progress.py`
- Create: `data/progress.json`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: `AppProgress` e `MissionProgress`.
- Produces: `ProgressRepository.load() -> AppProgress`, `ProgressRepository.save(progress: AppProgress) -> None` e `ProgressError`.

- [ ] **Step 1: Escrever testes de round-trip e proteção contra JSON inválido**

```python
import pytest
from python_lab.models import AppProgress, MissionProgress
from python_lab.progress import ProgressError, ProgressRepository


def test_progress_round_trip(tmp_path):
    path = tmp_path / "progress.json"
    repository = ProgressRepository(path)
    expected = AppProgress(current_mission_id="001", missions={"001": MissionProgress(status="started", attempts=2)})
    repository.save(expected)
    actual = repository.load()
    assert actual.current_mission_id == "001"
    assert actual.missions["001"].attempts == 2


def test_invalid_progress_is_not_overwritten(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("{invalid", encoding="utf-8")
    repository = ProgressRepository(path)
    with pytest.raises(ProgressError, match="Progresso inválido"):
        repository.load()
    assert path.read_text(encoding="utf-8") == "{invalid"
```

- [ ] **Step 2: Executar e confirmar a falha**

Run: `python -m pytest tests/test_progress.py -v`

Expected: FAIL porque o repositório ainda não existe.

- [ ] **Step 3: Implementar serialização e gravação atômica**

`save` deve criar um arquivo temporário no mesmo diretório com `tempfile.NamedTemporaryFile(delete=False, dir=path.parent)`, gravar JSON UTF-8, executar `flush()` e `os.fsync()`, e finalizar com `os.replace(temp_path, self.path)`. Em caso de falha anterior ao `replace`, remover somente o arquivo temporário criado.

Arquivo inicial:

```json
{"current_mission_id": null, "missions": {}, "evidence": []}
```

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_progress.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python_lab/progress.py data/progress.json tests/test_progress.py
git commit -m "feat: persist learning progress atomically"
```

---

### Task 4: Recomendação, pistas, conclusão e evidências

**Files:**
- Create: `python_lab/learning.py`
- Test: `tests/test_learning.py`

**Interfaces:**
- Consumes: `Mission`, `AppProgress`, `MissionProgress`.
- Produces: `recommend_mission`, `start_mission`, `reveal_hint`, `complete_mission`, `CompletionError`.

- [ ] **Step 1: Escrever testes para as regras pedagógicas centrais**

```python
from pathlib import Path
import pytest
from python_lab.learning import CompletionError, complete_mission, recommend_mission, reveal_hint
from python_lab.models import AppProgress, Mission, MissionProgress


def mission(mid="001", prerequisites=()):
    return Mission(mid, "example", "Example", "Summary", ("debugging",), prerequisites, Path("tests"), Path("solution.py"), ("Pergunta", "Pista"))


def test_recommend_started_mission_before_next_available():
    progress = AppProgress(current_mission_id="002", missions={"002": MissionProgress(status="started")})
    assert recommend_mission([mission("001"), mission("002")], progress).id == "002"


def test_completion_requires_plan_tests_and_explanation():
    progress = MissionProgress(status="started", tests_passed=True)
    with pytest.raises(CompletionError, match="planejamento"):
        complete_mission(mission(), progress, [])


def test_reference_solution_prevents_demonstrated_evidence():
    progress = MissionProgress(
        status="started",
        plan={"input":"dados", "output":"relatório", "steps":"validar", "risks":"vazio"},
        tests_passed=True,
        reference_viewed=True,
        explanation="Usei validação antes do cálculo.",
    )
    evidence = complete_mission(mission(), progress, [])
    assert evidence[0]["result"] == "practicing"
```

- [ ] **Step 2: Executar e confirmar a falha**

Run: `python -m pytest tests/test_learning.py -v`

Expected: FAIL porque `python_lab.learning` não existe.

- [ ] **Step 3: Implementar as regras mínimas**

`recommend_mission` deve respeitar a ordem dos IDs e pré-requisitos concluídos. `reveal_hint` incrementa `hints_revealed` até o limite, exigindo confirmação booleana antes de marcar `reference_viewed` no último nível. `complete_mission` valida plano com as quatro chaves, `tests_passed` e explicação não vazia; define `status="completed"`; gera `practicing` quando a referência foi vista e `demonstrated` nos demais casos. Uma evidência posterior `demonstrated` para a mesma Skill em outra Mission gera `consolidated`.

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_learning.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python_lab/learning.py tests/test_learning.py
git commit -m "feat: enforce deliberate practice workflow"
```

---

### Task 5: Execução segura e portável do pytest

**Files:**
- Create: `python_lab/test_runner.py`
- Test: `tests/test_test_runner.py`

**Interfaces:**
- Consumes: caminho absoluto da suíte da Mission.
- Produces: `run_tests(test_path: Path, project_root: Path) -> TestResult`.

- [ ] **Step 1: Escrever teste usando monkeypatch do subprocess**

```python
import sys
from pathlib import Path
from python_lab.test_runner import run_tests


def test_runner_uses_current_python_and_captures_output(monkeypatch, tmp_path):
    calls = {}
    class Completed:
        returncode = 0
        stdout = "2 passed"
    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return Completed()
    monkeypatch.setattr("python_lab.test_runner.subprocess.run", fake_run)
    result = run_tests(tmp_path / "tests", tmp_path)
    assert calls["command"][:3] == [sys.executable, "-m", "pytest"]
    assert result.passed is True
    assert result.output == "2 passed"
```

- [ ] **Step 2: Executar e confirmar a falha**

Run: `python -m pytest tests/test_test_runner.py -v`

Expected: FAIL porque o runner não existe.

- [ ] **Step 3: Implementar runner sem shell**

Usar `subprocess.run([sys.executable, "-m", "pytest", str(test_path), "-q"], cwd=project_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)`. Retornar `TestResult(passed=returncode == 0, return_code=returncode, output=stdout)`.

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_test_runner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python_lab/test_runner.py tests/test_test_runner.py
git commit -m "feat: run mission tests portably"
```

---

### Task 6: CLI orientada por comandos

**Files:**
- Create: `python_lab/app.py`
- Create: `python_lab/cli.py`
- Test: `tests/test_cli.py`
- Modify: `lab.py`

**Interfaces:**
- Consumes: catálogo, repositório, regras de aprendizagem e runner.
- Produces: `PythonLabApp.start(mission_id: str)`, `save_plan(plan: dict[str, str])`, `run_current_tests(solution_path: Path | None = None) -> TestResult`, `next_hint(confirm_reference: bool = False) -> str`, `save_explanation(text: str)` e `complete_current_mission() -> list[dict[str, object]]`.
- Produces: `PythonLabCLI.execute(command_line: str) -> bool` e `main() -> None`; `False` encerra o loop.

- [ ] **Step 1: Escrever testes dos comandos essenciais**

```python
from rich.console import Console
from python_lab.cli import PythonLabCLI


def test_help_lists_core_commands(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/help") is True
    output = console.export_text()
    assert "/goal" in output
    assert "/test" in output
    assert "/explain" in output


def test_unknown_command_does_not_crash(app):
    console = Console(record=True)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/desconhecido") is True
    assert "Comando desconhecido" in console.export_text()
```

O fixture `app` em `tests/conftest.py` deve usar catálogo e progresso temporários para nunca alterar `data/progress.json`.

- [ ] **Step 2: Executar e confirmar a falha**

Run: `python -m pytest tests/test_cli.py -v`

Expected: FAIL porque `python_lab.cli` não existe.

- [ ] **Step 3: Implementar o application facade e despacho explícito**

`PythonLabApp` deve receber `goal`, `skills`, `missions`, `repository` e `project_root` no construtor. Cada método delega às funções de `learning.py`, salva o progresso após uma alteração confirmada e impede operação sem missão atual com `ApplicationError("Nenhuma missão iniciada")`. O parâmetro opcional `solution_path` existe para o teste ponta a ponta; quando ausente, usa o `starter.py` da missão atual.

A CLI deve dividir a primeira palavra, buscar um handler em:

```python
self.handlers = {
    "/goal": self.show_goal,
    "/skills": self.show_skills,
    "/missions": self.show_missions,
    "/start": self.start,
    "/plan": self.plan,
    "/test": self.test,
    "/hint": self.hint,
    "/explain": self.explain,
    "/status": self.status,
    "/help": self.help,
    "/exit": self.exit,
}
```

Entradas multilinha de `/plan` devem solicitar `input`, `output`, `steps` e `risks`. `/explain` deve rejeitar texto vazio. `/test` incrementa `attempts`, grava o resultado e persiste. `main()` captura `KeyboardInterrupt`, salva somente estado já confirmado e encerra com mensagem curta.

- [ ] **Step 4: Testar CLI e regressão do motor**

Run: `python -m pytest tests/test_cli.py tests/test_learning.py tests/test_progress.py -v`

Expected: PASS.

- [ ] **Step 5: Fazer smoke test manual**

Run: `python lab.py`

Expected: painel com Goal, missão recomendada e prompt `lab>`; `/help` lista os 11 comandos; `/exit` encerra sem traceback.

- [ ] **Step 6: Commit**

```bash
git add lab.py python_lab/app.py python_lab/cli.py tests/conftest.py tests/test_cli.py
git commit -m "feat: add guided command-line workflow"
```

---

### Task 7: Missions 001 a 003

**Files:**
- Create: `missions/001-consolidar-falhas/*`
- Create: `missions/002-limpar-relatorio-csv/*`
- Create: `missions/003-validar-inventario-json/*`
- Test: testes internos de cada Mission.

**Interfaces:**
- Produces: `consolidar_falhas(registros: list[dict]) -> dict`, `limpar_relatorio(caminho: Path) -> dict`, `validar_inventario(caminho: Path) -> tuple[list, list]`.
- Consumes: formato de Mission aceito por `load_missions`.

- [ ] **Step 1: Criar testes falhando para Mission 001**

```python
def test_consolida_equipamentos_repetidos():
    registros = [{"equipamento":"S01", "minutos":10}, {"equipamento":"S01", "minutos":20}, {"equipamento":"S03", "minutos":15}]
    assert consolidar_falhas(registros) == {"totais":{"S01":30, "S03":15}, "mais_critico":"S01"}


def test_lista_vazia_nao_tem_mais_critico():
    assert consolidar_falhas([]) == {"totais":{}, "mais_critico":None}
```

Run: `python -m pytest missions/001-consolidar-falhas/tests -v`

Expected: FAIL com implementação inicial incompleta.

- [ ] **Step 2: Escrever solução de referência da Mission 001 e validar**

Implementar acumulação com dicionário, desempate por ordem alfabética e rejeição de minutos negativos com `ValueError`.

Run: `python -m pytest missions/001-consolidar-falhas/tests -v`

Expected: PASS usando temporariamente a solução de referência; restaurar `starter.py` antes do commit.

- [ ] **Step 3: Criar testes falhando para Mission 002**

Cobrir CSV válido, duração vazia, duração não numérica, campo ausente e arquivo vazio. O retorno deve ser `{"validos": int, "invalidos": int, "totais": dict[str, int]}`.

Run: `python -m pytest missions/002-limpar-relatorio-csv/tests -v`

Expected: FAIL.

- [ ] **Step 4: Escrever solução de referência da Mission 002 e validar**

Usar `csv.DictReader`, tratar `ValueError` por linha e contar inválidos sem interromper o arquivo inteiro.

Run: `python -m pytest missions/002-limpar-relatorio-csv/tests -v`

Expected: PASS com referência e FAIL controlado com starter.

- [ ] **Step 5: Criar testes falhando para Mission 003**

Cobrir JSON válido, arquivo malformado, campos obrigatórios `id`, `tipo`, `status`, IDs duplicados e lista vazia. O retorno será `(validos, inconsistencias)`, com inconsistências contendo `index` e `errors`.

Run: `python -m pytest missions/003-validar-inventario-json/tests -v`

Expected: FAIL.

- [ ] **Step 6: Escrever solução de referência da Mission 003 e validar**

Usar `json.load`, converter `JSONDecodeError` em `ValueError("Inventário JSON inválido")` e detectar duplicatas com `set`.

Run: `python -m pytest missions/003-validar-inventario-json/tests -v`

Expected: PASS com referência e FAIL controlado com starter.

- [ ] **Step 7: Completar metadados e pistas**

Cada `mission.json` deve declarar IDs, Skills, pré-requisitos, `tests` e `solution`. Cada `hints.json` deve conter exatamente cinco níveis, sendo o quinto `{"type":"reference","path":"reference_solution.py"}`. Os READMEs devem especificar problema, entrada, saída, restrições e critérios de aceite sem revelar o algoritmo.

- [ ] **Step 8: Commit**

```bash
git add missions/001-consolidar-falhas missions/002-limpar-relatorio-csv missions/003-validar-inventario-json
git commit -m "feat: add first three Python learning missions"
```

---

### Task 8: Missions 004 e 005

**Files:**
- Create: `missions/004-recuperar-script/*`
- Create: `missions/005-relatorio-operacional/*`
- Test: testes internos das duas Missions.

**Interfaces:**
- Produces: script corrigido `calcular_disponibilidade(eventos) -> dict` e pacote `relatorio_operacional` com `load_inputs`, `build_report`, `write_report`.
- Consumes: Mission 004 depende de `003`; Mission 005 depende de `001`, `002`, `003` e `004`.

- [ ] **Step 1: Preparar código defeituoso e testes da Mission 004**

O starter deve conter bugs intencionais: divisão por zero sem eventos, mutação da lista recebida, arredondamento antes do cálculo final e aceitação de duração negativa. Os testes devem nomear claramente cada comportamento esperado.

Run: `python -m pytest missions/004-recuperar-script/tests -v`

Expected: pelo menos quatro falhas distintas.

- [ ] **Step 2: Criar solução de referência e validar Mission 004**

A referência não deve mutar a entrada, deve retornar `{}` para lista vazia, rejeitar duração negativa e arredondar somente o resultado final para duas casas.

Run: `python -m pytest missions/004-recuperar-script/tests -v`

Expected: PASS com referência.

- [ ] **Step 3: Criar contrato modular e testes da Mission 005**

`load_inputs(csv_path, json_path)` carrega eventos e inventário; `build_report(eventos, inventario)` retorna equipamentos com total de falhas e status cadastral; `write_report(report, output_path)` grava JSON UTF-8. Testar arquivo ausente, linha inválida, equipamento desconhecido, entrada vazia e round-trip do arquivo final.

Run: `python -m pytest missions/005-relatorio-operacional/tests -v`

Expected: FAIL com funções iniciais incompletas.

- [ ] **Step 4: Criar solução de referência e validar Mission 005**

Separar as três responsabilidades em `io.py`, `report.py` e `main.py`; não duplicar as regras de validação dentro do entry point.

Run: `python -m pytest missions/005-relatorio-operacional/tests -v`

Expected: PASS com referência.

- [ ] **Step 5: Completar metadados, dados e pistas**

Mission 004 deve destacar `debugging`, `pytest`, `edge_cases` e `ai_code_review`. Mission 005 deve destacar `decomposition`, `csv`, `json`, `exceptions`, `pytest` e `modules`. Incluir datasets pequenos, legíveis e versões com edge cases nos testes.

- [ ] **Step 6: Commit**

```bash
git add missions/004-recuperar-script missions/005-relatorio-operacional
git commit -m "feat: add debugging and capstone missions"
```

---

### Task 9: Verificação ponta a ponta e documentação de uso

**Files:**
- Create: `README.md`
- Create: `tests/test_end_to_end.py`
- Modify: arquivos encontrados durante a verificação somente quando uma falha reproduzível exigir correção.

**Interfaces:**
- Consumes: todos os componentes anteriores.
- Produces: jornada completa verificável e instruções de instalação/uso.

- [ ] **Step 1: Escrever teste ponta a ponta com progresso temporário**

```python
def test_complete_first_mission_updates_progress(test_app, solved_mission_001):
    test_app.start("001")
    test_app.save_plan({"input":"registros", "output":"totais", "steps":"acumular e comparar", "risks":"lista vazia"})
    result = test_app.run_current_tests(solution_path=solved_mission_001)
    assert result.passed
    test_app.save_explanation("Usei um dicionário para acumular minutos por equipamento.")
    test_app.complete_current_mission()
    reloaded = test_app.repository.load()
    assert reloaded.missions["001"].status == "completed"
    assert any(item["skill"] == "collections" for item in reloaded.evidence)
```

- [ ] **Step 2: Executar teste ponta a ponta**

Run: `python -m pytest tests/test_end_to_end.py -v`

Expected: PASS; se falhar, corrigir somente a integração reproduzida e adicionar teste de regressão específico.

- [ ] **Step 3: Escrever README operacional**

Documentar exatamente:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python lab.py
```

Incluir o tripé Goal/Skills/Missions, comandos, ciclo de uma sessão, localização das soluções e regra de ajuda. Explicar que a solução de referência afeta a evidência e que progresso real não deve ser commitado.

- [ ] **Step 4: Executar a suíte completa**

Run: `python -m pytest -v`

Expected: todos os testes do motor e integração PASS.

- [ ] **Step 5: Validar todas as soluções de referência**

Executar cada suíte contra sua referência por meio do mecanismo de teste usado nos testes de conteúdo.

Expected: cinco referências com 100% dos testes aprovados.

- [ ] **Step 6: Fazer smoke test manual no Windows ou PowerShell compatível**

Fluxo: `/goal` → `/skills` → `/start 001` → `/plan` → `/test` → `/hint` → `/status` → `/exit` → reiniciar.

Expected: nenhuma exceção; progresso confirmado aparece após reinício; missão não conclui enquanto faltarem testes ou explicação.

- [ ] **Step 7: Commit final da v0.1**

```bash
git add README.md tests python_lab missions data pyproject.toml lab.py
git commit -m "docs: complete Python Lab v0.1 handoff"
```

---

## Gate de validação após implementação

O desenvolvimento termina com software tecnicamente íntegro, não com produto validado. Lucas deverá usar o Lab em pelo menos cinco sessões e concluir as cinco Missions. Só então serão avaliados retorno espontâneo, quantidade de ajuda, erros recorrentes, capacidade de explicação e transferência das Skills para outro contexto.

Uma integração com `ai-tutor`, uma CLI TUI mais sofisticada ou uma interface web exige evidência de necessidade surgida nesse período de uso.
