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
import os
import platform
import subprocess
import sys
import threading
import time
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

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


class Daemon:
    """Registre de modules + bus + gardiens. Toutes les sources externes sont injectables (tests)."""

    def __init__(self, modules_root: Path | None = None, monitor: GpuMonitor | None = None,
                 process_names: Callable[[], set[str] | None] = psutil_process_names,
                 now: Callable[[], float] = time.time, python: str = sys.executable,
                 llm: LlmRouter | None = None) -> None:
        self.modules_root = modules_root or REPO_ROOT / "modules"
        self.monitor = monitor or GpuMonitor()
        self.bus = EventBus()
        self.inoue = Inoue(self.monitor)
        self.llm = llm or LlmRouter(self.inoue, LlmConfig.from_section(config.section("ollama")))
        self.contexts: dict[str, str] = {}  # module -> dernier contexte publié pour l'assistant
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

    def _respawn(self, name: str) -> None:
        with self._lock:
            module = self.modules[name]
            if module.active and not module.running():
                self._spawn(module)
                self.bus.publish(Event(f"module.{name}.restarted", {"starts": module.starts}, source="fuma"))

    def _health(self, name: str) -> Health:
        module = self.modules[name]
        if not module.running():
            code = module.proc.poll() if module.proc else None
            return Health(ok=False, detail=f"processus arrêté (code {code})")
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
        elif parts[2] == "state" and event.payload.get("context"):
            self.contexts[parts[1]] = str(event.payload["context"])

    # -- assistant
    def ask(self, prompt: str, model: str | None = None, with_context: bool = True) -> dict[str, Any]:
        """Question à l'assistant local, avec le contexte publié par les modules actifs (déjà filtré par eux)."""
        context = "\n".join(self.contexts[name] for name in sorted(self.contexts)
                            if self.modules.get(name) and self.modules[name].active) if with_context else ""
        messages: list[dict[str, Any]] = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})
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
            "manifest_errors": self.manifest_errors,
        }

    def modules_status(self) -> list[dict[str, Any]]:
        return [{
            "name": name, "version": m.manifest.version, "description": m.manifest.description,
            "active": m.active, "running": m.running(), "auto": m.auto, "waiting_vram": m.waiting_vram,
            "starts": m.starts, "vram_min_gb": m.manifest.vram_min_gb,
            "vram_comfort_gb": m.manifest.vram_comfort_gb, "experimental": m.manifest.experimental,
            "triggers": list(m.manifest.triggers.processes), "health": m.last_health, "error": m.last_error,
        } for name, m in sorted(self.modules.items())]


def _manifest_name(directory: Path) -> str | None:
    try:
        return load_manifest(directory).name
    except ManifestError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Démon AetherTwin (I&F Core).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port de l'API (toujours sur 127.0.0.1)")
    parser.add_argument("--no-api", action="store_true", help="ne lance pas l'API HTTP")
    parser.add_argument("--tick-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)

    daemon = Daemon()
    daemon.start()
    print(f"AetherTwin — démon démarré. OS : {daemon.os_name}. GPU : {daemon.monitor.backend_name}. "
          f"Modules : {', '.join(sorted(daemon.modules)) or 'aucun'}.")
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

            uvicorn.run(create_app(daemon), host="127.0.0.1", port=args.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        daemon.stop()
        print("Démon arrêté.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
