import json

import pytest

from python_lab.cli import main
from python_lab.scaffolding import registry


@pytest.mark.parametrize('template', list(registry.TEMPLATES))
def test_new_only_generates_and_prints_next_commands(tmp_path, capsys, template):
    state = tmp_path / 'state'
    code = main(['new', template, 'my-app', '--path', str(tmp_path), '--data-dir', str(state), '--json'])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload['action'] == 'new'
    assert payload['data']['target'] == str(tmp_path / 'my-app')
    assert (tmp_path / 'my-app' / 'pyproject.toml').is_file()
    assert len(payload['data']['files']) == len(registry.TEMPLATES[template])
    assert 'pip install' in payload['message']
    assert not (tmp_path / 'my-app' / '.venv').exists()
    assert main(['new', template, 'my-app', '--path', str(tmp_path), '--json']) == 2
    capsys.readouterr()


def test_new_rejects_path_in_name_and_unknown_template(tmp_path, capsys):
    for template, name in [('cli', '../escape'), ('unregistered', 'app')]:
        assert main(['new', template, name, '--path', str(tmp_path), '--json']) == 2
        assert not json.loads(capsys.readouterr().out)['ok']
    assert list(tmp_path.iterdir()) == []
