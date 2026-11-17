@echo off
title WoW Assistant
rem Lance WoW Assistant avec Python 3.11, depuis le dossier de ce fichier.
cd /d "%~dp0"

py -3.11 --version >nul 2>nul
if errorlevel 1 (
    echo [ERREUR] Python 3.11 est introuvable ^(commande : py -3.11^).
    pause
    exit /b 1
)

py -3.11 -c "import pygame, PIL" >nul 2>nul
if errorlevel 1 (
    echo Installation des dependances pour Python 3.11...
    py -3.11 -m pip install -r requirements.txt
)

py -3.11 main.py
if errorlevel 1 (
    echo.
    echo WoW Assistant s'est arrete avec une erreur ^(voir ci-dessus^).
    pause
)
