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
    cycle: int = 1
    lesson_id: str = ""


@dataclass(frozen=True)
class RoadmapCycle:
    cycle: int
    title: str
    lesson_id: str
    milestone: str
    status: str


@dataclass
class MissionProgress:
    status: str = "available"
    plan: dict[str, str] | None = None
    attempts: int = 0
    tests_passed: bool = False
    hints_revealed: int = 0
    reference_viewed: bool = False
    explanation: str | None = None
    tested_solution_path: str | None = None
    tested_solution_fingerprint: str | None = None
    attempt_history: list[dict[str, object]] = field(default_factory=list)


@dataclass
class AppProgress:
    current_mission_id: str | None = None
    missions: dict[str, MissionProgress] = field(default_factory=dict)
    evidence: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class TestResult:
    passed: bool
    return_code: int
    output: str
    summary: str = ""
    diagnostics: tuple[str, ...] = ()
