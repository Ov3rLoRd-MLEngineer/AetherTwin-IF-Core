"""
Vue 3D facultative (désactivée par défaut) : la visionneuse 3D de Wowhead (ZamModelViewer), affichée dans une page
locale.

- Un petit serveur écoute sur 127.0.0.1 uniquement (port libre choisi par le système). Il sert la page
  `web3d/viewer.html` et relaie, avec un cache disque, les fichiers de la visionneuse et des modèles depuis
  `wow.zamimg.com/modelviewer/live/` (le navigateur refuse de les charger directement depuis une autre origine), ainsi
  que jQuery (exigé par la visionneuse). Aucun autre hôte, aucun autre chemin.
- L'appli décrit ce qu'il faut montrer (personnage : race, sexe, personnalisation, objets ; ou une créature, une
  monture, une mascotte) ; la page relit cette description et met la vue à jour (essayage d'une pièce, d'un ensemble).
- La page s'affiche DANS la fenêtre de l'appli, sur le cadre de l'aperçu : une fenêtre pywebview (processus
  `webhost.py --embedded`, sans bordure) est rattachée comme fenêtre enfant de la fenêtre pygame (Win32 SetParent),
  puis placée et masquée par l'appli à chaque image. Sans pywebview (ou hors Windows) : bouton « Vue 3D » qui ouvre
  la page dans le navigateur.
- Les modèles appartiennent à Wowhead / Blizzard : usage personnel. Rien n'est extrait des fichiers du jeu.
"""
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ZAM = "https://wow.zamimg.com/"
JQUERY = "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js"
SAFE_PATH = re.compile(r"^modelviewer/live/[A-Za-z0-9_./-]+$")
PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web3d")
TYPES = {".js": "application/javascript", ".json": "application/json", ".html": "text/html; charset=utf-8",
         ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".css": "text/css"}

# Emplacements Battle.net (type de l'apparence) → emplacements de la visionneuse (types d'inventaire du jeu)
SLOTS = {"HEAD": 1, "SHOULDER": 3, "SHIRT": 4, "CHEST": 5, "WAIST": 6, "LEGS": 7, "FEET": 8, "WRIST": 9,
         "HAND": 10, "HANDS": 10, "BACK": 16, "CLOAK": 16, "TABARD": 19, "ROBE": 20, "WEAPONMAINHAND": 21,
         "WEAPONOFFHAND": 22, "WEAPON": 21, "TWOHWEAPON": 21, "RANGED": 26, "RANGEDRIGHT": 26, "SHIELD": 22,
         "HOLDABLE": 23}
HIDDEN_SLOTS = {"NECK", "FINGER_1", "FINGER_2", "TRINKET_1", "TRINKET_2"}
# un emplacement de la visionneuse en remplace d'autres (une robe remplace le torse, etc.)
SAME_PLACE = {5: (5, 20), 20: (5, 20), 21: (21,), 22: (22, 23), 23: (22, 23), 16: (16,)}
MODEL_TYPES = {"npc": 8, "item": 1, "character": 16}


def appearance_display(bnet, item_id):
    """(emplacement de la visionneuse, display id) de l'apparence d'un objet, via Battle.net."""
    item = bnet.get(f"/data/wow/item/{int(item_id)}", "static", max_age=3600 * 24 * 28)
    refs = item.get("appearances") or []
    if not refs:
        return None
    return appearance_by_id(bnet, refs[0]["id"])


def appearance_by_id(bnet, appearance_id):
    data = bnet.get(f"/data/wow/item-appearance/{int(appearance_id)}", "static", max_age=3600 * 24 * 28)
    slot = SLOTS.get((data.get("slot") or {}).get("type", ""), 0)
    display = data.get("item_display_info_id")
    return (slot, int(display)) if slot and display else None


def character_model(bnet, realm, name):
    """Description 3D du personnage tel qu'il apparaît (transmogrification comprise) : Battle.net « appearance »."""
    from bnet import realm_slug
    import urllib.parse
    path = f"/profile/wow/character/{realm_slug(realm)}/{urllib.parse.quote(name.lower())}/appearance"
    data = bnet.get(path, "profile", max_age=3600)
    items = []
    for it in data.get("items") or []:
        if (it.get("slot") or {}).get("type") in HIDDEN_SLOTS:
            continue
        try:
            found = appearance_display(bnet, it["id"])
        except Exception:   # objet inconnu de l'API : on l'omet plutôt que de tout perdre
            found = None
        if found:
            items.append(list(found))
    return {"kind": "character", "race": (data.get("playable_race") or {}).get("id", 1),
            "gender": 1 if (data.get("gender") or {}).get("type") == "FEMALE" else 0,
            "options": [{"optionId": c["option"]["id"], "choiceId": c["choice"]["id"]}
                        for c in data.get("customizations") or [] if c.get("option") and c.get("choice")],
            "items": items}


def display_model(display_id, caption=""):
    """Créature, monture ou mascotte : modèle de créature par son « display id »."""
    return {"kind": "model", "id": int(display_id), "type": MODEL_TYPES["npc"], "caption": caption}


