"""
Processus enfant : affiche UNE page web dans une fenêtre sans bordure, pilotée par des commandes JSON (une par ligne) sur stdin.

Isolation voulue : ce programme n'importe aucun module de l'appli, ne reçoit aucun chemin de ses fichiers, n'expose
aucun pont JavaScript -> Python, refuse toute navigation hors des domaines autorisés et ne peut rien renvoyer au
processus parent. Les commandes acceptées : move, show, hide, navigate (soumise à la liste blanche), quit.

Dépendance : pywebview (pip install pywebview). Sous Windows il utilise WebView2 (déjà présent sur Windows 10/11).
Codes de sortie : 3 = pywebview absent, 4 = adresse refusée, 5 = échec du moteur web.
"""
import argparse
import json
import os
import sys
import threading
from urllib.parse import urlparse


def host_allowed(url, allowed):
    """Vrai si le domaine de l'adresse (ou l'un de ses parents) figure dans la liste blanche. Seuls http/https passent."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == a or host.endswith("." + a) for a in (x.strip().lower() for x in allowed) if a)


def detach_window(title):
    """Masque la fenêtre et la détache de la fenêtre de l'appli (vue 3D incrustée) avant sa destruction.

    Sinon, si l'appli bouge ou se redimensionne pendant la fermeture, Windows prévient encore une fenêtre dont le
    moteur WebView2 est déjà détruit, et .NET affiche « CoreWebView2Controller … disposed »."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32")
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowW.restype = wintypes.HWND
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        u.SetParent.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        hwnd = u.FindWindowW(None, title)
        pid = wintypes.DWORD(0)
        if not hwnd or (u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) and pid.value != os.getpid()):
            return False                            # jamais la fenêtre d'un autre programme au même titre
        u.ShowWindow(hwnd, 0)                       # SW_HIDE
        u.SetParent(hwnd, None)                     # plus de fenêtre parente : plus de messages de déplacement
        return True
    except Exception:
        return False


def quiet_winforms_errors(window):
    """Erreur .NET du fil d'affichage (en pratique : pendant la fermeture) : une ligne sur stderr, pas de boîte.

    Sans gestionnaire, WinForms ouvre « Une exception non gérée s'est produite dans votre application ».
    Le gestionnaire WinForms vaut pour un seul fil : il est posé sur le fil d'affichage de pywebview, via la fenêtre.
    Lancé par webview.start (fil à part) : attend que la fenêtre existe, 20 s au plus."""
    if sys.platform != "win32":
        return False
    try:
        import time

        from System import Action
        from System.Threading import ThreadExceptionEventHandler
        from System.Windows.Forms import Application

        def handler(_sender, event):
            try:
                print(f"Moteur web (ignoré) : {event.Exception.Message}", file=sys.stderr)
            except Exception:
                pass

        def attach():
            Application.ThreadException += ThreadExceptionEventHandler(handler)

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            form = getattr(window, "native", None)
            if form is not None and form.IsHandleCreated:
                form.Invoke(Action(attach))
                return True
            time.sleep(0.1)
    except Exception:
        pass
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--allowed", default="")
    parser.add_argument("--storage", default="")
    parser.add_argument("--title", default="Widget web")
    parser.add_argument("--rect", default="100,100,480,360")
    parser.add_argument("--framed", action="store_true", help="fenêtre normale (bordure, redimensionnable)")
    parser.add_argument("--embedded", action="store_true",
                        help="vue 3D : fenêtre cachée au départ, que l'appli rattache à la sienne (fenêtre enfant)")
    args = parser.parse_args()
    allowed = [h for h in args.allowed.split(",") if h.strip()]

    if not host_allowed(args.url, allowed):
        print("Adresse refusée (hors liste blanche)", file=sys.stderr)
        sys.exit(4)
    try:
        import webview
    except ImportError:
        print("pywebview manquant : pip install pywebview", file=sys.stderr)
        sys.exit(3)

    x, y, w, h = [int(v) for v in args.rect.split(",")]
    try:
        webview.settings.update({"ALLOW_DOWNLOADS": False, "OPEN_EXTERNAL_LINKS_IN_BROWSER": True,
                                 "ALLOW_FILE_URLS": False, "OPEN_DEVTOOLS_IN_DEBUG": False})
    except Exception:
        pass
    # focus=True est indispensable : avec focus=False, pywebview rend la fenêtre « non activable »
    # (WS_EX_NOACTIVATE) et aucune frappe au clavier ne lui parvient jamais (identifiants, recherche...).
    options = dict(x=x, y=y, width=w, height=h, frameless=True, on_top=True, easy_drag=False, resizable=False,
                   text_select=True, focus=True)
    if args.framed:   # vue 3D : fenêtre ordinaire, déplaçable et redimensionnable, pas au premier plan
        options.update(frameless=False, on_top=False, resizable=True, text_select=False)
    if args.embedded:
        options.update(frameless=True, on_top=False, resizable=False, text_select=False, hidden=True)
    try:
        window = webview.create_window(args.title, args.url, **options)
    except TypeError:                       # versions plus anciennes : sans certains paramètres
        for key in ("focus", "text_select", "easy_drag", "hidden"):
            options.pop(key, None)
        window = webview.create_window(args.title, args.url, **options)

    state = {"good": args.url}

    def on_loaded():
        """Si la page affichée sort de la liste blanche (redirection, lien), on revient à la dernière page autorisée."""
        try:
            current = window.get_current_url()
            if current and not host_allowed(current, allowed):
                window.load_url(state["good"])
            elif current:
                state["good"] = current
        except Exception:
            pass

    try:
        window.events.loaded += on_loaded
    except Exception:
        pass

    def reader():
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
                action = cmd.get("cmd")
                if action == "move":
                    window.resize(int(cmd["w"]), int(cmd["h"]))
                    window.move(int(cmd["x"]), int(cmd["y"]))
                elif action == "show":
                    window.show()
                elif action == "hide":
                    window.hide()
                elif action == "navigate" and host_allowed(str(cmd.get("url", "")), allowed):
                    state["good"] = cmd["url"]
                    window.load_url(cmd["url"])
                elif action == "quit":
                    break
            except Exception:
                continue
        detach_window(args.title)       # d'abord masquer et détacher, puis détruire
        try:
            window.destroy()            # parent terminé ou ordre de fermeture
        except Exception:
            pass

    threading.Thread(target=reader, daemon=True).start()
    try:
        kwargs = {"private_mode": False}
        if args.storage:
            kwargs["storage_path"] = args.storage
        webview.start(quiet_winforms_errors, (window,), **kwargs)
    except Exception as e:
        print(f"Moteur web : {e}", file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":
    main()
