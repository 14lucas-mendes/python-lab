"""Domain errors shared by state storage backends."""


class ProgressError(Exception):
    """Invalid or unavailable progress state."""


class SessionError(Exception):
    """Invalid or unavailable session history."""
