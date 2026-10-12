from __package__.main import main


def test_greeting(capsys):
    assert main(["--name", "Ana"]) == 0
    assert capsys.readouterr().out == "Olá, Ana!\n"
