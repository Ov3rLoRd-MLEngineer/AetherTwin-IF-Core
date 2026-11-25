@echo off
rem Installation d'AetherTwin. Passe par ce fichier si Windows refuse d'executer setup.ps1 :
rem l'autorisation ne vaut que pour ce lancement (-ExecutionPolicy Bypass), le reglage de Windows ne change pas.
rem Options : -Gpu -Weights -Shortcut -Voice (ex. : "Installer AetherTwin.bat" -Voice)
rem A la fin, une fenetre propose de creer les raccourcis du bureau (AetherTwin et WoW Assistant).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" -Ask %*
echo.
pause
