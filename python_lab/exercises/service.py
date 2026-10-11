"""Explicit local checks and atomic, hash-bound custom catalog publication.

Generated Python executes with the user's privileges after confirmation. Temporary
copies, limits and process cleanup are safeguards, not a security sandbox.
"""
import ast
from contextlib import closing, contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET

from python_lab.analysis.service import _temporary_parents
from python_lab.assistant.errors import AssistantError
from python_lab.catalog import CatalogError, _load_mission, compose_missions
from python_lab.exercises.models import (DraftValidation, ExerciseDraft, MAX_DRAFT_FILE_BYTES,
                                         identifier, mission_payload, validate_draft)
from python_lab.runtime.processes import ProcessCleanupError, ProcessRunner

_CONFTEXT = '''import json
from pathlib import Path
import pytest
from python_lab.solution_loader import load_solution

_reports = []

def pytest_addoption(parser):
    parser.addoption("--lab-solution", choices=["starter.py", "reference_solution.py"])
    parser.addoption("--lab-evidence")

@pytest.fixture
def solution(request):
    return load_solution(Path(__file__).parent.parent / request.config.getoption("--lab-solution"))

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    _reports.append({"phase": report.when, "outcome": report.outcome,
                     "assertion": call.excinfo is not None and call.excinfo.type is AssertionError})

def pytest_sessionfinish(session, exitstatus):
    Path(session.config.getoption("--lab-evidence")).write_text(json.dumps(_reports), encoding="utf-8")
'''
_FILES = {'draft.json', 'mission.json', 'README.md', 'criteria.json', 'starter.py',
          'reference_solution.py', 'hints.json', 'tests/conftest.py', 'tests/test_exercise.py'}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def _no_links(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise AssistantError('Paths de exercícios não podem conter symlinks.')


def _directory(path: Path) -> None:
    _no_links(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    _no_links(path)
    if os.name == 'posix':
        path.chmod(0o700)


class ExerciseService:
    def __init__(self, data_dir: Path, runner: ProcessRunner, *, catalog_dir: Path | None = None):
        self.data_dir = Path(os.path.abspath(data_dir))
        self.runner = runner
        self.catalog_dir = Path(catalog_dir) if catalog_dir is not None else Path(__file__).resolve().parents[2]
        self.catalog_dir = self.catalog_dir.resolve()
        if self.data_dir.is_relative_to(self.catalog_dir):
            raise AssistantError('Diretório de dados deve ficar fora do catálogo instalado.')
        self._lock = threading.RLock()

    @contextmanager
    def _transaction(self):
        # Serializes service instances and processes. All checks and the single
        # directory rename occur under the same lock; installed context is read-only.
        _directory(self.data_dir)
        lock = self.data_dir / 'exercise-publication.sqlite3'
        _no_links(lock)
        with self._lock, closing(sqlite3.connect(lock, timeout=30)) as database, database:
            database.execute('BEGIN IMMEDIATE')
            yield

    def _compose(self, candidate: Path, catalog_dir: Path | None = None) -> None:
        try:
            compose_missions(catalog_dir or self.catalog_dir, self.data_dir / 'custom_catalog',
                             additional=(_load_mission(candidate / 'mission.json'),))
        except (CatalogError, OSError, ValueError) as exc:
            raise AssistantError(f'Catálogo de exercício inválido: {exc}') from exc

    def save_draft(self, draft: ExerciseDraft) -> Path:
        if not isinstance(draft, ExerciseDraft):
            raise AssistantError('Draft de exercício inválido.')
        checked = validate_draft(asdict(draft))
        mission = mission_payload(checked.mission, checked.id)
        files = {
            'draft.json': _json({'id': checked.id, 'format_version': 1}),
            'mission.json': _json(mission), 'README.md': checked.briefing,
            'criteria.json': _json(mission['success_criteria']), 'starter.py': checked.starter,
            'reference_solution.py': checked.reference, 'hints.json': '[]\n',
            'tests/conftest.py': _CONFTEXT, 'tests/test_exercise.py': checked.tests,
        }
        with self._transaction():
            drafts = self.data_dir / 'exercise_drafts'
            _directory(drafts)
            target = drafts / checked.id
            _no_links(target)
            if target.exists():
                raise AssistantError('ID de draft já existe; preserve a revisão anterior.')
            with tempfile.TemporaryDirectory(prefix='.exercise-save-', dir=self.data_dir) as temporary:
                stage = Path(temporary) / checked.id
                _directory(stage / 'tests')
                for name, content in files.items():
                    encoded = content.encode('utf-8', errors='strict')
                    if len(encoded) > MAX_DRAFT_FILE_BYTES:
                        raise AssistantError('Arquivo de draft excedeu o limite de bytes.')
                    file = stage / name
                    with file.open('xb') as stream:
                        stream.write(encoded)
                    if os.name == 'posix':
                        file.chmod(0o600)
                self._compose(stage)
                os.rename(stage, target)
            return target

    def _read(self, draft_path: Path) -> tuple[Path, dict[str, bytes], str]:
        path = Path(os.path.abspath(draft_path))
        _no_links(path)
        drafts = self.data_dir / 'exercise_drafts'
        if path.parent != drafts or not path.is_dir():
            raise AssistantError('Path de draft inválido; use um draft privado salvo localmente.')
        identifier(path.name)
        files: dict[str, bytes] = {}
        try:
            for file in path.rglob('*'):
                _no_links(file)
                name = file.relative_to(path).as_posix()
                if file.is_dir() and name == 'tests':
                    continue
                if name not in _FILES or not file.is_file():
                    raise AssistantError('Material de draft inesperado ou inválido.')
                with file.open('rb') as stream:
                    content = stream.read(MAX_DRAFT_FILE_BYTES + 1)
                if len(content) > MAX_DRAFT_FILE_BYTES:
                    raise AssistantError('Arquivo de draft excedeu o limite de bytes.')
                content.decode('utf-8', errors='strict')
                files[name] = content
            if set(files) != _FILES:
                raise AssistantError('Material de draft incompleto.')
            metadata = json.loads(files['draft.json'])
            if metadata != {'id': path.name, 'format_version': 1} or type(metadata.get('format_version')) is not int:
                raise AssistantError('Metadados de draft inválidos.')
            mission = mission_payload(json.loads(files['mission.json']), path.name)
            validate_draft({'id': path.name, 'mission': mission, 'briefing': files['README.md'].decode(),
                            'starter': files['starter.py'].decode(), 'reference': files['reference_solution.py'].decode(),
                            'tests': files['tests/test_exercise.py'].decode()})
            if json.loads(files['criteria.json']) != mission['success_criteria']:
                raise AssistantError('Critérios divergem dos metadados da missão.')
            if files['tests/conftest.py'].decode() != _CONFTEXT or json.loads(files['hints.json']) != []:
                raise AssistantError('Harness controlado mudou; salve um novo draft.')
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise AssistantError('Material de draft inválido ou UTF-8 indisponível.') from exc
        digest = hashlib.sha256()
        for name, content in sorted(files.items()):
            digest.update(name.encode() + b'\0' + len(content).to_bytes(8, 'big') + content)
        return path, files, digest.hexdigest()

    @contextmanager
    def _external_temp(self, path: Path, cancel: threading.Event | None):
        # Do not call gettempdir(): it probes TMPDIR by writing before validation.
        roots = (self.data_dir, path, self.catalog_dir, Path.cwd().resolve())
        for candidate in _temporary_parents():
            if cancel is not None and cancel.is_set():
                yield None
                return
            try:
                parent = Path(candidate).resolve(strict=True)
                if any(parent.is_relative_to(root) for root in roots) or not parent.is_dir():
                    continue
                temporary = tempfile.TemporaryDirectory(prefix='python-lab-exercise-', dir=parent)
            except (OSError, ValueError, RuntimeError):
                continue
            with temporary as directory:
                yield Path(directory)
            return
        raise AssistantError('Não há diretório temporário externo para validar exercício.')

    def _record_path(self, draft_path: Path) -> Path:
        return self.data_dir / 'exercise_validations' / (draft_path.name + '.json')

    def _record(self, path: Path, result: DraftValidation) -> None:
        with self._transaction():
            directory = self._record_path(path).parent
            _directory(directory)
            target = self._record_path(path)
            _no_links(target)
            fd, temporary = tempfile.mkstemp(prefix='.validation-', dir=directory)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(_json(asdict(result)))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def _run(self, stage: Path, selected: str, cancel: threading.Event | None) -> tuple[bool, bool, bool]:
        report, evidence = stage / f'{selected}.xml', stage / f'{selected}.json'
        # Fixed invocation, explicit fixture selection, isolated config and cache.
        args = [str(stage / 'tests'), '-q', '-c', str(stage / 'pytest.ini'),
                '--confcutdir', str(stage), '-p', 'no:cacheprovider',
                '--basetemp', str(stage / f'{selected}-tmp'), '--junitxml', str(report),
                '--lab-solution', selected, '--lab-evidence', str(evidence)]
        script = ('import os, sys; sys.dont_write_bytecode=True; '
                  'os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"; '
                  'import pytest; sys.exit(pytest.main(' + repr(args) + '))')
        try:
            completed = self.runner.run([sys.executable, '-I', '-c', script], cwd=stage,
                                        timeout=30.0, output_limit=1048576, cancel=cancel)
        except ProcessCleanupError:
            raise
        except OSError:
            return False, False, False
        cancelled = completed.cancelled or (cancel is not None and cancel.is_set())
        if cancelled or completed.timed_out or completed.truncated:
            return False, False, cancelled
        try:
            root = ET.parse(report).getroot()
            cases = list(root.iter('testcase'))
            reports = json.loads(evidence.read_text(encoding='utf-8'))
            calls = [item for item in reports if item['phase'] == 'call']
            failures = [item for item in reports if item['outcome'] == 'failed']
            rejected = not cases or len(calls) != len(cases) or any(
                case.find('error') is not None or case.find('skipped') is not None for case in cases
            ) or any(item['outcome'] == 'skipped' for item in reports)
            success = completed.return_code == 0 and not rejected and not failures and all(
                case.find('failure') is None for case in cases
            )
            contract_failure = completed.return_code == 1 and not rejected and bool(failures) and all(
                item['phase'] == 'call' and item['assertion'] is True for item in failures
            ) and any(case.find('failure') is not None for case in cases)
            return success, contract_failure, False
        except (OSError, ValueError, TypeError, KeyError, ET.ParseError):
            return False, False, False

    def validate(self, draft_path: Path, *, execution_confirmed: bool,
                 cancel: threading.Event | None = None) -> DraftValidation:
        if execution_confirmed is not True:
            raise AssistantError('É necessária confirmação explícita antes de executar o exercício.')
        path, files, fingerprint = self._read(draft_path)
        # Invalidate any previous success before starting a new explicit check.
        result = DraftValidation(False, fingerprint, 'Validação técnica incompleta.')
        self._record(path, result)
        self._compose(path)
        if cancel is not None and cancel.is_set():
            result = DraftValidation(False, fingerprint, 'Validação cancelada.', True)
        else:
            try:
                for name in ('starter.py', 'reference_solution.py', 'tests/test_exercise.py'):
                    ast.parse(files[name].decode(), filename=name)
            except (SyntaxError, ValueError):
                result = DraftValidation(False, fingerprint, 'Sintaxe inválida; não é falha do contrato.')
            else:
                with self._external_temp(path, cancel) as stage:
                    if stage is None:
                        result = DraftValidation(False, fingerprint, 'Validação cancelada.', True)
                    else:
                        (stage / 'tests').mkdir()
                        for name in ('starter.py', 'reference_solution.py', 'tests/test_exercise.py', 'tests/conftest.py'):
                            (stage / name).write_bytes(files[name])
                        (stage / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
                        reference_pass, _, cancelled = self._run(stage, 'reference_solution.py', cancel)
                        starter_failure = False
                        if reference_pass and not cancelled:
                            _, starter_failure, cancelled = self._run(stage, 'starter.py', cancel)
                        result = DraftValidation(reference_pass and starter_failure and not cancelled, fingerprint,
                            'Referência aprovada; starter falha por assert do contrato. Revisão didática ainda necessária.'
                            if reference_pass and starter_failure and not cancelled else
                            'Suite vazia/ignorada, referência reprovada ou starter sem falha de contrato.', cancelled)
        # Hash before and after execution: code cannot change review material and
        # retain a successful validation; cleanup completed before this point.
        if self._read(path)[2] != fingerprint:
            result = DraftValidation(False, fingerprint, 'Draft mudou durante a validação.')
        self._record(path, result)
        return result

    def publish(self, draft_path: Path, catalog_dir: Path, *, approved: bool) -> Path:
        if approved is not True:
            raise AssistantError('É necessária aprovação explícita para publicar exercício.')
        installed = Path(catalog_dir).resolve()
        if self.data_dir.is_relative_to(installed):
            raise AssistantError('Diretório de dados deve ficar fora do catálogo instalado.')
        with self._transaction():
            path, files, fingerprint = self._read(draft_path)
            record = self._record_path(path)
            _no_links(record)
            try:
                saved = json.loads(record.read_text(encoding='utf-8'))
                if saved.get('passed') is not True or saved.get('cancelled') is not False or saved.get('fingerprint') != fingerprint:
                    raise AssistantError('Draft mudou ou não possui validação técnica aprovada.')
            except (OSError, ValueError, AttributeError) as exc:
                raise AssistantError('Draft precisa de validação técnica antes de publicar.') from exc
            self._compose(path, installed)
            custom = self.data_dir / 'custom_catalog'
            _directory(custom)
            target = custom / path.name
            _no_links(target)
            if target.exists():
                raise AssistantError('ID de missão já publicado.')
            with tempfile.TemporaryDirectory(prefix='.exercise-publish-', dir=self.data_dir) as temporary:
                stage = Path(temporary) / path.name
                _directory(stage / 'tests')
                for name, content in files.items():
                    (stage / name).write_bytes(content)
                    if os.name == 'posix':
                        (stage / name).chmod(0o600)
                # Recheck both copied material and installed/custom relations
                # immediately before the one filesystem mutation making it public.
                if self._read(path)[2] != fingerprint:
                    raise AssistantError('Draft mudou durante a publicação.')
                self._compose(stage, installed)
                os.rename(stage, target)
            return target
