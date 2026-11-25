"""Serveur MCP (stdio) pour piloter OBS Studio en local : scènes, captures, vidéo, enregistrement. Pas de diffusion.

    .venv\\Scripts\\python.exe -m modules.gaming_hud.obs_mcp
    .venv\\Scripts\\python.exe -I modules\\gaming_hud\\obs_mcp.py      (forme à déclarer chez un client MCP)

Prérequis : dans OBS, Outils > Paramètres du serveur WebSocket > « Activer le serveur WebSocket ».
Le mot de passe vient de OBS_WEBSOCKET_PASSWORD, sinon des réglages locaux d'OBS ; il n'est jamais écrit ici.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # lancé comme script : la racine du dépôt remplace le dossier du script
    sys.path[0] = str(Path(__file__).resolve().parents[2])

from core.mcp_stdio import ToolServer  # noqa: E402
from modules.gaming_hud.obs_control import TOOL_SPECS, call_tool  # noqa: E402

SERVER = ToolServer(
    {"name": "aethertwin-obs", "version": "0.1.0"},
    "Pilote OBS Studio sur cette machine (boucle locale) : préparer des scènes de capture (fenêtres, écran, logo), "
    "régler la vidéo, faire des captures d'image et enregistrer. Aucune diffusion n'est possible avec ces outils.",
    TOOL_SPECS, call_tool)

if __name__ == "__main__":
    SERVER.main()
