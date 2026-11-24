"""Serveur MCP (stdio) de l'explorateur de données, pour Hermes Agent ou tout client MCP. Aucune écoute réseau.

    .venv\\Scripts\\python.exe -m modules.data_lab.mcp_server
    .venv\\Scripts\\python.exe -I modules\\data_lab\\mcp_server.py      (forme déclarée chez Hermes)

Les classeurs sont ceux de l'explorateur : `data/data_lab/workbooks` à la racine du dépôt.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # lancé comme script : la racine du dépôt remplace le dossier du script
    sys.path[0] = str(Path(__file__).resolve().parents[2])

from core.mcp_stdio import ToolServer  # noqa: E402
from modules.data_lab.agent import TOOL_SPECS, call_tool  # noqa: E402
from modules.data_lab.workbooks import DATA_DIR, REPO_ROOT, Store  # noqa: E402


def make_server(store: Store) -> ToolServer:
    def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return call_tool(store, name, args)

    return ToolServer(
        {"name": "aethertwin-donnees", "version": "0.1.0"},
        "Explorateur de données local d'AetherTwin : tableur à formules (noms français ou anglais, arguments "
        "séparés par « ; »), ajustements, balayages, Monte-Carlo, valeur cible. Lis un classeur avant de l'écrire ; "
        "utilise ces outils plutôt que de calculer de tête.",
        TOOL_SPECS, call)


if __name__ == "__main__":
    make_server(Store(REPO_ROOT / DATA_DIR)).main()