def _first_display(data, what):
    displays = data.get("creature_displays") or []
    if not displays:
        raise ValueError(f"pas de modèle pour cette {what}")
    return int(displays[0]["id"])


def mount_model(bnet, mount_id, caption=""):
    data = bnet.get(f"/data/wow/mount/{int(mount_id)}", "static", max_age=3600 * 24 * 28)
    return display_model(_first_display(data, "monture"), caption)


def creature_model(bnet, creature_id, caption=""):
    data = bnet.get(f"/data/wow/creature/{int(creature_id)}", "static", max_age=3600 * 24 * 28)
    return display_model(_first_display(data, "créature"), caption)


def pet_model(bnet, species_id, creature_id=0, caption=""):
    if not creature_id:
        pet = bnet.get(f"/data/wow/pet/{int(species_id)}", "static", max_age=3600 * 24 * 28)
        creature_id = (pet.get("creature") or {}).get("id")
        if not creature_id:
            raise ValueError("pas de créature pour cette mascotte")
    return creature_model(bnet, creature_id, caption)


def try_on(model, pieces):
    """Modèle de personnage avec des pièces essayées [(emplacement, display)] à la place de celles portées."""
    model = dict(model, items=[list(i) for i in model.get("items", [])])
    for slot, display in pieces:
        replaced = SAME_PLACE.get(slot, (slot,))
        model["items"] = [i for i in model["items"] if i[0] not in replaced] + [[slot, display]]
    return model


class Viewer3D:
    """Serveur local de la vue 3D. `show(description)` change ce que la page affiche."""

    def __init__(self, cache_dir, opener=None):
        self.cache_dir = cache_dir
        self._open = opener or (lambda req, timeout=30: urllib.request.urlopen(req, timeout=timeout))
        self.server = None
        self.port = 0
        self.model = {"kind": "none"}
        self.version = 0
        self.lock = threading.Lock()
        self.proc = None              # processus webhost (fenêtre pywebview incrustée)
        self.child = None             # sa fenêtre Win32, une fois rattachée à la fenêtre de l'appli
        self.title = ""
        self.started_at = 0.0
        self.placed = None            # dernier rectangle (pixels du client de la fenêtre parente)
        self.visible = False
        self.error = ""
        self.browser_opened = False   # repli : page ouverte dans le navigateur par défaut

    # ------------------------------------------------------------------ cycle de vie
    def start(self):
        if self.server:
            return self.port
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):   # pas de journal console à chaque fichier
                pass

            def do_GET(self):
                viewer._handle(self)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.port

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def url(self):
        return f"http://127.0.0.1:{self.start()}/viewer.html"

    # ------------------------------------------------------------------ vue incrustée
    @staticmethod
    def can_embed():
        import importlib.util
        return sys.platform == "win32" and importlib.util.find_spec("webview") is not None

    def embed(self, parent, rect):
        """Place la vue 3D sur `rect` (x, y, w, h en pixels du client de la fenêtre `parent`), ou la masque (None).
        Appelé à chaque image ; ne fait un appel Win32 que si quelque chose change. Vrai si la vue est affichée."""
        if rect is None or not parent:
            self._hide()
            return False
        if self.error:
            return False
        if self.proc is None:
            self._spawn()
            return False
        if self.proc.poll() is not None:
            self.error = "la fenêtre 3D s'est fermée (pywebview / WebView2 ?)"
            self.proc = self.child = None
            return False
        if not self.child:
            hwnd = _win32().FindWindowW(None, self.title)
            if not hwnd:
                if time.monotonic() - self.started_at > 25:
                    self.error = "la fenêtre 3D ne s'est pas ouverte (WebView2 installé ?)"
                return False
            if not _attach(hwnd, parent):
                self.error = "impossible d'incruster la fenêtre 3D"
                return False
            self.child, self.placed, self.visible = hwnd, None, False
            self._command({"cmd": "show"})               # pywebview affiche son contenu (créé masqué)
        rect = tuple(int(v) for v in rect)
        if rect != self.placed or not self.visible:
            _place(self.child, rect)
            self.placed, self.visible = rect, True
        return True

    def _hide(self):
        if self.child and self.visible:
            _win32().ShowWindow(self.child, 0)            # SW_HIDE
            self.visible = False

    def _spawn(self):
        import subprocess
        import tempfile
        self.title = "WoWAssistant-3D-" + secrets.token_hex(6)   # titre unique : sert à retrouver la fenêtre
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webhost.py")
        args = [sys.executable, "-I", script, "--url", self.url(), "--allowed", "127.0.0.1", "--embedded",
                "--title", self.title, "--rect", "0,0,400,400",
                "--storage", os.path.join(self.cache_dir, "webview")]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, cwd=tempfile.gettempdir(), close_fds=True,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.child, self.started_at = None, time.monotonic()

    def _command(self, message):
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass

    # ------------------------------------------------------------------ repli : navigateur
    def window_open(self):
        return self.browser_opened

    def open_window(self):
        """Sans pywebview : la page dans le navigateur par défaut (elle suit la sélection de l'appli)."""
        import webbrowser
        webbrowser.open(self.url())
        self.browser_opened = True

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.stdin.write(b'{"cmd": "quit"}\n')
                self.proc.stdin.flush()
                self.proc.wait(timeout=1.5)
            except Exception:
                self.proc.kill()
        self.proc = self.child = None
        self.visible = False
        self.stop()

    def show(self, model):
        with self.lock:
            if model != self.model:
                self.model = model
                self.version += 1

    # ------------------------------------------------------------------ requêtes
    def _handle(self, req):
        path = req.path.split("?", 1)[0].lstrip("/")
        try:
            if path in ("", "viewer.html"):
                return self._send_file(req, os.path.join(PAGE_DIR, "viewer.html"))
            if path == "model.json":
                with self.lock:
                    body = json.dumps(dict(self.model, version=self.version)).encode("utf-8")
                return self._send(req, 200, body, TYPES[".json"])
            if path == "jquery.js":
                return self._send_cached(req, JQUERY, "jquery-3.7.1.min.js")
            if path.startswith("zam/"):
                sub = path[4:]
                if not SAFE_PATH.match(sub) or ".." in sub:
                    return self._send(req, 403, b"refuse", "text/plain")
                return self._send_cached(req, ZAM + sub, sub)
            return self._send(req, 404, b"introuvable", "text/plain")
        except (BrokenPipeError, ConnectionResetError):
            return None

    def _send(self, req, code, body, ctype):
        req.send_response(code)
        req.send_header("Content-Type", ctype)
        req.send_header("Content-Length", str(len(body)))
        req.send_header("Cache-Control", "no-store" if ctype == TYPES[".json"] else "max-age=86400")
        req.end_headers()
        req.wfile.write(body)

    def _send_file(self, req, path):
        with open(path, "rb") as f:
            body = f.read()
        return self._send(req, 200, body, TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))

    def _send_cached(self, req, url, key):
        local = os.path.join(self.cache_dir, *key.split("/"))
        ctype = TYPES.get(os.path.splitext(key)[1], "application/octet-stream")
        if os.path.isfile(local):
            with open(local, "rb") as f:
                return self._send(req, 200, f.read(), ctype)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "WoWAssistant/1.9"})
            with self._open(request, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            return self._send(req, e.code, b"", "text/plain")
        except (urllib.error.URLError, OSError):
            return self._send(req, 502, b"injoignable", "text/plain")
        os.makedirs(os.path.dirname(local), exist_ok=True)
        tmp = local + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, local)
        return self._send(req, 200, body, ctype)


