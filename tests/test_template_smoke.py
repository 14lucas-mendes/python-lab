"""Explicit network preparation, then offline generated-project functional checks.

Opt in with PYTHON_LAB_TEMPLATE_SMOKE=1; the ordinary Lab suite never installs
packages. Each template gets its own venv, with no inherited site packages.
"""

import os
from pathlib import Path
import subprocess
import sys
import venv

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("PYTHON_LAB_TEMPLATE_SMOKE") != "1",
    reason="Clean-venv dependency installation is a separate opt-in smoke stage",
)
CONSTRAINTS = Path(__file__).resolve().parents[1] / "constraints/template-smoke.txt"


def run(command, cwd, *, timeout=180):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [str(arg) for arg in command], cwd=cwd, env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )
    print(f"Command: {command}\n{result.stdout}\n{result.stderr}")
    assert result.returncode == 0, f"exit {result.returncode}: {result.stdout}\n{result.stderr}"
    return result


@pytest.mark.parametrize("template", ["cli", "fastapi"])
def test_generated_project_in_clean_venv(tmp_path, template):
    # Supported Lab artifact: editable install. -I + outside cwd ensures the
    # generator/resources are available through the installed artifact.
    target = tmp_path / f"{template}-app"
    run([
        sys.executable, "-I", "-c",
        "from importlib import metadata; import json; "
        "direct_url = json.loads(metadata.distribution('python-lab').read_text('direct_url.json') or '{}'); "
        "assert direct_url.get('dir_info', {}).get('editable') is True; "
        "from pathlib import Path; from python_lab.scaffolding import ScaffoldService; "
        "import sys; result = ScaffoldService().create(sys.argv[1], Path(sys.argv[2])); "
        "assert (result.target / '.gitignore').is_file(); print(result)",
        template, target,
    ], tmp_path)
    venv_dir = tmp_path / f"{template}-venv"
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(venv_dir)
    executable_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python = executable_dir / ("python.exe" if os.name == "nt" else "python")
    assert "include-system-site-packages = false" in (venv_dir / "pyvenv.cfg").read_text()
    run([python, "-m", "pip", "install", "-c", CONSTRAINTS, "-e", ".[dev]"], target)
    run([python, "-m", "pip", "check"], target)
    suite = run([python, "-m", "pytest", "-q"], target)
    assert "1 passed" in suite.stdout
    if template == "cli":
        command = run([python, "-m", "cli_app.main", "--name", "Ana"], target)
        assert command.stdout == "Olá, Ana!\n"
        console = executable_dir / ("cli_app.exe" if os.name == "nt" else "cli_app")
        assert run([console, "--name", "Ana"], target).stdout == "Olá, Ana!\n"
    else:
        request = run([
            python, "-c",
            "from fastapi.testclient import TestClient; from fastapi_app.main import app; "
            "client = TestClient(app); response = client.get('/health'); "
            "assert response.status_code == 200; "
            "assert response.json() == {'status': 'ok'}; print(response.status_code, response.json())",
        ], target)
        assert "200 {'status': 'ok'}" in request.stdout
    run([python, "-m", "pip", "freeze", "--exclude-editable"], target)
