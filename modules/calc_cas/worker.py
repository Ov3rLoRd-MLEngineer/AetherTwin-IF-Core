"""Processus de calcul séparé, avec délai maximal.

SymPy ne peut pas être interrompu proprement dans un fil d'exécution : un calcul pathologique (intégrale sans
fin, `9^9^9`) bloquerait le module. Tous les calculs passent donc par un processus enfant ; au-delà du délai,
le parent le tue, en relance un neuf et y rejoue les définitions de l'utilisateur (variables, fonctions).

    runner = CasRunner(timeout_s=10)
    runner.call("eval", text="integrate(x^2, x)")            # -> {"ok": True, "exact": "x**3/3", …}
    runner.call("eval", text="9^9^9")                          # -> {"ok": False, "timeout": True, "error": …}

Plusieurs sessions indépendantes vivent dans le même processus (« user » pour l'interface, « agent » pour les
modèles locaux) : un agent ne voit ni ne modifie les variables de l'utilisateur.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
import threading
import time
from multiprocessing.connection import Connection
from typing import Any

STARTUP_S = 90.0  # premier import de SymPy (disque froid) : bien plus long qu'un calcul
_JOB: Any = None  # objet de tâche Windows gardé ouvert tant que le processus vit


def job_limits() -> Any:
    """Structure JOBOBJECT_EXTENDED_LIMIT_INFORMATION (Windows), vide."""
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    return Extended()


def limit_memory(megabytes: int) -> bool:
    """Borne la mémoire du processus courant (objet de tâche Windows, `RLIMIT_AS` ailleurs). `False` si impossible."""
    limit = int(megabytes) * 1024 * 1024
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = job_limits()
        info.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = limit
        ok = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) and \
            kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())
        global _JOB
        _JOB = job
        return bool(ok)
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        return True
    except (ImportError, ValueError, OSError):
        return False


def _dispatch(sessions: dict[str, Any], op: str, args: dict[str, Any]) -> Any:
    from modules.calc_cas import engine

    session = sessions.setdefault(str(args.pop("session", "user")), engine.Session())
    if op in ("plot", "analyze", "table"):
        from modules.calc_cas import graph
    if op in ("stats", "regress"):
        from modules.calc_cas import stats
    if op == "program":
        from modules.calc_cas.sandbox import run_program

        return run_program(str(args.get("code", "")), list(args.get("inputs") or []), args.get("seed"), session)
    if op == "settings":
        for key, value in args.items():
            if key not in engine.SETTINGS or value not in engine.SETTINGS[key]:
                raise ValueError(f"réglage invalide : {key} = {value!r}")
            session.settings[key] = value
        return dict(session.settings)
    if op == "eval":
        return engine.evaluate(args["text"], session)
    if op == "restore":  # rejoue des définitions (après une relance)
        return [engine.evaluate(src, session)["ok"] for src in args["sources"]]
    if op == "vars":
        return session.listing()
    if op == "delete":
        return session.delete(str(args["name"]))
    if op == "reset":
        sessions.pop(str(args.get("target", "user")), None)
        return True
    if op == "plot":
        return graph.plot(args["curves"], args.get("window") or {}, session, int(args.get("samples", 600)))
    if op == "analyze":
        return graph.analyze(args, session)
    if op == "table":
        return graph.table(args, session)
    if op == "geometry":
        from modules.calc_cas.geometry import measure

        return measure(args, session)
    if op == "stats":
        return stats.describe(args, session)
    if op == "regress":
        return stats.regress(args, session)
    if op == "ping":
        return "pong"
    raise ValueError(f"opération inconnue : {op!r}")


def worker_main(conn: Connection, memory_mb: int | None = None) -> None:
    """Boucle du processus enfant : (op, args) -> ("ok", résultat) | ("error", message)."""
    if memory_mb:
        limit_memory(memory_mb)
    try:
        import modules.calc_cas.engine  # noqa: F401 — import lourd fait une fois, avant le signal « prêt »
        conn.send(("ready", None))
    except Exception as exc:  # noqa: BLE001 — SymPy absent ou cassé : le parent passe en mode dégradé
        conn.send(("broken", f"{type(exc).__name__}: {exc}"))
        return
    sessions: dict[str, Any] = {}
    while True:
        try:
            op, args = conn.recv()
        except (EOFError, OSError):
            return
        if op == "quit":
            return
        try:
            conn.send(("ok", _dispatch(sessions, op, dict(args))))
        except Exception as exc:  # noqa: BLE001 — le processus ne meurt jamais d'un mauvais calcul
            from modules.calc_cas.engine import CasError, _explain

            conn.send(("error", str(exc) if isinstance(exc, CasError | ValueError | KeyError) and str(exc)
                       else _explain(exc)))


class CasRunner:
    """Côté parent : un processus enfant à la fois, relancé après un délai dépassé."""

    def __init__(self, timeout_s: float = 10.0, memory_mb: int | None = None) -> None:
        self.timeout_s = float(timeout_s)
        self.memory_mb = memory_mb
        self.settings: dict[str, dict[str, Any]] = {}  # session -> réglages (angle…), rejoués après relance
        self.lock = threading.Lock()
        self.proc: Any = None
        self.conn: Connection | None = None
        self.ready = False
        self.broken = ""
        self.restarts = 0
        self.definitions: dict[str, dict[str, str]] = {}  # session -> {nom: source}, rejouées après relance

    # -- cycle de vie
    def start(self) -> None:
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self.proc = ctx.Process(target=worker_main, args=(child, self.memory_mb), daemon=True, name="calc_cas-worker")
        self.proc.start()
        child.close()
        self.conn, self.ready = parent, False

    def _wait_ready(self) -> None:
        if self.ready:
            return
        if self.conn is None or not self.conn.poll(STARTUP_S):
            self._kill()
            raise RuntimeError("le moteur de calcul n'a pas démarré")
        status, detail = self.conn.recv()
        if status != "ready":
            self.broken = str(detail)
            self._kill()
            raise RuntimeError(f"moteur de calcul indisponible : {detail}")
        self.ready = True
        for session, values in self.settings.items():
            self.conn.send(("settings", {"session": session, **values}))
            if self.conn.poll(self.timeout_s):
                self.conn.recv()
        for session, defs in self.definitions.items():
            if defs:
                self.conn.send(("restore", {"session": session, "sources": list(defs.values())}))
                if self.conn.poll(self.timeout_s * max(1, len(defs))):
                    self.conn.recv()

    def _kill(self) -> None:
        if self.proc is not None and self.proc.is_alive():
            self.proc.terminate()
            self.proc.join(5)
            if self.proc.is_alive():
                self.proc.kill()
                self.proc.join(5)
        if self.conn is not None:
            self.conn.close()
        self.proc, self.conn, self.ready = None, None, False

    def stop(self) -> None:
        with self.lock:
            if self.conn is not None and self.proc is not None and self.proc.is_alive():
                try:
                    self.conn.send(("quit", {}))
                    self.proc.join(3)
                except OSError:
                    pass
            self._kill()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.is_alive()

    # -- appels
    def call(self, op: str, timeout_s: float | None = None, **args: Any) -> Any:
        """Exécute une opération dans le processus enfant. Délai dépassé : dictionnaire d'erreur, enfant relancé.

        Lève `RuntimeError` si le moteur ne peut pas démarrer (SymPy absent), `ValueError` pour une opération
        invalide."""
        if self.broken:
            raise RuntimeError(f"moteur de calcul indisponible : {self.broken}")
        limit = self.timeout_s if timeout_s is None else float(timeout_s)
        with self.lock:
            if not self.alive():
                self.start()
            self._wait_ready()
            if self.conn is None:
                raise RuntimeError("moteur de calcul non lancé")
            started = time.monotonic()
            try:
                self.conn.send((op, args))
                finished = self.conn.poll(limit)
            except (OSError, EOFError):
                finished = False
            if not finished:
                self._kill()
                self.restarts += 1
                return {"ok": False, "timeout": True,
                        "error": f"Délai dépassé ({limit:g} s) : calcul interrompu. Simplifie l'expression ou "
                                 "utilise une valeur approchée (approx, nsolve)."}
            try:
                status, value = self.conn.recv()
            except (EOFError, OSError):
                self._kill()
                self.restarts += 1
                return {"ok": False, "error": "Le moteur de calcul s'est arrêté (mémoire ?) : il a été relancé"}
        if status == "error":
            raise ValueError(value)
        self._remember(op, args, value)
        if isinstance(value, dict) and "ok" in value:
            value.setdefault("elapsed_ms", round((time.monotonic() - started) * 1000))
        return value

    def _remember(self, op: str, args: dict[str, Any], value: Any) -> None:
        session = str(args.get("session", "user"))
        defs = self.definitions.setdefault(session, {})
        if op == "eval" and isinstance(value, dict) and value.get("ok") and value.get("definition"):
            name = value["definition"]["name"]
            defs.pop(name, None)  # une redéfinition passe en dernier (ordre de rejeu)
            defs[name] = value["definition"]["source"]
        elif op == "settings" and isinstance(value, dict):
            self.settings[session] = dict(value)
        elif op == "delete":
            defs.pop(str(args.get("name")), None)
        elif op == "reset":
            self.definitions.pop(str(args.get("target", "user")), None)
            self.settings.pop(str(args.get("target", "user")), None)
