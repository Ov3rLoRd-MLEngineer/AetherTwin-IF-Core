"""Chaque attribut WoWConfig.X utilisé par l'appli existe bien dans config.py.

Régression du 23/11/2026 : main.py appelait WoWConfig.BASE_DIR (variable du module, pas de la classe) ;
aucun test n'exécutant main(), l'appli plantait au démarrage.
"""

import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "modules" / "gaming_hud" / "app"


def test_wowconfig_attributes_exist():
    sys.path.insert(0, str(APP))
    try:
        from config import WoWConfig
    finally:
        sys.path.remove(str(APP))
    missing = []
    for path in APP.glob("*.py"):
        for name in set(re.findall(r"WoWConfig\.([A-Za-z_]+)", path.read_text(encoding="utf-8"))):
            if not hasattr(WoWConfig, name):
                missing.append(f"{path.name}: {name}")
    assert not missing, missing
