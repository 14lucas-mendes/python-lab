import socket

from __package__.main import app


def test_health_is_local(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Health tests must not use network")
    monkeypatch.setattr(socket, "socket", forbidden)
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
