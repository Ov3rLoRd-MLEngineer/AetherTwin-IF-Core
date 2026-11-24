"""Fenêtre de bureau de la calculatrice : `python -m modules.calc_cas.app` (lancée par le Hub).

La fenêtre est la page `core/web/calc_app.html` servie par le Hub, ouverte dans Edge (ou Chrome) en mode
application : fenêtre sans barre d'adresse, redimensionnable, avec son propre profil (`data/calc_cas/window-profile`)
pour mémoriser sa taille et sa position. Sans navigateur compatible, la page s'ouvre dans le navigateur par défaut.

Le processus attend la fermeture de la fenêtre : le Hub sait ainsi si la calculatrice est ouverte, et peut la
fermer (« Arrêter l'application »).
"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "data" / "calc_cas" / "window-profile"
WINDOW_SIZE = (500, 900)
CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)


def hub_url() -> str:
    """Adresse de la page, d'après le port du démon dans la configuration (5750 par défaut)."""
    try:
        from core import config

        port = int(config.section("daemon").get("port", 5750))
    except Exception:  # noqa: BLE001 — configuration absente ou illisible : port par défaut
        port = 5750
    return f"http://127.0.0.1:{port}/static/calc_app.html"


def find_browser(candidates: tuple[str, ...] = CANDIDATES) -> str | None:
    """Premier navigateur Chromium installé (Edge, puis Chrome), ou `None`."""
    for raw in candidates:
        path = Path(os.path.expandvars(raw))
        if "%" not in str(path) and path.is_file():
            return str(path)
    return None


def browser_args(browser: str, url: str, profile: Path = PROFILE,
                 size: tuple[int, int] = WINDOW_SIZE) -> list[str]:
    """Ligne de commande (liste, jamais de shell) d'une fenêtre d'application isolée."""
    width, height = size
    return [browser, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={width},{height}",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]


def tie_children_to_this_process() -> bool:
    """Windows : place ce processus dans un objet de tâche « tuer à la fermeture ». Le navigateur lancé ensuite
    en hérite ; quand le Hub arrête l'application (fin forcée de ce processus), la fenêtre se ferme aussi.
    `False` hors Windows ou en cas d'échec (la fenêtre reste alors ouverte à l'arrêt)."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    from modules.calc_cas import worker

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = worker.job_limits()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) and \
        kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())
    global _JOB
    _JOB = job  # gardé ouvert jusqu'à la fin du processus
    return bool(ok)


_JOB = None


def main() -> int:
    url = hub_url()
    browser = find_browser()
    if browser is None:
        print(f"Aucun navigateur Edge ou Chrome trouvé : ouverture de {url} dans le navigateur par défaut.")
        webbrowser.open(url)
        return 0
    PROFILE.mkdir(parents=True, exist_ok=True)
    tie_children_to_this_process()
    proc = subprocess.Popen(browser_args(browser, url), stdin=subprocess.DEVNULL)  # noqa: S603 — chemin fixe
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
