"""Shared, SDK-independent learning actions; generation never proves competence."""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import threading
from uuid import uuid4

from python_lab.app import ApplicationError, PythonLabApp
from python_lab.assistant.errors import AssistantError
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.models import AssistantRequest, WorkspaceSnapshot
from python_lab.commands import CommandDispatcher, CommandResult
from python_lab.exercises.models import ExerciseProvider, identifier
from python_lab.exercises.service import ExerciseService
from python_lab.learning_events import AssistanceEvent
from python_lab.presentation import practice_snapshot, practice_feedback
from python_lab.progress import ProgressError
from python_lab.runtime.processes import ProcessCleanupError

LEARNING_ACTIONS = {'/exercise', '/exercise-validate', '/exercise-publish', '/exercise-show'}
Confirm = Callable[[CommandResult], Awaitable[bool]]


class LearningCommands:
    def __init__(self, app: PythonLabApp, provider: ExerciseProvider | None,
                 exercises: ExerciseService, *, provider_factory=None,
                 workspace: Path | None = None, mode: str = 'tutor'):
        self.app, self.provider, self.exercises = app, provider, exercises
        self.provider_factory = provider_factory
        self.workspace = workspace or app.project_root
        self.mode = mode

    def register(self, dispatcher: CommandDispatcher) -> None:
        dispatcher.register('/practice', self.practice)
        for name, handler in self.actions().items():
            dispatcher.register_async(name, handler)

    def actions(self):
        return {'/exercise': self.draft, '/exercise-validate': self.validate,
                '/exercise-publish': self.publish, '/exercise-show': self.show}

    @staticmethod
    def error(exc, kind='usage'):
        return CommandResult(False, str(exc), {'error_kind': kind})

    def practice(self, args: tuple[str, ...]) -> CommandResult:
        if args not in ((), ('--review-completed',)):
            return self.error('Uso: /practice [--review-completed].')
        try:
            snapshot = practice_snapshot(self.app.missions, self.app.progress,
                include_completed=bool(args), workspace=self.workspace,
                history=ConversationRepository(self.exercises.data_dir / 'lab.sqlite3'))
        except AssistantError as exc:
            return self.error(exc, 'execution')
        data = asdict(snapshot)
        for reference in data['error_history']:
            reference['workspace'] = str(reference['workspace'])
        return CommandResult(True, practice_feedback(snapshot), data)

    async def _blocking(self, function, cancel):
        if cancel.is_set():
            raise asyncio.CancelledError()
        worker = asyncio.create_task(asyncio.to_thread(function))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel.set()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            try:
                worker.result()
            except ProcessCleanupError:
                raise
            except Exception:
                pass
            raise

    def _identity(self):
        mission = self.app.progress.current_mission_id
        return mission, self.app.capture_assistance_attempt(mission)

    def _record(self, mission, attempt, request_id, level, action):
        self.app.record_assistance(AssistanceEvent(
            mission, action, level, datetime.now(timezone.utc).isoformat(), request_id,
        ), attempt_id=attempt)

    async def draft(self, args, *, cancel=None):
        action_cancel = cancel or threading.Event()
        try:
            if not args or any(value.startswith('--') for value in args):
                raise ValueError('Uso: /exercise TOPIC.')
            mission, attempt = self._identity()
            request_id = uuid4().hex
            provider = self.provider
            if provider is None and self.provider_factory is not None:
                provider = self.provider_factory()
            if provider is None:
                raise AssistantError('IA indisponível: configure provider, model, LAB_API_KEY e o extra assistant; drafts salvos continuam disponíveis.')
            if action_cancel.is_set():
                raise asyncio.CancelledError()
            context = '\n'.join(f'{item.id}: ciclo={item.cycle}, lesson_id={item.lesson_id}, skills={list(item.skills)}'
                                for item in self.app.missions)
            request = AssistantRequest('exercise', 'Crie um exercício draft de arquivo único sobre: '
                + ' '.join(args) + '\nCatálogo local (IDs existentes não podem ser reutilizados):\n' + context,
                self.mode, 0, WorkspaceSnapshot(self.workspace, ()), mission_id=mission)
            try:
                generated = await provider.draft(request)
            except AssistantError as exc:
                return self.error(exc, 'execution')
            if action_cancel.is_set():
                raise asyncio.CancelledError()
            # Bounded local persistence is the commit boundary: no await between
            # accepting the result, saving material and recording its local event.
            path = self.exercises.save_draft(generated)
            self._record(mission, attempt, request_id, 0, 'exercise')
            _, files, _ = self.exercises._read(path)
            return self._review(path, files)
        except (ValueError, AssistantError, ApplicationError) as exc:
            return self.error(exc)
        except (OSError, ProgressError) as exc:
            return self.error(exc, 'execution')

    def _path(self, value):
        return self.exercises.data_dir / 'exercise_drafts' / identifier(value)

    @staticmethod
    def _arguments(args, *, reference=False):
        allowed = {'--yes', '--reference'} if reference else {'--yes'}
        if not args or any(value not in allowed for value in args[1:]) or len(set(args[1:])) != len(args[1:]):
            raise ValueError('Informe um ID local e apenas as opções permitidas.')
        return args[0], '--yes' in args, '--reference' in args

    @staticmethod
    def _review(path, files):
        briefing = files['README.md'].decode('utf-8')
        starter = files['starter.py'].decode('utf-8')
        tests = files['tests/test_exercise.py'].decode('utf-8')
        return CommandResult(True, f'Draft {path.name} · {path}\n{briefing}\nStarter:\n{starter}\nTestes propostos (não executados):\n{tests}\n'
            f'Revisão didática necessária. Referência oculta; /exercise-show {path.name} --reference --yes conta como ajuda nível 4.\n'
            f'Próximo: /exercise-validate {path.name}; publicar exige aprovação separada.',
            {'id': path.name, 'path': str(path), 'status': 'draft', 'briefing': briefing,
             'starter': starter, 'tests': tests, 'assistance_level': 0})

    async def validate(self, args, *, cancel=None, confirm: Confirm | None = None):
        action_cancel = cancel or threading.Event()
        try:
            identity, yes, _ = self._arguments(args)
            path = self._path(identity)
            preview = CommandResult(False, f'Validar exercício {identity}: executar referência e testes gerados em cópias temporárias.\n'
                f'Material: {path}\nExecução com seus privilégios de usuário; sem sandbox.\n'
                f'Confirme explicitamente: lab exercises validate {identity} --yes.',
                {'id': identity, 'path': str(path), 'status': 'draft', 'error_kind': 'usage'})
            confirmed = await confirm(preview) if confirm else yes
            if not confirmed:
                return preview
            result = await self._blocking(lambda: self.exercises.validate(
                path, execution_confirmed=True, cancel=action_cancel), action_cancel)
            if result.cancelled or action_cancel.is_set():
                raise asyncio.CancelledError()
            # Failed assertions/invalid draft suites are findings, not competence.
            return CommandResult(True, result.detail, {'id': identity, 'path': str(path),
                'status': 'validated' if result.passed else 'validation_failed', 'validation': asdict(result),
                'competence_approved': False})
        except (ValueError, AssistantError) as exc:
            return self.error(exc)
        except (OSError, ProcessCleanupError) as exc:
            return self.error(exc, 'execution')

    async def publish(self, args, *, cancel=None, confirm: Confirm | None = None):
        action_cancel = cancel or threading.Event()
        try:
            identity, yes, _ = self._arguments(args)
            path = self._path(identity)
            destination = self.exercises.data_dir / 'custom_catalog' / identity
            preview = CommandResult(False, f'Publicar exercício revisado {identity}.\nMaterial: {path}\nDestino: {destination}\n'
                f'Aprovar revisão didática e adicionar ao catálogo local com seus privilégios de usuário.\n'
                f'Esta aprovação não executa código nem aprova competência. Confirme: lab exercises publish {identity} --yes.',
                {'id': identity, 'path': str(destination), 'status': 'draft', 'error_kind': 'usage'})
            confirmed = await confirm(preview) if confirm else yes
            if not confirmed:
                return preview
            if action_cancel.is_set():
                raise asyncio.CancelledError()
            target = self.exercises.publish(path, self.exercises.catalog_dir, approved=True)
            return CommandResult(True, f'Publicado em {target}. Reabra o Lab para carregar o catálogo composto; competência não aprovada.',
                                 {'id': identity, 'path': str(target), 'status': 'published', 'competence_approved': False})
        except (ValueError, AssistantError) as exc:
            return self.error(exc)
        except OSError as exc:
            return self.error(exc, 'execution')

    async def show(self, args, *, cancel=None, confirm: Confirm | None = None):
        action_cancel = cancel or threading.Event()
        try:
            identity, yes, reference = self._arguments(args, reference=True)
            mission, attempt = self._identity()
            request_id = uuid4().hex
            path, files, _ = await self._blocking(lambda: self.exercises._read(self._path(identity)), action_cancel)
            if not reference:
                return self._review(path, files)
            preview = CommandResult(False, f'Consultar solução completa nível 4 de {identity}.\nMaterial: {path}\n'
                'Leitura e registro com seus privilégios de usuário; a tentativa capturada ficará assistida.\n'
                f'Confirme: lab exercises show {identity} --reference --yes.',
                {'id': identity, 'path': str(path), 'error_kind': 'usage', 'assistance_level': 4})
            confirmed = await confirm(preview) if confirm else yes
            if not confirmed:
                return preview
            if action_cancel.is_set():
                raise asyncio.CancelledError()
            self._record(mission, attempt, request_id, 4, 'exercise-reference')
            return CommandResult(True, f'Ajuda nível 4 · {path}\n' + files['reference_solution.py'].decode('utf-8'),
                                 {'id': identity, 'path': str(path), 'assistance_level': 4})
        except (ValueError, AssistantError, ApplicationError) as exc:
            return self.error(exc)
        except (OSError, ProgressError, ProcessCleanupError) as exc:
            return self.error(exc, 'execution')
