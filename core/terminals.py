"""Terminaux du Hub : une console Windows (pseudo-terminal) affichée dans le tableau de bord.

Le démon garde les sessions (`cmd.exe` dans un pseudo-terminal `pywinpty`) ; la page les affiche avec xterm.js et
leur parle par WebSocket (`/terminals/<id>/ws`). Une session survit au rechargement de la page : la sortie récente
est gardée en mémoire et rejouée à la reconnexion.

Sécurité :
- l'identifiant de session est un secret aléatoire, renvoyé seulement à la page du Hub (POST refusé depuis une
  autre origine, réponse illisible pour un autre site) ;
- la WebSocket vérifie l'hôte et l'origine (le contrôle HTTP du Hub ne s'applique pas aux WebSockets) ;
- une session lance soit `cmd.exe` seul, soit un fichier de lancement écrit par le module `dev_launcher` dans son
  dossier (`data/dev_launcher/lancements`), rien d'autre.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_SESSIONS = 6
REPLAY_BYTES = 200_000


INHERITED = ("AETHERTWIN_BUS", "CLAUDE", "ANTHROPIC_")


def child_env() -> dict[str, str]:
    """Environnement d'un terminal : sans le bus du Hub ni les variables d'une session Claude Code qui aurait
    lancé le Hub (jeton de messagerie, identifiants de session…) : le terminal repart d'un état propre."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(INHERITED)}


class TerminalError(ValueError):
    """Session inconnue, lancement refusé ou pseudo-terminal indisponible."""


def _spawn_pty(argv: list[str], cwd: str, env: dict[str, str], rows: int, cols: int) -> Any:
    from winpty import PtyProcess  # dépendance Windows (pywinpty)

    return PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(rows, cols))


class Session:
    """Un pseudo-terminal, sa sortie récente et ses abonnés (les pages ouvertes)."""

    def __init__(self, sid: str, title: str, proc: Any, now: float) -> None:
        self.id, self.title, self.proc, self.started = sid, title, proc, now
        self.buffer = ""
        self.listeners: list[Callable[[str], None]] = []
        self.lock = threading.Lock()
        self.ended = False

    def feed(self, text: str) -> None:
        with self.lock:
            self.buffer = (self.buffer + text)[-REPLAY_BYTES:]
            listeners = list(self.listeners)
        for listener in listeners:
            listener(text)

    def subscribe(self, listener: Callable[[str], None]) -> str:
        with self.lock:
            self.listeners.append(listener)
            return self.buffer

    def unsubscribe(self, listener: Callable[[str], None]) -> None:
        with self.lock:
            if listener in self.listeners:
                self.listeners.remove(listener)

    def alive(self) -> bool:
        try:
            return bool(self.proc.isalive())
        except Exception:  # noqa: BLE001 — processus déjà libéré
            return False

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "titre": self.title, "debut": self.started, "actif": self.alive() and not self.ended}


class TerminalManager:
    """Sessions ouvertes. `launches_dir` : seul dossier d'où un fichier de lancement peut être exécuté."""

    def __init__(self, launches_dir: Path, spawn: Callable[..., Any] = _spawn_pty,
                 now: Callable[[], float] = time.time) -> None:
        self.launches_dir = Path(launches_dir)
        self.spawn, self.now = spawn, now
        self.sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _launch_file(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or not name.endswith(".bat"):
            raise TerminalError("fichier de lancement invalide")
        path = (self.launches_dir / name).resolve()
        if path.parent != self.launches_dir.resolve() or not path.is_file():
            raise TerminalError("fichier de lancement introuvable")
        return path

    def open(self, launch: str = "", cwd: str = "", title: str = "", rows: int = 30, cols: int = 110) -> dict[str, Any]:
        """Ouvre `cmd.exe` (dans `cwd`), ou exécute un fichier de lancement du module dev_launcher."""
        with self._lock:
            self._prune()
            if len(self.sessions) >= MAX_SESSIONS:
                raise TerminalError(f"{MAX_SESSIONS} terminaux ouverts au plus : fermez-en un")
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        if launch:
            path = self._launch_file(launch)
            argv, folder = [comspec, "/k", str(path)], str(path.parent)
            title = title or path.stem
        else:
            folder = cwd if cwd and Path(cwd).is_dir() else str(Path.home())
            argv, title = [comspec], title or "Invite de commandes"
        env = child_env()
        env["TERM"] = "xterm-256color"
        try:
            proc = self.spawn(argv, folder, env, max(5, min(rows, 200)), max(20, min(cols, 400)))
        except ImportError as exc:
            raise TerminalError("pseudo-terminal indisponible (paquet pywinpty absent)") from exc
        except OSError as exc:
            raise TerminalError(f"lancement impossible : {exc}") from exc
        session = Session(secrets.token_urlsafe(24), title[:80], proc, self.now())
        with self._lock:
            self.sessions[session.id] = session
        threading.Thread(target=self._pump, args=(session,), name=f"term-{session.id[:6]}", daemon=True).start()
        return session.view()

    def _pump(self, session: Session) -> None:
        """Lit la sortie du pseudo-terminal jusqu'à la fin du processus."""
        while True:
            try:
                text = session.proc.read(4096)
            except EOFError:
                break
            except Exception:  # noqa: BLE001 — pseudo-terminal fermé
                break
            if text:
                session.feed(text)
            elif not session.alive():
                break
        session.ended = True
        session.feed("\r\n[processus terminé]\r\n")

    def get(self, sid: str) -> Session:
        session = self.sessions.get(sid or "")
        if session is None:
            raise TerminalError("terminal inconnu")
        return session

    def write(self, sid: str, data: str) -> None:
        session = self.get(sid)
        if session.alive():
            session.proc.write(data[:65536])

    def resize(self, sid: str, rows: int, cols: int) -> None:
        session = self.get(sid)
        if session.alive():
            session.proc.setwinsize(max(5, min(int(rows), 200)), max(20, min(int(cols), 400)))

    def close(self, sid: str) -> dict[str, Any]:
        session = self.get(sid)
        try:
            session.proc.terminate(force=True)
        except Exception:  # noqa: BLE001, S110 — déjà terminé
            pass
        with self._lock:
            self.sessions.pop(sid, None)
        return {"id": sid, "ferme": True}

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            self._prune()
            return [s.view() for s in self.sessions.values()]

    def _prune(self) -> None:
        """Oublie les sessions terminées depuis plus de 10 minutes."""
        for sid, session in list(self.sessions.items()):
            if session.ended and self.now() - session.started > 600:
                self.sessions.pop(sid, None)

    def close_all(self) -> None:
        for sid in list(self.sessions):
            self.close(sid)
