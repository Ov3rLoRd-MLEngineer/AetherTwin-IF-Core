# Installation reproductible : venv Python 3.11 dans le dépôt + dépendances épinglées.
#   .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$os = (Get-CimInstance Win32_OperatingSystem).Caption
Write-Host "Système détecté : $os"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Création du venv (.venv) avec Python 3.11..."
    py -3.11 -m venv .venv
    if (-not $?) { throw "Python 3.11 introuvable. Installe-le, puis relance (py -0p liste les versions)." }
}

$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements-dev.txt
if (-not $?) { throw "Installation des dépendances impossible." }

if (-not (Test-Path "config\local.yaml")) {
    Copy-Item "config\local.example.yaml" "config\local.yaml"
    Write-Host "config\local.yaml créé depuis l'exemple (ignoré par Git)."
}

& $py --version
Write-Host "Prêt. Tests : .\.venv\Scripts\python.exe -m pytest"
