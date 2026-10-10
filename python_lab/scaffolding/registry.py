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

# Distribution -> import namespace for the generated projects' tooling, dev and
# tested transitive dependencies. Curated here, never discovered via pip/network.
_COMMON_DEPENDENCIES = {
    "pip": "pip",
    "setuptools": "setuptools",
    "wheel": "wheel",
    "pytest": "pytest",
    "iniconfig": "iniconfig",
    "packaging": "packaging",
    "pluggy": "pluggy",
    "pygments": "pygments",
    "colorama": "colorama",  # pytest/Click on Windows, absent from Linux freeze.
}
DEPENDENCY_NAMES: dict[str, dict[str, str]] = {
    "cli": dict(_COMMON_DEPENDENCIES),
    "fastapi": {
        **_COMMON_DEPENDENCIES,
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "starlette": "starlette",
        "httpx": "httpx",
        "httpcore": "httpcore",
        "h11": "h11",
        "anyio": "anyio",
        "certifi": "certifi",
        "click": "click",
        "idna": "idna",
        "pydantic": "pydantic",
        "pydantic-core": "pydantic_core",
        "typing-extensions": "typing_extensions",
        "typing-inspection": "typing_inspection",
        "annotated-doc": "annotated_doc",
        "annotated-types": "annotated_types",
    },
}
