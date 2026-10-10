"""Explicit resource manifests: generation never recursively copies a directory."""

_FILES = (
    "pyproject.toml",
    "README.md",
    ".gitignore",
    "src/__package__/__init__.py",
    "src/__package__/main.py",
    "tests/test_app.py",
)

TEMPLATES: dict[str, tuple[str, ...]] = {"cli": _FILES, "fastapi": _FILES}
