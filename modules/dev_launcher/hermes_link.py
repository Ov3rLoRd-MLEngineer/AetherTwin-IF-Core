"""Lien avec Hermes Agent : pont MCP déclaré chez Hermes, questions posées à Hermes.

Déclaré une fois chez Hermes (`hermes mcp add`, son `config.yaml` sauvegardé avant en `.bak` horodaté), le pont
sert quel que soit le moyen de parler à Hermes : application, `hermes.exe`, WoW Assistant… Rien n'est modifié chez
Hermes sans un clic sur « Brancher sur Hermes ».
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from modules.dev_launcher.launch import BRIDGE

MCP_NAME = "aethertwin_dev"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    local = Path(os.environ.get("LOCALAPPDATA") or "") / "hermes"
    if os.environ.get("LOCALAPPDATA") and local.is_dir():
        return local
    return Path.home() / ".hermes"


def registered(config_text: str, name: str = MCP_NAME) -> bool:
    """Le serveur figure-t-il dans la section `mcp_servers` de config.yaml ? (lecture texte, sans YAML)."""
    inside = False
    for line in config_text.splitlines():
        if re.match(r"^mcp_servers\s*:", line):
            inside = True
            continue
        if inside and line and not line[0].isspace() and not line.lstrip().startswith("#"):
            inside = False
        if inside and re.match(rf"^\s+{re.escape(name)}\s*:", line):
            return True
    return False


def state(exe: str) -> dict[str, Any]:
    config = hermes_home() / "config.yaml"
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return {"installe": bool(exe), "pont": registered(text), "config": config.is_file()}


def backup(path: Path) -> str:
    if path.is_file():
        dest = path.with_name(f"{path.name}.aethertwin-{time.strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(path, dest)
        return str(dest)
    return ""


def register(exe: str, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Déclare le pont chez Hermes avec sa propre commande, config.yaml sauvegardé avant."""
    if not exe:
        raise ValueError("Hermes Agent introuvable sur ce PC")
    config = hermes_home() / "config.yaml"
    if registered(config.read_text(encoding="utf-8", errors="replace") if config.is_file() else ""):
        return {"pont": True, "deja": True, "sauvegarde": ""}
    saved = backup(config)
    python = sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-5] + ".exe"
    result = runner([exe, "mcp", "add", MCP_NAME, "--command", python, "--args", "-I", str(BRIDGE), "hermes"],
                    input="y\n", capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=300, creationflags=NO_WINDOW)
    ok = registered(config.read_text(encoding="utf-8", errors="replace") if config.is_file() else "")
    if not ok:
        tail = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()[-3:]
        raise ValueError("échec de « hermes mcp add » : " + " / ".join(tail))
    return {"pont": True, "deja": False, "sauvegarde": saved}
