"""Results of creating a curated project; no execution is implied."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScaffoldResult:
    target: Path
    files: tuple[Path, ...]
    template: str
