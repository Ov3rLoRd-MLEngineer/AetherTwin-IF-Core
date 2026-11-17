"""Overlay pour OBS : une page web locale à fond transparent, à ajouter comme « source navigateur ».

    http://127.0.0.1:5757/obs-hud          la page (HTML, CSS et JS servis d'ici, aucune dépendance externe)
    http://127.0.0.1:5757/obs-hud/events   flux SSE : l'état, renvoyé à chaque changement
    http://127.0.0.1:5757/obs-hud/state    le même état, en JSON (diagnostic)

Deux garanties :
- le serveur n'écoute que sur la boucle locale (`127.0.0.1`) — toute autre adresse est refusée ;
- ce qui est servi vient d'une fonction `snapshot()` fournie par le module, qui ne rend **que** de
  l'état déjà passé par le filtre de confidentialité en mode Showcase. Le serveur ne lit rien d'autre.

Bibliothèque standard uniquement (pas de FastAPI ici : le serveur vit dans le processus du module).
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parent / "web"
LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "logo_if_core_mono.svg"
LOOPBACK = ("127.0.0.1", "localhost")
DEFAULT_PORT = 5757

# chemin de l'URL -> (fichier, type MIME). Liste fermée : aucun autre fichier ne peut être servi.
STATIC = {
    "/obs-hud": ("obs_hud.html", "text/html; charset=utf-8"),
    "/obs-hud/": ("obs_hud.html", "text/html; charset=utf-8"),
    "/obs-hud/style.css": ("obs_hud.css", "text/css; charset=utf-8"),
    "/obs-hud/app.js": ("obs_hud.js", "text/javascript; charset=utf-8"),
}
# La page ne peut charger que ses propres fichiers et ne se connecter qu'à ce serveur.
CSP = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; connect-src 'self'"


class ObsServer:
    """Sert la page d'overlay et son flux d'état."""

    def __init__(self, snapshot: Callable[[], dict[str, Any]], host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 interval_s: float = 1.0, heartbeat_s: float = 15.0) -> None:
        if host not in LOOPBACK:
            raise ValueError(f"l'overlay n'écoute que sur la boucle locale, pas sur {host!r}")
        self.snapshot = snapshot
        self.host, self.port = "127.0.0.1", port
        self.interval_s, self.heartbeat_s = interval_s, heartbeat_s
        self._server: ThreadingHTTPServer | None = None
        self._stopping = threading.Event()
        self.clients = 0

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/obs-hud"

    def start(self) -> str:
        """Démarre le serveur. Lève `OSError` si le port est déjà pris."""
        handler = type("ObsHandler", (_Handler,), {"owner": self})
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._stopping.clear()
        threading.Thread(target=self._server.serve_forever, name="obs-hud", daemon=True).start()
        return self.url

    def stop(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def payload(self) -> str:
        """État courant sérialisé. Une erreur de lecture donne un état vide, jamais une exception."""
        try:
            data = self.snapshot()
        except Exception as exc:  # noqa: BLE001 — l'overlay ne doit jamais tomber en direct
            data = {"error": type(exc).__name__}
        return json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))


class _Handler(BaseHTTPRequestHandler):
    owner: ObsServer
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in STATIC:
            name, content_type = STATIC[path]
            try:
                self._send(200, (WEB_DIR / name).read_bytes(), content_type)
            except OSError:
                self._send(500, b"fichier de l'overlay introuvable", "text/plain; charset=utf-8")
        elif path == "/obs-hud/logo.svg":
            try:
                self._send(200, LOGO_PATH.read_bytes(), "image/svg+xml")
            except OSError:
                self._send(404, b"", "image/svg+xml")
        elif path == "/obs-hud/state":
            self._send(200, self.owner.payload().encode("utf-8"), "application/json; charset=utf-8")
        elif path == "/obs-hud/events":
            self._stream()
        elif path == "/favicon.ico":  # demandée d'office par les navigateurs : réponse vide, pas d'erreur en console
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(404, b"introuvable", "text/plain; charset=utf-8")

    def _stream(self) -> None:
        """Flux SSE : envoie l'état quand il change, et un battement régulier pour garder la connexion."""
        owner = self.owner
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.close_connection = True
        owner.clients += 1
        last, last_sent = None, 0.0
        try:
            while not owner._stopping.is_set():
                now = time.monotonic()
                payload = owner.payload()
                if payload != last:
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    last, last_sent = payload, now
                elif now - last_sent >= owner.heartbeat_s:
                    self.wfile.write(b": battement\n\n")
                    last_sent = now
                self.wfile.flush()
                owner._stopping.wait(owner.interval_s)
        except (BrokenPipeError, ConnectionError, OSError):
            pass  # la source navigateur a été fermée
        finally:
            owner.clients -= 1

    def log_message(self, *_args: object) -> None:
        pass  # pas de journal d'accès : rien n'est écrit sur la sortie du module


def overlay_view(visible: dict[str, Any], gpus: list[dict[str, Any]], showcase: bool,
                 max_quests: int = 4) -> dict[str, Any]:
    """Réduit un état DÉJÀ FILTRÉ à ce que la page affiche. Ne lit que des champs connus, rien d'autre."""
    view: dict[str, Any] = {"showcase": showcase, "ts": int(time.time()), "gpus": [
        {"index": g.get("index"), "name": g.get("name"), "util": g.get("utilization_pct"),
         "vram_used": g.get("vram_used_mib"), "vram_total": g.get("vram_total_mib"),
         "temp": g.get("temperature_c"), "power": g.get("power_w")} for g in gpus]}
    character = visible.get("character")
    if isinstance(character, dict) and character:
        zone, sub = character.get("zone") or "", character.get("subzone") or ""
        view["character"] = {
            "name": character.get("name"), "level": character.get("level"), "class": character.get("class"),
            "spec": character.get("specialization"),
            "zone": f"{zone} - {sub}" if zone and sub and sub != zone else zone,
            "ilvl": character.get("ilvl"), "money": character.get("money"),
        }
    quests = visible.get("quests")
    if isinstance(quests, dict):
        titles = [str(q.get("title")) for q in quests.get("list", []) if isinstance(q, dict) and q.get("title")]
        view["quests"] = {"count": quests.get("count") or len(titles), "titles": titles[:max_quests]}
    fields = visible.get("fields")
    if isinstance(fields, dict) and fields:
        view["fields"] = {str(k): (v[-3:] if isinstance(v, list) else v) for k, v in list(fields.items())[:8]}
    return view
