@echo off
rem Lanceur AetherTwin (I&F Core). Double-clic, ou raccourci sur le bureau vers ce fichier.
rem Il se place toujours dans le dossier du projet et utilise le Python du .venv.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title AetherTwin (I^&F Core)

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Environnement Python introuvable : %PY%
  echo Installe-le une fois avec :  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  pause
  exit /b 1
)
if not exist "config\local.yaml" (
  copy /y "config\local.example.yaml" "config\local.yaml" >nul
  echo config\local.yaml cree a partir de l'exemple.
)

if not "%~1"=="" (
  set "CHOIX=%~1"
  goto :choix
)

:menu
echo.
echo  ==== AetherTwin (I^&F Core) ====
echo   1. Hub + tableau de bord dans le navigateur
echo   2. Hub + gaming_hud (overlay OBS) + genesis_lab (Professeur)
echo   3. WoW Assistant seul (sans le Hub)
echo   4. Scantrad : traduire une image (le Hub doit tourner)
echo   5. Etat des GPU (mesure ponctuelle)
echo   6. Quitter
echo.
set "CHOIX="
set /p "CHOIX=Ton choix [1] : "
if "%CHOIX%"=="" set "CHOIX=1"

:choix
if "%CHOIX%"=="1" (
  "%PY%" -m core.daemon --open
  goto :fin
)
if "%CHOIX%"=="2" (
  "%PY%" -m core.daemon --open --activate gaming_hud --activate genesis_lab
  goto :fin
)
if "%CHOIX%"=="3" (
  "%PY%" -m modules.gaming_hud
  goto :fin
)
if "%CHOIX%"=="4" goto :scantrad
if "%CHOIX%"=="5" (
  "%PY%" -m core.hardware.gpu_monitor
  pause
  goto :menu
)
if "%CHOIX%"=="6" exit /b 0
echo Choix inconnu : %CHOIX%
goto :menu

:scantrad
echo.
echo Glisse l'image dans cette fenetre (ou tape son chemin), puis Entree.
echo Vide = page de test du projet.
set "IMAGE="
set /p "IMAGE=Image : "
if "%IMAGE%"=="" set "IMAGE=tests\data\scantrad\page_test.png"
set "IMAGE=%IMAGE:"=%"
set "SERIE="
set /p "SERIE=Nom de la serie (glossaire, vide = aucun) : "
"%PY%" -m modules.scantrad "%IMAGE%" --series "%SERIE%"
echo.
echo L'image traduite est a cote de l'original, avec le suffixe _fr.
pause
goto :menu

:fin
echo.
echo Termine. Tu peux fermer cette fenetre.
pause
