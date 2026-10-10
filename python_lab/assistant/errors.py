"""Public errors for explicit context and assistant operations."""

from python_lab.app import ApplicationError


class ContextError(ApplicationError):
    """Selected project context is invalid or cannot safely be captured."""


class AssistantError(ApplicationError):
    """An assistant request or response violates the shared contract."""
