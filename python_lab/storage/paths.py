"""Resolve the read-only catalog and writable user state locations."""

from dataclasses import dataclass
from pathlib import Path

import platformdirs


@dataclass(frozen=True)
class AppPaths:
    catalog_dir: Path
    data_dir: Path


def resolve_paths(catalog_dir: Path, data_dir: Path | None) -> AppPaths:
    """Choose a user data directory without creating or modifying either path."""
    chosen = data_dir if data_dir is not None else platformdirs.user_data_path(
        "python-lab", appauthor=False
    )
    if chosen.resolve().is_relative_to(catalog_dir.resolve()):
        raise ValueError("O diretório de dados deve ficar fora do catálogo")
    return AppPaths(catalog_dir=catalog_dir, data_dir=chosen)
