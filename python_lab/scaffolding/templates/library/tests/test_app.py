import socket
from typing import get_type_hints

from __package__.main import greet


def test_typed_greeting_is_local(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Library tests must not use network")
    monkeypatch.setattr(socket, "socket", forbidden)
    assert greet("Ana") == "Olá, Ana!"
    assert greet("João") == "Olá, João!"
    assert get_type_hints(greet) == {"name": str, "return": str}
