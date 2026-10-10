param([switch]$CheckOnly)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$scripts = Join-Path $root ".venv\Scripts"
$lab = Join-Path $scripts "lab.exe"
$python = Join-Path $scripts "python.exe"

if (-not (Test-Path $lab) -or -not (Test-Path $python)) {
    throw "lab.exe ou python.exe nao encontrado em $scripts. Instale com: .venv\Scripts\python.exe -m pip install -c constraints\dev.txt -e `".[dev]`""
}

# Validate the interpreter, metadata and entrypoint before changing user state.
$expected = & $python -c "import sys; from importlib.metadata import version; sys.exit('Python Lab requer Python >=3.11') if sys.version_info < (3, 11) else None; print('python-lab ' + version('python-lab'))"
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao validar Python e metadados (codigo $LASTEXITCODE)."
}
$installed = & $lab --version
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao executar lab --version (codigo $LASTEXITCODE)."
}
if (($installed -join "`n").Trim() -ne ($expected -join "`n").Trim()) {
    throw "Versao inesperada de lab: $installed. Esperada: $expected"
}
Write-Host "Versao instalada: $installed"
if ($CheckOnly) {
    return
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ([string]::IsNullOrEmpty($userPath)) {
    $userPath = ""
}

$parts = $userPath -split ";" | Where-Object { $_ -ne "" }
if ($parts -contains $scripts) {
    Write-Host "PATH do usuario ja contem $scripts"
} else {
    $updated = if ($userPath) { "$userPath;$scripts" } else { $scripts }
    [Environment]::SetEnvironmentVariable("Path", $updated, "User")
    Write-Host "Adicionado $scripts ao PATH do usuario."
}

Write-Host "Abra um terminal novo em qualquer pasta e rode: lab"
