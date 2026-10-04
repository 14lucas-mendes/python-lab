$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$scripts = Join-Path $root ".venv\Scripts"
$lab = Join-Path $scripts "lab.exe"

if (-not (Test-Path $lab)) {
    throw "lab.exe nao encontrado em $scripts. Instale o projeto no venv com: .venv\Scripts\python.exe -m pip install -e `".[dev]`""
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
Write-Host "Versao instalada:"
& $lab --version
