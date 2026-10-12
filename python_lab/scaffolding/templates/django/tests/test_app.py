import os
import socket

import django
from django.test import Client

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "__package__.settings")
django.setup()


def test_health_is_local(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Health tests must not use network")
    monkeypatch.setattr(socket, "socket", forbidden)
    response = Client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
