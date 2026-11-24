"""Fenêtre du Hub : `python -m core.hub_window [--port 5750]`.

Le tableau de bord s'ouvre dans sa propre fenêtre d'application (Edge ou Chrome en mode « --app », profil
`data/hub/window-profile` qui garde sa taille et sa position), avec l'icône d'AetherTwin dans la barre de titre et
la barre des tâches. Sans Edge ni Chrome, il s'ouvre dans le navigateur par défaut.

Le démon lance ce module avec `--open` (raccourci « Lancer AetherTwin ») ; il attend que le Hub réponde avant
d'ouvrir la fenêtre.
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import webbrowser

from core.app_window import REPO_ROOT, brand_window, open_app

PROFILE = REPO_ROOT / "data" / "hub" / "window-profile"
WINDOW_SIZE = (1480, 960)
APP_ID = "AetherTwin.Hub"
TITLE = "AetherTwin — Hub"
LAUNCHER = REPO_ROOT / "Lancer AetherTwin.bat"


def wait_for_hub(port: int, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def open_window(port: int) -> bool:
    """Ouvre la fenêtre du Hub ; `False` si elle a dû s'ouvrir dans le navigateur par défaut."""
    url = f"http://127.0.0.1:{port}/"
    command = f'"{LAUNCHER}"' if LAUNCHER.is_file() else f'"{sys.executable}" -m core.daemon --open'
    proc = open_app(url, PROFILE, WINDOW_SIZE, APP_ID, "AetherTwin", command)
    if proc is None:
        webbrowser.open(url)
        return False
    # on attend ici que l'icône soit posée (le fil d'`open_app` ne survivrait pas à la fin du processus)
    brand_window(proc.pid, APP_ID, "AetherTwin", command)
    return True


def spawn(port: int) -> None:
    """Lance la fenêtre dans un processus à part (appelé par le démon : il ne l'attend pas)."""
    subprocess.Popen([sys.executable, "-m", "core.hub_window", "--port", str(port)],  # noqa: S603 — chemin fixe
                     stdin=subprocess.DEVNULL, cwd=str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fenêtre du Hub AetherTwin.")
    parser.add_argument("--port", type=int, default=5750)
    args = parser.parse_args(argv)
    if not wait_for_hub(args.port):
        print(f"Le Hub ne répond pas sur le port {args.port}.")
        return 1
    open_window(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
