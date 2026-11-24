"""Serveur MCP (stdio) du labo de chimie, pour Hermes Agent ou tout client MCP. Aucune écoute réseau.

    .venv\\Scripts\\python.exe -m modules.chem_lab.mcp_server
    .venv\\Scripts\\python.exe -I modules\\chem_lab\\mcp_server.py      (forme déclarée chez Hermes)
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # lancé comme script : la racine du dépôt remplace le dossier du script
    sys.path[0] = str(Path(__file__).resolve().parents[2])

from core.mcp_stdio import ToolServer  # noqa: E402
from modules.chem_lab.agent import TOOL_SPECS, call_tool  # noqa: E402

SERVER = ToolServer(
    {"name": "aethertwin-chimie", "version": "0.1.0"},
    "Labo de chimie local d'AetherTwin : calculs exacts (masses molaires, équilibrage, stœchiométrie, pH, "
    "titrages). Utilise ces outils plutôt que d'estimer un résultat de tête.",
    TOOL_SPECS, call_tool)

if __name__ == "__main__":
    SERVER.main()
