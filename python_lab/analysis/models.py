"""Immutable findings from explicitly selected Python sources."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Issue:
    path: str
    line: int | None
    code: str
    message: str
    source: str


@dataclass(frozen=True)
class ToolCheck:
    tool: str
    status: Literal["passed", "failed", "unavailable"]
    issues: tuple[Issue, ...]


@dataclass(frozen=True)
class AnalysisReport:
    checks: tuple[ToolCheck, ...]
