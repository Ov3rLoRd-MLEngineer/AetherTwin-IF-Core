"""Configuration locale du Hub : `config/local.yaml` (ignoré par Git), jamais de secret dans le dépôt.

Ordre de recherche du fichier : variable d'environnement `AETHERTWIN_CONFIG`, puis `config/local.yaml`.
Un fichier absent ou illisible donne une configuration vide : le Hub démarre avec ses valeurs par défaut.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_CONFIG = "AETHERTWIN_CONFIG"


def config_path() -> Path:
    return Path(os.environ[ENV_CONFIG]) if os.environ.get(ENV_CONFIG) else REPO_ROOT / "config" / "local.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Configuration complète ; `{}` si le fichier est absent, illisible ou n'est pas un dictionnaire."""
    path = path or config_path()
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return {}
    except Exception:  # noqa: BLE001 — YAML mal formé : on démarre avec les valeurs par défaut
        return {}
    return data if isinstance(data, dict) else {}


def section(name: str, path: Path | None = None) -> dict[str, Any]:
    """Une section de la configuration (ex. « ollama », « gaming_hud ») ; `{}` si elle n'existe pas."""
    value = load_config(path).get(name)
    return dict(value) if isinstance(value, dict) else {}
