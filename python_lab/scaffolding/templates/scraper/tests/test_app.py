from pathlib import Path
import socket

from __package__.main import extract_title


def test_title_from_local_utf8_fixture(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Scraper tests must not use network")
    monkeypatch.setattr(socket, "socket", forbidden)
    html = (Path(__file__).parent / "fixtures/page.html").read_text(encoding="utf-8")
    assert extract_title(html) == "Olá & Python"
    assert extract_title("<html>sem título</html>") == ""
    assert extract_title("<title> Primeiro </title><title>Segundo</title>") == "Primeiro"
