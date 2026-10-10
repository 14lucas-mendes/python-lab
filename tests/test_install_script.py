"""Native Windows installer checks; Ubuntu CI still runs all runner/TUI tests."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_installer_validates_before_persisting_path():
    script = (ROOT / "scripts" / "install-lab.ps1").read_text()
    check = script.index("& $lab --version")
    assert "LASTEXITCODE" in script[check:script.index("$userPath")]
    assert script.index("sys.version_info") < script.index("SetEnvironmentVariable")
    assert check < script.index("SetEnvironmentVariable")


@pytest.mark.skipif(sys.platform != "win32", reason="Native PowerShell/Windows installer")
def test_native_installer_checks_and_path_roundtrip(tmp_path):
    script = ROOT / "scripts" / "install-lab.ps1"
    pwsh = shutil.which("pwsh")
    assert pwsh, "Windows CI requires PowerShell"
    # Actual installed lab.exe; restore the original user PATH even on failure.
    command = """
$ErrorActionPreference = 'Stop'
$script = $env:LAB_INSTALL_SCRIPT
$before = [Environment]::GetEnvironmentVariable('Path', 'User')
try {
    & $script -CheckOnly
    if ([Environment]::GetEnvironmentVariable('Path', 'User') -ne $before) { throw 'CheckOnly changed PATH' }
    & $script
    & $script
    $scripts = Join-Path (Split-Path -Parent (Split-Path -Parent $script)) '.venv\\Scripts'
    $parts = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';'
    if (@($parts | Where-Object { $_ -eq $scripts }).Count -ne 1) { throw 'PATH was not installed idempotently' }
} finally {
    [Environment]::SetEnvironmentVariable('Path', $before, 'User')
}
"""
    env = os.environ.copy()
    env["LAB_INSTALL_SCRIPT"] = str(script)
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Native PowerShell/Windows installer")
@pytest.mark.parametrize("failure", ["missing", "exit", "wrong-version"])
def test_native_installer_failure_does_not_change_path(tmp_path, failure):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "install-lab.ps1"
    content = (ROOT / "scripts" / "install-lab.ps1").read_text()
    venv = tmp_path / ".venv" / "Scripts"
    venv.mkdir(parents=True)
    # A cmd shim lets the real PowerShell process test LASTEXITCODE and version
    # mismatch independently. This changes only the temp copy of the installer.
    if failure != "missing":
        content = content.replace('"lab.exe"', '"lab.cmd"')
        (venv / "lab.cmd").write_text('@echo off\nexit /b 9\n' if failure == "exit" else
                                      '@echo off\necho python-lab 999.0.0\nexit /b 0\n')
    # Use this suite's real venv interpreter, including installed metadata.
    content = content.replace('$python = Join-Path $scripts "python.exe"',
                              "$python = $env:LAB_TEST_PYTHON")
    script.write_text(content, encoding="utf-8")
    env = os.environ.copy()
    env["LAB_INSTALL_SCRIPT"] = str(script)
    env["LAB_TEST_PYTHON"] = sys.executable
    command = """
$before = [Environment]::GetEnvironmentVariable('Path', 'User')
$failed = $false
try { & $env:LAB_INSTALL_SCRIPT } catch { $failed = $true; Write-Output $_ }
if (-not $failed) { throw 'Installer accepted a broken installation' }
if ([Environment]::GetEnvironmentVariable('Path', 'User') -ne $before) { throw 'Failure changed PATH' }
"""
    result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = {"missing": "nao encontrado", "exit": "codigo 9", "wrong-version": "Versao inesperada"}
    assert expected[failure] in result.stdout
