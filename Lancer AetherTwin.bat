@echo off
rem Lanceur AetherTwin (I&F Core) : double-clic, ou raccourci « AetherTwin » du bureau.
rem Il démarre le Hub et ouvre le tableau de bord dans le navigateur ; tout se pilote de là
rem (modules, WoW Assistant, overlay OBS, Professeur, connaissances, scantrad).
rem Si le Hub tourne déjà, il ouvre seulement le tableau de bord.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title AetherTwin (I^&F Core) - Hub

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

echo Hub AetherTwin : tableau de bord sur http://127.0.0.1:5750/
echo Garde cette fenetre ouverte. Pour arreter : bouton "Arreter le Hub" du tableau de bord, ou Ctrl+C ici.
echo.
"%PY%" -m core.daemon --open
echo.
echo Hub arrete. Tu peux fermer cette fenetre.
pause
