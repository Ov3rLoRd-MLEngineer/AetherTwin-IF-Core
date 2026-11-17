"""
Gestion des widgets web (Open WebUI, lecteur vidéo) : chacun tourne dans un processus séparé (webhost.py) dont la fenêtre
suit la position du widget de l'overlay.

Ce que cette isolation garantit : le contenu web ne s'exécute jamais dans l'appli ; le processus ne reçoit que des
ordres de position et une adresse autorisée ; son environnement est réduit ; son dossier de travail est temporaire ;
il n'a aucun canal pour écrire dans l'appli. Ce n'est pas un bac à sable du système d'exploitation : le processus
garde les droits de votre session Windows.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

from webhost import host_allowed

HOST_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webhost.py")
KEEP_ENV = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
            "COMSPEC", "PATHEXT", "HOMEDRIVE", "HOMEPATH", "LANG", "DISPLAY", "XAUTHORITY", "HOME")
_PY = f"{sys.version_info.major}.{sys.version_info.minor}"     # le « pip » nu peut viser un AUTRE Python que celui de l'appli
EXIT_MESSAGES = {3: f"pywebview absent de ce Python ({_PY}) : py -{_PY} -m pip install pywebview",
                 4: "Adresse refusée (hors liste blanche)", 5: "Le moteur web n'a pas pu démarrer"}


class WebHost:
    def __init__(self, settings, command=None):
        self.settings = settings
        self.command = command or [sys.executable, "-I", HOST_SCRIPT]
        self.procs = {}
        self.errors = {}
        self._last = {}
        self._workdir = tempfile.mkdtemp(prefix="wowassistant_web_")
        self.storage_root = os.path.join(os.path.dirname(HOST_SCRIPT), "cache", "web")

    # ------------------------------------------------------------------ réglages
    def allowed_hosts(self):
        hosts = [h.strip().lower() for h in str(self.settings.get("web.allowed_hosts", "")).split(",") if h.strip()]
        for key in ("web.openwebui_url", "web.video_url"):          # les adresses configurées sont de confiance
            host = urlparse(str(self.settings.get(key, ""))).hostname
            if host:
                hosts.append(host.lower())
        return sorted(set(hosts))

    def is_allowed(self, url):
        return host_allowed(url, self.allowed_hosts())

    def scale(self):
        try:
            return max(0.5, float(self.settings.get("web.scale", 1.0)))
        except (TypeError, ValueError):
            return 1.0

    # ------------------------------------------------------------------ état
    def is_running(self, wid):
        proc = self.procs.get(wid)
        return proc is not None and proc.poll() is None

    def retry(self, wid):
        self.errors.pop(wid, None)

    def _reap(self):
        for wid, proc in list(self.procs.items()):
            code = proc.poll()
            if code is not None:
                self.procs.pop(wid, None)
                self._last.pop(wid, None)
                if code != 0 and wid not in self.errors:
                    self.errors[wid] = EXIT_MESSAGES.get(code, f"Le widget web s'est arrêté (code {code})")

    # ------------------------------------------------------------------ processus
    def start(self, wid, url, rect):
        if not self.is_allowed(url):
            self.errors[wid] = "Adresse hors liste blanche : ajoutez son domaine dans Paramètres > Web"
            return False
        env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        storage = os.path.join(self.storage_root, wid)
        os.makedirs(storage, exist_ok=True)
        args = self.command + ["--url", url, "--allowed", ",".join(self.allowed_hosts()), "--storage", storage,
                               "--title", f"WoW Assistant - {wid}", "--rect", ",".join(str(int(v)) for v in rect)]
        try:
            self.procs[wid] = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               cwd=self._workdir, env=env, close_fds=True,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.errors[wid] = f"Lancement impossible : {e}"
            return False
        self._last[wid] = (tuple(int(v) for v in rect), True)
        return True

    def _send(self, wid, message):
        proc = self.procs.get(wid)
        if not proc or proc.poll() is not None:
            return False
        try:
            proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def stop(self, wid):
        proc = self.procs.pop(wid, None)
        self._last.pop(wid, None)
        if proc and proc.poll() is None:
            self._send_proc(proc, {"cmd": "quit"})
            try:
                proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                proc.kill()

    @staticmethod
    def _send_proc(proc, message):
        try:
            proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            proc.stdin.flush()
        except Exception:
            pass

    def stop_all(self):
        for wid in list(self.procs):
            self.stop(wid)

    def navigate(self, wid, url):
        if not self.is_allowed(url):
            self.errors[wid] = "Adresse hors liste blanche"
            return False
        return self._send(wid, {"cmd": "navigate", "url": url})

    # ------------------------------------------------------------------ synchronisation avec l'overlay
    def sync(self, wants, origin, visible):
        """wants : {wid: {"rect": (x, y, w, h) dans la fenêtre overlay ou None, "enabled": bool, "url": str}}.
        origin : position de la fenêtre overlay à l'écran ; visible : False si l'overlay est masqué / quitté."""
        self._reap()
        k = self.scale()
        for wid, want in wants.items():
            if not want["enabled"]:
                if wid in self.procs:
                    self.stop(wid)
                self.errors.pop(wid, None)
                continue
            rect = want["rect"]
            if rect is None or not visible:                       # réduit, masqué par le mode Focus, ou overlay caché
                if self.is_running(wid) and self._last.get(wid, (None, True))[1]:
                    self._send(wid, {"cmd": "hide"})
                    self._last[wid] = (self._last[wid][0], False)
                continue
            screen = (int((origin[0] + rect[0]) * k), int((origin[1] + rect[1]) * k), int(rect[2] * k), int(rect[3] * k))
            if wid in self.errors:
                continue                                          # en erreur : on attend « Réessayer »
            if not self.is_running(wid):
                self.start(wid, want["url"], screen)
                continue
            last_rect, shown = self._last.get(wid, (None, True))
            if not shown:
                self._send(wid, {"cmd": "show"})
            if screen != last_rect or not shown:
                self._send(wid, {"cmd": "move", "x": screen[0], "y": screen[1], "w": screen[2], "h": screen[3]})
            self._last[wid] = (screen, True)