# ---------------------------------------------------------------------------- Win32 (fenêtre enfant)
_USER32 = None
WS_CHILD, WS_POPUP, WS_CAPTION, WS_THICKFRAME = 0x40000000, 0x80000000, 0x00C00000, 0x00040000
WS_CLIPCHILDREN = 0x02000000
WS_EX_TOPMOST, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = 0x00000008, 0x00040000, 0x00000080


def _win32():
    global _USER32
    if _USER32 is None:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowW.restype = wintypes.HWND
        u.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        u.SetParent.restype = wintypes.HWND
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongW.restype = ctypes.c_long
        u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        u.SetWindowLongW.restype = ctypes.c_long
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        _USER32 = u
    return _USER32


def _signed(value):
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value >= 1 << 31 else value


def _attach(child, parent):
    """La fenêtre pywebview devient une fenêtre enfant de celle de l'appli : elle la suit et se réduit avec elle."""
    u = _win32()
    style = u.GetWindowLongW(child, -16)                                  # GWL_STYLE
    u.SetWindowLongW(child, -16, _signed((style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD))
    ex = u.GetWindowLongW(child, -20)                                     # GWL_EXSTYLE
    u.SetWindowLongW(child, -20, _signed((ex & ~(WS_EX_TOPMOST | WS_EX_APPWINDOW)) | WS_EX_TOOLWINDOW))
    pstyle = u.GetWindowLongW(parent, -16)                                # le parent ne peint pas sous l'enfant
    if not pstyle & WS_CLIPCHILDREN:
        u.SetWindowLongW(parent, -16, _signed(pstyle | WS_CLIPCHILDREN))
    return bool(u.SetParent(child, parent))


def _place(child, rect):
    x, y, w, h = rect
    # HWND_TOP ; SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
    _win32().SetWindowPos(child, 0, x, y, max(1, w), max(1, h), 0x0010 | 0x0040 | 0x0020)


def client_rect(parent, logical_size, rect):
    """Rectangle logique de l'appli (surface pygame SCALED) → pixels du client de la fenêtre (mise à l'échelle et
    bandes noires comprises). None si la fenêtre est réduite."""
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    if not _win32().GetClientRect(parent, ctypes.byref(r)):
        return None
    return scale_rect((r.right - r.left, r.bottom - r.top), logical_size, rect)


def scale_rect(client_size, logical_size, rect):
    cw, ch = client_size
    lw, lh = logical_size
    if cw <= 0 or ch <= 0:
        return None
    k = min(cw / lw, ch / lh)
    ox, oy = (cw - lw * k) / 2, (ch - lh * k) / 2
    x, y, w, h = rect
    return (round(ox + x * k), round(oy + y * k), round(w * k), round(h * k))
