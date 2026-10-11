"""SDK-independent, bounded single-file exercise drafts.

References are private review material. Accessing one explicitly is full-solution
(level 4) assistance; technical validation does not establish didactic quality.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import re
from typing import Protocol

from python_lab.assistant.errors import AssistantError
from python_lab.assistant.models import AssistantRequest

MAX_DRAFT_FILE_BYTES = 262144
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')
MISSION_FIELDS = {
    'id', 'slug', 'title', 'summary', 'skills', 'prerequisites', 'cycle',
    'lesson_id', 'success_criteria', 'learning_objectives', 'reflection_questions',
    'tests', 'solution',
}


def identifier(value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise AssistantError('Identificador de exercício inválido; use letras, números, _ ou -.')
    return value


def text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise AssistantError(f'Campo {field_name} deve ser texto não vazio.')
    try:
        encoded = value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise AssistantError(f'Campo {field_name} deve ser UTF-8 válido.') from None
    if len(encoded) > MAX_DRAFT_FILE_BYTES:
        raise AssistantError(f'Campo {field_name} excedeu o limite de bytes.')
    return value


def mission_payload(value: object, draft_id: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) - MISSION_FIELDS:
        raise AssistantError('Metadados de missão inválidos.')
    mission = dict(value)
    if mission.get('id') != draft_id:
        raise AssistantError('ID da missão diverge do draft.')
    identifier(mission['id'])
    mission['slug'] = identifier(mission.get('slug', draft_id))
    for name in ('title', 'summary', 'lesson_id'):
        mission[name] = text(mission.get(name), name)
    cycle = mission.get('cycle')
    if type(cycle) is not int or not 1 <= cycle <= 13:
        raise AssistantError('cycle deve ser inteiro de 1 a 13.')
    for name in ('skills', 'prerequisites', 'success_criteria', 'learning_objectives', 'reflection_questions'):
        items = mission.get(name, [] if name in ('prerequisites', 'learning_objectives', 'reflection_questions') else None)
        if not isinstance(items, list) or len(items) > 64:
            raise AssistantError(f'Campo {name} deve ser lista de textos.')
        mission[name] = [text(item, name) for item in items]
        if len(items) != len(set(items)):
            raise AssistantError(f'Campo {name} contém duplicatas.')
        if name in ('skills', 'success_criteria') and not items:
            raise AssistantError(f'Campo {name} não pode ser vazio.')
        if name in ('skills', 'prerequisites'):
            for item in items:
                identifier(item)
    for name, expected in (('tests', 'tests'), ('solution', 'starter.py')):
        if mission.get(name, expected) != expected:
            raise AssistantError('Exercício inicial usa apenas starter.py e tests controlados.')
        mission[name] = expected
    text(json.dumps(mission, ensure_ascii=False, allow_nan=False), 'mission')
    return mission


@dataclass(frozen=True)
class ExerciseDraft:
    id: str
    mission: dict[str, object]
    briefing: str
    starter: str
    reference: str = field(repr=False)
    tests: str


class ExerciseProvider(Protocol):
    async def draft(self, request: AssistantRequest) -> ExerciseDraft: ...


def validate_draft(payload: object) -> ExerciseDraft:
    if not isinstance(payload, Mapping) or set(payload) != {'id', 'mission', 'briefing', 'starter', 'reference', 'tests'}:
        raise AssistantError('Draft estruturado inválido.')
    draft_id = identifier(payload['id'])
    return ExerciseDraft(draft_id, mission_payload(payload['mission'], draft_id),
                         *(text(payload[name], name) for name in ('briefing', 'starter', 'reference', 'tests')))


@dataclass(frozen=True)
class DraftValidation:
    passed: bool
    fingerprint: str
    detail: str = ''
    cancelled: bool = False
