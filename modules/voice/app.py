"""Fenêtre de bureau du studio audio : `python -m modules.voice.app` (lancée par le Hub).

Même principe que le studio pixel : la page `core/web/audio_app.html` servie par le Hub, ouverte dans Edge (ou
Chrome) en mode application, avec son propre profil (`data/voice/window-profile`, où le navigateur retient
l'autorisation du micro). Le processus attend la fermeture de la fenêtre.
"""
from __future__ import annotations

import subprocess
import sys
import webbrowser

from modules.calc_cas.app import browser_args, find_browser, hub_url, tie_children_to_this_process
from modules.voice.service import DATA_DIR

PROFILE = DATA_DIR / "window-profile"
PAGE = "/static/audio_app.html"
WINDOW_SIZE = (1360, 880)


def page_url() -> str:
    return hub_url().rsplit("/static/", 1)[0] + PAGE


def main() -> int:
    url = page_url()
    browser = find_browser()
    if browser is None:
        print(f"Aucun navigateur Edge ou Chrome trouvé : ouverture de {url} dans le navigateur par défaut.")
        webbrowser.open(url)
        return 0
    PROFILE.mkdir(parents=True, exist_ok=True)
    tie_children_to_this_process()
    proc = subprocess.Popen(browser_args(browser, url, PROFILE, WINDOW_SIZE),  # noqa: S603 — chemin fixe
                            stdin=subprocess.DEVNULL)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
