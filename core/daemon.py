"""Le démon : centre de l'architecture en étoile.

Il tient le bus d'événements, le registre des modules et les deux gardiens. À chaque tour (`tick`) :
  1. il observe les processus de la machine et publie `process.started` / `process.stopped` ;
  2. il active le module dont un déclencheur vient d'apparaître, et le désactive quand il disparaît ;
  3. Fuma redémarre les modules tombés et signale les GPU trop chauds ;
  4. la nuit, Fuma lance les tâches lourdes planifiées.

Chaque module tourne dans un processus séparé (`core.module_runner`). Le démon démarre sans GPU
et sans `psutil` (mode dégradé).

    python -m core.daemon            # démon + API HTTP sur 127.0.0.1:5750
    python -m core.daemon --no-api   # démon seul
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import config
from core.bus import EventBus
from core.guardians.fuma import Fuma
from core.guardians.inoue import Decision, Inoue, Verdict
from core.hardware.gpu_monitor import GpuMonitor
from core.llm_router import LlmConfig, LlmRouter
from core.module_api import (
    MANIFEST_NAME,
    Event,
    Health,
    Manifest,
    ManifestError,
    discover_manifests,
    load_manifest,
)
from core.scheduler import GpuScheduler
from core.strata import StrataBackend, StrataConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 5750


def psutil_process_names() -> set[str] | None:
    """Noms (en minuscules) des processus en cours ; `None` si `psutil` est absent (mode dégradé)."""
    try:
        import psutil
    except ImportError:
        return None
    names = set()
    for proc in psutil.process_iter(["name"]):
        with contextlib.suppress(Exception):
            if proc.info["name"]:
                names.add(proc.info["name"].lower())
    return names


# Garde-fou des modules (voir `Daemon.hung` et `core.module_runner`).
HEARTBEAT_STALE_S = 30.0  # plus de battement : processus figé
BUSY_FAIL_FAST_S = 60.0  # occupé depuis plus longtemps : refus immédiat (un long travail n'est pas coupé)
MAX_PENDING = 4  # demandes en attente au plus par module (protège les fils du serveur)

@dataclass
class ManagedModule:
    manifest: Manifest
    directory: Path
    proc: subprocess.Popen[bytes] | None = None
    active: bool = False
    auto: bool = False  # activé par un déclencheur (et donc désactivé quand il disparaît)
    waiting_vram: bool = False
    last_health: dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    starts: int = 0
    busy: str = ""  # commande en cours (battement de cœur du module)
    busy_s: float = 0.0
    heartbeat_at: float = 0.0  # 0 = jamais reçu (ancien module ou démarrage)
    pending: int = 0  # commandes envoyées sans réponse

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


class Daemon:
    """Registre de modules + bus + gardiens. Toutes les sources externes sont injectables (tests)."""

    def __init__(self, modules_root: Path | None = None, monitor: GpuMonitor | None = None,
                 process_names: Callable[[], set[str] | None] = psutil_process_names,
                 now: Callable[[], float] = time.time, python: str = sys.executable,
                 llm: LlmRouter | None = None, knowledge: Any = None) -> None:
        self.modules_root = modules_root or REPO_ROOT / "modules"
        self.monitor = monitor or GpuMonitor()
        self.bus = EventBus()
        self.inoue = Inoue(self.monitor)
        self.llm = llm or LlmRouter(self.inoue, LlmConfig.from_section(config.section("ollama")),
                                    strata=StrataBackend(StrataConfig.from_section(config.section("strata"))))
        self.contexts: dict[str, str] = {}  # module -> dernier contexte publié pour l'assistant
        self.states: dict[str, dict[str, Any]] = {}  # module -> dernier état publié (déjà filtré par le module)
        self.apps: dict[str, subprocess.Popen[bytes]] = {}  # module -> application de bureau lancée
        self.fuma = Fuma(now=now)
        self.scheduler = GpuScheduler(self.inoue)
        self.modules: dict[str, ManagedModule] = {}
        self.manifest_errors: dict[str, str] = {}
        self.os_name = f"{platform.system()} {platform.release()}"
        self._process_names = process_names
        self._seen: set[str] = set()
        self._python = python
        self._lock = threading.RLock()
        self._started_at = now()
        self._now = now
        self.process_watch_degraded = False
        self._pending: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self.knowledge = knowledge  # core.knowledge.service.KnowledgeService, ou None (pas de base)
        if knowledge is not None and getattr(knowledge, "nightly", False):
            self.fuma.schedule_night_task("ingestion des connaissances", knowledge.start_ingestion, recurring=True)

    # -- cycle de vie
    def start(self) -> None:
        self.bus.start()
        self.bus.subscribe("module", self._on_module_event)
        self.reload_modules()
        self._seen = self._process_names() or set()
        self.bus.publish(Event("hub.started", {"os": self.os_name, "gpu_backend": self.monitor.backend_name,
                                               "modules": sorted(self.modules)}))

    def stop(self) -> None:
        self.bus.publish(Event("hub.shutdown"))
        for name in list(self.modules):
            self.deactivate(name)
        for name in list(self.apps):
            self.stop_app(name)
        if self.knowledge is not None:
            self.knowledge.stop()
        self.scheduler.shutdown()
        self.bus.stop()

    def reload_modules(self) -> None:
        """(Re)lit les manifestes de `modules/`. Un manifeste invalide est signalé, pas fatal."""
        found, self.manifest_errors = discover_manifests(self.modules_root)
        directories: dict[str, Path] = {}
        for child in sorted(self.modules_root.iterdir()) if self.modules_root.is_dir() else []:
            name = _manifest_name(child) if (child / MANIFEST_NAME).is_file() else None
            if name and name not in directories:
                directories[name] = child
        with self._lock:
            for name, manifest in found.items():
                if name in self.modules:
                    self.modules[name].manifest = manifest
                else:
                    self.modules[name] = ManagedModule(manifest, directories[name])

    # -- activation
    def activate(self, name: str, auto: bool = False) -> Decision:
        """Demande la VRAM à Inoue puis lance le module dans son processus. Idempotent."""
        with self._lock:
            module = self.modules[name]
            if module.active and module.running():
                return Decision(Verdict.GRANTED, reason="déjà actif")
            decision = self.inoue.request(name, module.manifest.vram_min_gb, module.manifest.vram_comfort_gb)
            module.waiting_vram = decision.verdict is Verdict.QUEUED
            module.auto = auto
            if decision.verdict is not Verdict.GRANTED:
                module.last_error = decision.reason
                self.bus.publish(Event(f"module.{name}.vram", {"verdict": decision.verdict.value,
                                                               "reason": decision.reason}))
                return decision
            self._spawn(module)
            module.active = True
            self.fuma.watch(name, lambda: self._health(name), lambda: self._respawn(name))
            return decision

    def deactivate(self, name: str, timeout_s: float = 8.0) -> None:
        """Arrêt propre (ordre sur le bus), puis arrêt forcé si le module ne répond pas. Rend la VRAM."""
        with self._lock:
            module = self.modules[name]
            self.fuma.unwatch(name)
            was_active, module.active, module.auto, module.waiting_vram = module.active, False, False, False
            proc = module.proc
        if proc is not None and proc.poll() is None:
            self.bus.publish(Event(f"module.{name}.cmd.stop"))
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)
        if was_active or name in self.inoue.state()["allocations"] or name in self.inoue.state()["queue"]:
            for served, _decision in self.inoue.release(name):
                if served in self.modules and self.modules[served].waiting_vram:
                    self.activate(served, auto=self.modules[served].auto)

    def _spawn(self, module: ManagedModule) -> None:
        env = dict(os.environ, **self.bus.child_env())
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH", "")]))
        module.proc = subprocess.Popen([self._python, "-m", "core.module_runner", str(module.directory)],
                                       cwd=str(REPO_ROOT), env=env, stdin=subprocess.DEVNULL)
        module.starts += 1
        module.last_error = ""
        module.last_health = {}  # rempli par `module.<nom>.started` : sert à savoir qu'il écoute le bus
        module.busy, module.busy_s, module.heartbeat_at = "", 0.0, 0.0  # état du processus précédent oublié

    def _respawn(self, name: str) -> None:
        with self._lock:
            module = self.modules[name]
            if module.active and module.running() and module.proc is not None:
                # Bloqué (commande sans fin, plus de battement) : arrêté de force avant d'être relancé.
                module.proc.kill()
                try:
                    module.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    return
            if module.active and not module.running():
                self._spawn(module)
                self.bus.publish(Event(f"module.{name}.restarted", {"starts": module.starts}, source="fuma"))

    def _health(self, name: str) -> Health:
        module = self.modules[name]
        if not module.running():
            code = module.proc.poll() if module.proc else None
            return Health(ok=False, detail=f"processus arrêté (code {code})")
        hung = self.hung(name)
        if hung:
            return Health(ok=False, detail=hung)
        return Health(ok=True, degraded=bool(module.last_health.get("degraded")),
                      detail=str(module.last_health.get("detail", "")))

    def _on_module_event(self, event: Event) -> None:
        parts = event.topic.split(".")
        if len(parts) < 3 or parts[1] not in self.modules:
            return
        module = self.modules[parts[1]]
        if parts[2] == "health":
            module.last_health = dict(event.payload)
        elif parts[2] == "started":
            module.last_health = dict(event.payload.get("health") or {})
        elif parts[2] == "error":
            module.last_error = str(event.payload.get("error", ""))
        elif parts[2] == "heartbeat":
            module.busy = str(event.payload.get("busy", ""))[:60]
            module.busy_s = float(event.payload.get("busy_s") or 0.0)
            module.heartbeat_at = self._now()
        elif parts[2] == "state":
            self.states[parts[1]] = {**event.payload, "received_at": self._now()}
            if event.payload.get("context"):
                self.contexts[parts[1]] = str(event.payload["context"])
        elif parts[2] == "result":
            waiter = self._pending.get(str(event.payload.get("request_id")))
            if waiter is not None:
                waiter[1].update(event.payload)
                waiter[0].set()

    # -- application de bureau d'un module (ex. la fenêtre de WoW Assistant)
    def app_spec(self, name: str) -> dict[str, str] | None:
        """`"app": {"label": …, "module": …}` du manifeste : un module Python fixe (validé au chargement du
        manifeste), jamais une commande libre."""
        app = self.modules[name].manifest.app
        return {"label": app[0], "module": app[1]} if app else None

    def app_running(self, name: str) -> bool:
        proc = self.apps.get(name)
        return proc is not None and proc.poll() is None

    def start_app(self, name: str) -> bool:
        """Lance l'application (`python -m <module>` depuis la racine du dépôt). `False` si elle tourne déjà."""
        spec = self.app_spec(name)
        if spec is None:
            raise ValueError(f"le module {name} n'a pas d'application de bureau")
        if self.app_running(name):
            return False
        self.apps[name] = subprocess.Popen([self._python, "-m", spec["module"]], cwd=str(REPO_ROOT),
                                           stdin=subprocess.DEVNULL)
        self.bus.publish(Event(f"module.{name}.app", {"running": True, "label": spec["label"]}))
        return True

    def stop_app(self, name: str, timeout_s: float = 6.0) -> str:
        """Ferme l'application **doucement** (demande de fermeture de fenêtre : elle enregistre ce qu'elle doit),
        puis de force si elle ne s'est pas fermée à temps. Rend « douce », « forcée » ou « déjà fermée »."""
        proc = self.apps.pop(name, None)
        if proc is None or proc.poll() is not None:
            return "déjà fermée"
        how = "douce"
        if sys.platform == "win32":  # sans /F, taskkill envoie WM_CLOSE à ses fenêtres
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T"], capture_output=True,  # noqa: S603, S607
                               timeout=10, check=False)
        else:
            proc.terminate()  # SIGTERM : l'application peut encore enregistrer
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            how = "forcée"
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        self.bus.publish(Event(f"module.{name}.app", {"running": False, "closed": how}))
        return how

    def notify(self, name: str, command: str, payload: dict[str, Any] | None = None) -> None:
        """Commande sans réponse attendue (ex. `showcase`)."""
        if name not in self.modules or not command.replace("_", "").isalnum():
            raise ValueError(f"commande invalide : {name}.{command}")
        self.bus.publish(Event(f"module.{name}.cmd.{command}", dict(payload or {})))

    # -- garde-fou : module bloqué ou muet
    def hung(self, name: str) -> str:
        """Raison pour laquelle un module lancé est considéré bloqué (vide s'il va bien)."""
        module = self.modules[name]
        if not module.running() or not module.heartbeat_at:
            return ""
        silent = self._now() - module.heartbeat_at
        if silent > HEARTBEAT_STALE_S:
            return f"ne répond plus depuis {silent:.0f} s"
        limit = module.manifest.command_timeout_s
        if module.busy and module.busy_s + silent > limit:
            return f"bloqué sur « {module.busy} » depuis {module.busy_s + silent:.0f} s (limite {limit:g} s)"
        return ""

    # -- commandes vers un module (réponse attendue sur `module.<nom>.result`)
    def command(self, name: str, command: str, payload: dict[str, Any] | None = None,
                timeout_s: float = 240.0) -> dict[str, Any]:
        """Envoie `module.<nom>.cmd.<commande>` et attend la réponse portant le même `request_id`.

        Lève `KeyError` si le module est inconnu, `RuntimeError` s'il n'est pas lancé, `TimeoutError` sans réponse.
        """
        module = self.modules[name]
        if not command.replace("_", "").isalnum():
            raise ValueError(f"commande invalide : {command!r}")
        if not module.running():
            raise RuntimeError(f"le module {name} n'est pas lancé")
        deadline = time.monotonic() + 30  # module tout juste lancé : on attend qu'il écoute le bus
        while not module.last_health and module.running() and time.monotonic() < deadline:
            time.sleep(0.1)
        if module.busy and module.busy_s >= BUSY_FAIL_FAST_S:
            # Réponse immédiate plutôt qu'une attente de 4 min qui occupe un fil du serveur (l'interface figeait).
            raise RuntimeError(f"{name} est occupé (« {module.busy} » depuis {module.busy_s:.0f} s) ; réessaie dans "
                               f"un moment. Au-delà de {module.manifest.command_timeout_s:g} s, le Hub le relance.")
        if module.pending >= MAX_PENDING:
            raise RuntimeError(f"{name} a déjà {module.pending} demandes en attente ; réessaie dans un moment")
        request_id = uuid.uuid4().hex
        done, reply = threading.Event(), {}
        self._pending[request_id] = (done, reply)
        module.pending += 1
        try:
            self.bus.publish(Event(f"module.{name}.cmd.{command}", {**(payload or {}), "request_id": request_id}))
            if not done.wait(timeout_s):
                raise TimeoutError(f"pas de réponse de {name} en {timeout_s:g} s")
            return reply
        finally:
            self._pending.pop(request_id, None)
            module.pending = max(0, module.pending - 1)

    # -- assistant
    def ask_messages(self, prompt: str, with_context: bool = True, history: list[dict[str, Any]] | None = None,
                     passages: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], str]:
        """Messages pour l'assistant : le contexte publié par les modules actifs (déjà filtré par eux), les
        extraits de la base de connaissances s'il y en a (numérotés, à citer), les derniers échanges de la
        conversation (rôles `user`/`assistant` seulement, 12 au plus, textes bornés), puis la question."""
        context = "\n".join(self.contexts[name] for name in sorted(self.contexts)
                            if self.modules.get(name) and self.modules[name].active) if with_context else ""
        if passages:
            excerpts = "\n\n".join(f"[{i}] {p['title']} — {' '.join(str(p['text']).split())[:700]}"
                                   for i, p in enumerate(passages, start=1))
            context = (f"{context}\n\n" if context else "") + (
                "Extraits de la base de connaissances locale. Appuie-toi dessus quand ils répondent à la question "
                "et cite-les par leur numéro, par exemple [1]. S'ils ne contiennent pas la réponse, dis-le "
                "simplement au lieu d'inventer.\n\n" + excerpts)
        messages: list[dict[str, Any]] = [{"role": "system", "content": context}] if context else []
        for turn in (history or [])[-12:]:
            role, content = turn.get("role"), turn.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content[:4000]})
        messages.append({"role": "user", "content": prompt})
        return messages, context

    def ask(self, prompt: str, model: str | None = None, with_context: bool = True) -> dict[str, Any]:
        """Question à l'assistant local, avec le contexte publié par les modules actifs (déjà filtré par eux)."""
        messages, context = self.ask_messages(prompt, with_context)
        answer = self.llm.chat(messages, model=model)
        return {**answer, "context_used": context}

    # -- un tour de surveillance
    def tick(self) -> dict[str, Any]:
        """Un tour : processus, déclencheurs, watchdog, alertes GPU, tâches de nuit. Retourne ce qui a changé."""
        names = self._process_names()
        self.process_watch_degraded = names is None
        started, stopped = set(), set()
        if names is not None:
            started, stopped, self._seen = names - self._seen, self._seen - names, names
            for name in sorted(started):
                self.bus.publish(Event("process.started", {"name": name}))
            for name in sorted(stopped):
                self.bus.publish(Event("process.stopped", {"name": name}))
            for module in list(self.modules.values()):
                triggers = {p.lower() for p in module.manifest.triggers.processes}
                if not triggers:
                    continue
                if triggers & names and not module.active and not module.waiting_vram:
                    self.activate(module.manifest.name, auto=True)
                elif module.auto and not triggers & names:
                    self.deactivate(module.manifest.name)
        restarted = self.fuma.tick()
        alerts = self.fuma.check_gpus(self.monitor.snapshot())
        for alert in alerts:
            self.bus.publish(Event(f"gpu.alert.{alert.kind}", alert.to_dict(), source="fuma"))
        night = self.fuma.run_night_tasks()
        return {"started": sorted(started), "stopped": sorted(stopped), "restarted": restarted,
                "alerts": [a.to_dict() for a in alerts], "night_tasks": night}

    # -- état (API et interface)
    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "os": self.os_name,
            "uptime_s": round(self._now() - self._started_at, 1),
            "gpu_backend": self.monitor.backend_name,
            "degraded": {"gpu": not self.monitor.snapshot(), "process_watch": self.process_watch_degraded},
            "inoue": self.inoue.state(),
            "fuma": self.fuma.state(),
            "scheduler": self.scheduler.state(),
            "llm": self.llm.state(),
            "knowledge": self.knowledge.state() if self.knowledge is not None else None,
            "manifest_errors": self.manifest_errors,
        }

    def modules_status(self) -> list[dict[str, Any]]:
        return [{
            "name": name, "version": m.manifest.version, "description": m.manifest.description,
            "active": m.active, "running": m.running(), "auto": m.auto, "waiting_vram": m.waiting_vram,
            "starts": m.starts, "vram_min_gb": m.manifest.vram_min_gb,
            "vram_comfort_gb": m.manifest.vram_comfort_gb, "experimental": m.manifest.experimental,
            "triggers": list(m.manifest.triggers.processes), "health": m.last_health, "error": m.last_error,
            "app": (self.app_spec(name) or {}).get("label"), "app_running": self.app_running(name),
        } for name, m in sorted(self.modules.items())]


