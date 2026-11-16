"""Bus d'événements local du Hub : publication / abonnement entre processus, sur 127.0.0.1 uniquement.

- `EventBus` vit dans le daemon : abonnements locaux (fonctions) et clients distants (modules).
- `BusClient` vit dans chaque processus de module.

Transport : `multiprocessing.connection` (TCP local authentifié par une clé tirée au hasard à chaque
lancement et transmise aux modules par leur environnement). Les messages sont du JSON, jamais du
`pickle` : un module ne peut pas faire exécuter de code au daemon.
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import secrets
import socket
import threading
from collections import deque
from collections.abc import Callable
from multiprocessing.connection import Client, Connection, Listener
from typing import Any

from core.module_api import Event

LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
ENV_ADDRESS = "AETHERTWIN_BUS_ADDR"
ENV_KEY = "AETHERTWIN_BUS_KEY"


def _send(conn: Connection, lock: threading.Lock, message: dict[str, Any]) -> None:
    with lock:
        conn.send_bytes(json.dumps(message, ensure_ascii=False).encode("utf-8"))


def _recv(conn: Connection) -> dict[str, Any]:
    message = json.loads(conn.recv_bytes(maxlength=8 * 1024 * 1024).decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("message de bus inattendu")
    return message


class _Remote:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.lock = threading.Lock()
        self.patterns: set[str] = set()
        self.name = "?"


class EventBus:
    """Centre du bus. `publish` sert les abonnés locaux puis les clients distants abonnés au sujet."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, authkey: bytes | None = None,
                 history: int = 200) -> None:
        if host not in LOOPBACK_HOSTS:
            raise ValueError(f"le bus n'écoute que sur la boucle locale, pas sur {host!r}")
        self._bind = ("127.0.0.1", port)
        self.authkey = authkey or secrets.token_bytes(32)
        self.address: tuple[str, int] | None = None
        self.history: deque[Event] = deque(maxlen=history)
        self._local: list[tuple[str, Callable[[Event], None]]] = []
        self._remotes: list[_Remote] = []
        self._lock = threading.RLock()
        self._listener: Listener | None = None
        self._stopping = False

    # -- cycle de vie
    def start(self) -> tuple[str, int]:
        self._listener = Listener(self._bind, family="AF_INET", authkey=self.authkey)
        self.address = self._listener.address  # type: ignore[assignment]
        threading.Thread(target=self._accept_loop, name="bus-accept", daemon=True).start()
        return self.address  # type: ignore[return-value]

    def stop(self) -> None:
        self._stopping = True
        with self._lock:
            remotes, self._remotes = self._remotes, []
        for remote in remotes:
            with contextlib.suppress(OSError):
                remote.conn.close()
        if self._listener is not None and self.address is not None:
            with contextlib.suppress(OSError):  # débloque accept(), qui attend une connexion
                socket.create_connection(self.address, timeout=1).close()
            with contextlib.suppress(OSError):
                self._listener.close()
            self._listener = None

    def child_env(self) -> dict[str, str]:
        """Variables à donner à un processus de module pour qu'il rejoigne le bus."""
        if self.address is None:
            raise RuntimeError("bus non démarré")
        return {ENV_ADDRESS: f"{self.address[0]}:{self.address[1]}", ENV_KEY: self.authkey.hex()}

    # -- abonnements locaux et publication
    def subscribe(self, pattern: str, callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._local.append((pattern, callback))

    def publish(self, event: Event) -> None:
        with self._lock:
            self.history.append(event)
            local = list(self._local)
            remotes = [r for r in self._remotes if any(event.matches(p) for p in r.patterns)]
        for pattern, callback in local:
            if event.matches(pattern):
                with contextlib.suppress(Exception):  # un abonné défaillant ne bloque pas les autres
                    callback(event)
        for remote in remotes:
            try:
                _send(remote.conn, remote.lock, {"op": "event", "event": event.to_dict()})
            except (OSError, ValueError):
                self._drop(remote)

    def clients(self) -> list[str]:
        with self._lock:
            return [remote.name for remote in self._remotes]

    # -- côté serveur
    def _accept_loop(self) -> None:
        while not self._stopping and self._listener is not None:
            try:
                conn = self._listener.accept()
            except Exception:  # noqa: BLE001, S112 — clé refusée, connexion coupée, écoute fermée
                continue
            if self._stopping:
                conn.close()
                break
            remote = _Remote(conn)
            with self._lock:
                self._remotes.append(remote)
            threading.Thread(target=self._reader, args=(remote,), name="bus-reader", daemon=True).start()

    def _reader(self, remote: _Remote) -> None:
        try:
            while True:
                message = _recv(remote.conn)
                op = message.get("op")
                if op == "hello":
                    remote.name = str(message.get("name", "?"))
                elif op == "sub":
                    with self._lock:
                        remote.patterns.update(str(p) for p in message.get("patterns", []))
                    _send(remote.conn, remote.lock, {"op": "ack"})
                elif op == "pub":
                    self.publish(Event.from_dict(message["event"]))
        except (EOFError, OSError, ValueError, KeyError, TypeError):
            pass  # client parti ou message invalide : on ferme cette connexion
        finally:
            self._drop(remote)

    def _drop(self, remote: _Remote) -> None:
        with self._lock:
            if remote in self._remotes:
                self._remotes.remove(remote)
        with contextlib.suppress(OSError):
            remote.conn.close()


class BusClient:
    """Client du bus, utilisé dans le processus d'un module."""

    def __init__(self, address: tuple[str, int], authkey: bytes, name: str = "client") -> None:
        self._conn = Client(tuple(address), family="AF_INET", authkey=authkey)
        self._lock = threading.Lock()
        self._events: queue.Queue[Event] = queue.Queue()
        self._ack = threading.Event()
        self.closed = False
        threading.Thread(target=self._reader, name="bus-client", daemon=True).start()
        _send(self._conn, self._lock, {"op": "hello", "name": name})

    @classmethod
    def from_env(cls, name: str, env: dict[str, str] | None = None) -> BusClient:
        env = env if env is not None else dict(os.environ)
        host, port = env[ENV_ADDRESS].rsplit(":", 1)
        return cls((host, int(port)), bytes.fromhex(env[ENV_KEY]), name)

    def _reader(self) -> None:
        try:
            while True:
                message = _recv(self._conn)
                if message.get("op") == "ack":
                    self._ack.set()
                elif message.get("op") == "event":
                    self._events.put(Event.from_dict(message["event"]))
        except (EOFError, OSError, ValueError, KeyError, TypeError):
            self.closed = True

    def subscribe(self, *patterns: str, timeout: float = 5.0) -> None:
        """S'abonne et attend la confirmation du bus : aucun événement publié ensuite n'est perdu."""
        self._ack.clear()
        _send(self._conn, self._lock, {"op": "sub", "patterns": list(patterns)})
        if not self._ack.wait(timeout):
            raise TimeoutError("le bus n'a pas confirmé l'abonnement")

    def publish(self, event: Event) -> None:
        try:
            _send(self._conn, self._lock, {"op": "pub", "event": event.to_dict()})
        except (OSError, ValueError):
            self.closed = True

    def recv(self, timeout: float | None = None) -> Event | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.closed = True
        with contextlib.suppress(OSError):
            self._conn.close()
