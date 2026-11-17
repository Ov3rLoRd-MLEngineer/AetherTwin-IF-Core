"""gaming_hud — HUD de jeu du Hub (évolution de WoW Assistant).

- `app/`      : l'application Pygame d'origine, inchangée. Ses fichiers s'importent « à plat »
                (`import ui`, `from config import WoWConfig`) ; `ensure_app_path()` ajoute son dossier
                au chemin d'import. Elle ne tourne que dans son propre processus.
- `adapters/` : l'interface `GameAdapter` et ses implémentations (WoW, suivi de journal, capture d'écran).
- `module.py` : le module du Hub (contrat `ModuleBase`).
- `addon/`    : l'addon Lua `HermesAssistant` à copier dans `Interface/AddOns` du jeu.

    python -m modules.gaming_hud        # lance l'application comme avant
"""
from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR / "app"
ADDON_DIR = PACKAGE_DIR / "addon" / "HermesAssistant"


def ensure_app_path() -> Path:
    """Rend importables les modules de l'application d'origine (imports à plat). Idempotent."""
    path = str(APP_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    return APP_DIR


def run_app() -> None:
    """Lance WoW Assistant à l'identique (fenêtre Pygame, overlay, voix, vision)."""
    ensure_app_path()
    import main as app_main  # module d'origine : app/main.py

    app_main.main()
