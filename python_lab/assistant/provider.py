"""Session output-token accounting, independent of SDK and model payloads."""

from uuid import uuid4

from python_lab.assistant.errors import AssistantError
from python_lab.assistant.models import LLMProvider, ReviewProvider

__all__ = ["LLMProvider", "ReviewProvider", "UsageBudget"]


def _tokens(value: object, *, positive: bool = False) -> None:
    if type(value) is not int or value < (1 if positive else 0):
        raise AssistantError("Tokens do orçamento devem ser inteiros válidos.")


class UsageBudget:
    """One object per local session; share it when recreating provider instances.

    Reservations count immediately, including concurrent sends. Unknown usage
    keeps the full reservation. This bounds output tokens, not input or money.
    Runtime persistence of a conversation must also preserve its budget; this
    in-memory object deliberately does not create or restore conversation state.
    """

    def __init__(self, limit: int):
        _tokens(limit)
        self._limit = limit
        self._used = 0
        self._pending: dict[str, int] = {}
        self._held = 0

    def reserve(self, tokens: int) -> str:
        _tokens(tokens, positive=True)
        if self._used + self._held + sum(self._pending.values()) + tokens > self._limit:
            raise AssistantError("O orçamento de tokens de saída da sessão foi atingido.")
        reservation = uuid4().hex
        self._pending[reservation] = tokens
        return reservation

    def settle(self, reservation: str, output_tokens: int | None) -> None:
        if not isinstance(reservation, str) or reservation not in self._pending:
            raise AssistantError("Reserva do orçamento desconhecida ou já liquidada.")
        if output_tokens is not None:
            _tokens(output_tokens)
        reserved = self._pending.pop(reservation)
        if output_tokens is None:
            self._held += reserved
        else:
            # Charge reported usage even if it exceeds the reserved amount.
            self._used += output_tokens
