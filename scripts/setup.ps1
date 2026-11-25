# Installation reproductible d'AetherTwin (I&F Core) sous Windows.
#   .\scripts\setup.ps1              # venv Python 3.11 + dépendances + config + vérifications
#   .\scripts\setup.ps1 -Gpu         # + PyTorch CUDA et segment-anything (mangastudio), environ 3 Go
#   .\scripts\setup.ps1 -Weights     # + poids HandSegNet / FootSegNet (2 × 375 Mo) et LaMa (198 Mo), Hugging Face
#   .\scripts\setup.ps1 -Shortcut    # + raccourcis « AetherTwin » et « WoW Assistant » sur le bureau
#   .\scripts\setup.ps1 -Ask         # à la fin, une fenêtre propose de créer ces raccourcis (utilisé par
#                                    #   « Installer AetherTwin.bat »)
#   -Desktop <dossier>               # raccourcis dans ce dossier au lieu du bureau (essais)
#   .\scripts\setup.ps1 -Voice       # + reconnaissance vocale locale (faster-whisper) pour l'onglet Traduction ;
#                                    #   le modèle « small » (~480 Mo, Hugging Face) se télécharge au premier message
# Si Windows refuse d'exécuter le script (« l'exécution de scripts est désactivée »), passe par
# `Installer AetherTwin.bat` à la racine : il autorise ce script pour ce lancement seulement, sans changer le
# réglage de Windows.
# Le script ne touche à rien en dehors du dossier du projet, sauf les raccourcis du bureau (-Shortcut, ou accord donné dans la fenêtre de -Ask).
param([switch]$Gpu, [switch]$Weights, [switch]$Shortcut, [switch]$Voice, [switch]$Ask, [string]$Desktop = "")
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
if ($LASTEXITCODE -ne 0) { throw "Installation des dépendances impossible." }

if ($Gpu) {
    Write-Host "Dépendances GPU (PyTorch CUDA 12.8, segment-anything) : quelques minutes..."
    & $py -m pip install --quiet -r requirements-gpu.txt
    if ($LASTEXITCODE -ne 0) { throw "Installation des dépendances GPU impossible (git est-il installé ?)." }
}

if ($Voice) {
    Write-Host "Reconnaissance vocale locale (faster-whisper)..."
    & $py -m pip install --quiet -r requirements-voice.txt
    if ($LASTEXITCODE -ne 0) { throw "Installation de faster-whisper impossible." }
}

if ($Weights) {
    $dir = Join-Path $root "models\mangastudio"
    New-Item -ItemType Directory -Force $dir | Out-Null
    foreach ($name in "handsegnet", "footsegnet") {
        $file = Join-Path $dir "${name}_vit_b_best.safetensors"
        if (Test-Path $file) { Write-Host "$name : déjà présent"; continue }
        Write-Host "Téléchargement de $name (375 Mo)..."
        curl.exe -L --fail -s -o $file "https://huggingface.co/Ov3rLoRd-MLEngineer/$name-anime-sdxl/resolve/main/${name}_vit_b_best.safetensors"
        if ($LASTEXITCODE -ne 0) { Remove-Item -Force -ErrorAction SilentlyContinue $file; throw "Téléchargement de $name impossible." }
    }
    # LaMa (Apache 2.0, version ONNX de Carve) : effacement par reconstruction de Scantrad
    $lama = Join-Path $root "models\scantrad\lama_fp32.onnx"
    New-Item -ItemType Directory -Force (Split-Path $lama) | Out-Null
    if (Test-Path $lama) { Write-Host "LaMa : déjà présent" } else {
        Write-Host "Téléchargement de LaMa (198 Mo)..."
        curl.exe -L --fail -s -o $lama "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx"
        if ($LASTEXITCODE -ne 0) { Remove-Item -Force -ErrorAction SilentlyContinue $lama; throw "Téléchargement de LaMa impossible." }
    }
}

if (-not (Test-Path "config\local.yaml")) {
    Copy-Item "config\local.example.yaml" "config\local.yaml"
    Write-Host "config\local.yaml créé depuis l'exemple (ignoré par Git)."
}

if ($Ask -and -not $Shortcut) {
    Add-Type -AssemblyName System.Windows.Forms
    $answer = [System.Windows.Forms.MessageBox]::Show(
        "Créer les raccourcis sur le bureau ?`n`n  • AetherTwin (le Hub, avec son logo)`n  • WoW Assistant`n`nTu pourras les supprimer quand tu veux, ils ne changent rien d'autre.",
        "Installation d'AetherTwin", "YesNo", "Question")
    $Shortcut = ($answer -eq "Yes")
}

if ($Shortcut) {
    $desktop = if ($Desktop) { $Desktop } else { [Environment]::GetFolderPath("Desktop") }
    $icon = (Join-Path $root "core\web\logo.ico") + ",0"
    $shell = New-Object -ComObject WScript.Shell
    foreach ($s in @(
            @("AetherTwin", (Join-Path $root "Lancer AetherTwin.bat"), $root, "AetherTwin (I&F Core) - Hub local"),
            @("WoW Assistant", (Join-Path $root "modules\gaming_hud\app\Lancer WoW Assistant.bat"),
              (Join-Path $root "modules\gaming_hud\app"), "WoW Assistant (AetherTwin)"))) {
        $link = $shell.CreateShortcut((Join-Path $desktop "$($s[0]).lnk"))
        $link.TargetPath = $s[1]
        $link.WorkingDirectory = $s[2]
        $link.Description = $s[3]
        $link.IconLocation = $icon
        $link.Save()
        Write-Host "Raccourci « $($s[0]) » créé sur le bureau."
    }
}

# Vérifications (informatives : rien n'est installé ni modifié ici)
Write-Host ""
Write-Host "--- Vérifications ---"
& $py --version
& $py -m core.hardware.gpu_monitor | Select-String '"backend"|"gpu_count"|"vram_total_mib"'
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Ollama introuvable : l'assistant, le Professeur, scantrad et le jeu tourneront sans modèle (modes dégradés)."
} else {
    $models = (& ollama list 2>$null) -join "`n"
    foreach ($m in @(@("qwen3-27b", "assistant et traductions (modèle par défaut)"),
                     @("qwen2.5vl", "lecture des bulles (scantrad)"),
                     @("nomic-embed-text", "recherche par vecteurs (connaissances)"))) {
        if ($models -match [regex]::Escape($m[0])) { Write-Host "Ollama : $($m[0]) présent — $($m[1])" }
        else { Write-Host "Ollama : $($m[0]) absent — $($m[1]). Pour l'ajouter : ollama pull $($m[0])" }
    }
}
$gpuDeps = & $py -c "import importlib.util as u; print(all(u.find_spec(m) for m in ('torch', 'segment_anything')))"
Write-Host "mangastudio : $(if ($gpuDeps -eq 'True') { 'PyTorch présent' } else { 'simulation (relance avec -Gpu pour les vrais modèles)' })"
Write-Host ""
Write-Host "Prêt. Lancer : double-clic sur « Lancer AetherTwin.bat » (ou le raccourci du bureau)."
Write-Host "Tests : .\.venv\Scripts\python.exe -m pytest"
