import socket

from __package__.main import echo


def test_echo_is_local_and_preserves_unicode(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Bot tests must not use network")
    monkeypatch.setattr(socket, "socket", forbidden)
    assert echo("olá") == "Eco: olá"
    assert echo("ação") == "Eco: ação"