def _manifest_name(directory: Path) -> str | None:
    try:
        return load_manifest(directory).name
    except ManifestError:
        return None


QUIET_TOPICS = (".state", ".health", ".result", ".pong")  # répétitifs ou volumineux : pas dans le journal


def setup_journal(daemon: Daemon, path: Path = REPO_ROOT / "logs" / "hub.log") -> logging.Logger:
    """Journal du Hub (`logs/hub.log`, 1 Mo × 3 fichiers, ignoré par Git) : démarrages, arrêts, erreurs, alertes
    GPU, applications. Les états des modules n'y sont pas (ils peuvent contenir des données du jeu)."""
    from logging.handlers import RotatingFileHandler

    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("aethertwin.hub")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)

    def record(event: Event) -> None:
        if event.topic.endswith(QUIET_TOPICS) or ".cmd." in event.topic:
            return
        level = logging.WARNING if (".error" in event.topic or "alert" in event.topic) else logging.INFO
        detail = json.dumps(event.payload, ensure_ascii=False, default=str)
        logger.log(level, "%s %s", event.topic, detail[:300])

    daemon.bus.subscribe("*", record)
    return logger


def port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Démon AetherTwin (I&F Core).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port de l'API (toujours sur 127.0.0.1)")
    parser.add_argument("--no-api", action="store_true", help="ne lance pas l'API HTTP")
    parser.add_argument("--tick-seconds", type=float, default=2.0)
    parser.add_argument("--open", action="store_true", help="ouvre le tableau de bord dans le navigateur")
    parser.add_argument("--activate", action="append", default=[], metavar="MODULE",
                        help="active ce module dès le démarrage (répétable)")
    args = parser.parse_args(argv)
    url = f"http://127.0.0.1:{args.port}/"

    if not args.no_api and port_in_use(args.port):
        print(f"Un démon AetherTwin (ou autre programme) écoute déjà sur le port {args.port} : {url}")
        if args.open:
            webbrowser.open(url)
        return 0

    from core.knowledge.service import KnowledgeService

    daemon = Daemon(knowledge=KnowledgeService(config.section("knowledge")))
    journal = setup_journal(daemon)
    daemon.start()
    journal.info("Hub démarré, port %s, GPU via %s", args.port, daemon.monitor.backend_name)
    print(f"AetherTwin — démon démarré. OS : {daemon.os_name}. GPU : {daemon.monitor.backend_name}. "
          f"Modules : {', '.join(sorted(daemon.modules)) or 'aucun'}.")
    for name in args.activate:
        if name in daemon.modules:
            decision = daemon.activate(name)
            print(f"  {name} : {decision.verdict.value} {decision.reason}".rstrip())
        else:
            print(f"  module inconnu : {name}")
    if not args.no_api:
        print(f"Tableau de bord : {url}   (Ctrl+C ou fermer cette fenêtre pour arrêter)")
        if args.open:
            threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(args.tick_seconds):
            daemon.tick()

    threading.Thread(target=loop, name="daemon-tick", daemon=True).start()
    try:
        if args.no_api:
            while True:
                time.sleep(1)
        else:
            import uvicorn

            from core.api import create_app

            app = create_app(daemon)
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
            app.state.shutdown = lambda: setattr(server, "should_exit", True)  # bouton « Arrêter le Hub »
            server.run()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        daemon.stop()
        journal.info("Hub arrêté")
        print("Démon arrêté.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
