"""Explicit, secret-free settings for the optional assistant."""

from dataclasses import dataclass, fields
from pathlib import Path
import tomllib

from python_lab.assistant.errors import AssistantError


def _positive_integer(value: object, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise AssistantError(f"{label} deve ser um inteiro positivo.")


@dataclass(frozen=True)
class AssistantSettings:
    provider: str
    model: str | None
    timeout_seconds: int = 30
    max_output_tokens: int = 2000
    max_session_output_tokens: int = 20000

    def __post_init__(self) -> None:
        if self.provider not in ("disabled", "openai"):
            raise AssistantError("Configure provider='openai' em config.toml.")
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise AssistantError("Configure model como texto não vazio em config.toml.")
        for name in ("timeout_seconds", "max_output_tokens", "max_session_output_tokens"):
            _positive_integer(getattr(self, name), name)


def load_settings(data_dir: Path) -> AssistantSettings:
    """Missing configuration leaves mission workflows usable without an SDK."""
    try:
        with (data_dir / "config.toml").open("rb") as stream:
            values = tomllib.load(stream)
    except FileNotFoundError:
        return AssistantSettings("disabled", None)
    except (OSError, ValueError):
        raise AssistantError("Não foi possível ler config.toml; verifique a configuração TOML.") from None
    if set(values) - {field.name for field in fields(AssistantSettings)}:
        raise AssistantError("config.toml contém campos desconhecidos; chaves devem ficar em LAB_API_KEY.")
    if "provider" not in values:
        raise AssistantError("Configure provider='openai' em config.toml.")
    return AssistantSettings(**{"model": None, **values})
