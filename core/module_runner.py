"""Lanceur d'un module dans son propre processus : `python -m core.module_runner <dossier_du_module>`.

Le daemon lance ce script, qui charge le manifeste, instancie la classe du module, la relie au bus
et fait tourner sa boucle jusqu'à l'ordre d'arrêt. Un module qui plante n'entraîne pas le Hub.

Sujets : le module reçoit `module.<nom>.cmd.*`, `hub.*`, `process.*`, `gpu.*` ;
il publie `module.<nom>.started`, `.health`, `.stopped`, `.error`.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

from core.bus import BusClient
from core.module_api import Event, ModuleBase, load_manifest

HEALTH_INTERVAL_S = 5.0


def load_module_class(entry: str) -> type[ModuleBase]:
    module_name, class_name = entry.split(":")
    cls = getattr(importlib.import_module(module_name), class_name)
    if not (isinstance(cls, type) and issubclass(cls, ModuleBase)):
        raise TypeError(f"{entry} n'hérite pas de ModuleBase")
    return cls


def run(module_dir: Path, client: BusClient | None = None, health_interval_s: float = HEALTH_INTERVAL_S) -> int:
    manifest = load_manifest(module_dir)
    prefix = f"module.{manifest.name}"
    sys.path.insert(0, str(module_dir.resolve().parent))
    client = client or BusClient.from_env(manifest.name)

    def emit(kind: str, **payload: object) -> None:
        client.publish(Event(f"{prefix}.{kind}", dict(payload), source=manifest.name))

    try:
        module = load_module_class(manifest.entry)(manifest)
        module.publish = client.publish
        client.subscribe(f"{prefix}.cmd", "hub", "process", "gpu")
        module.start()
    except Exception as exc:  # noqa: BLE001 — toute erreur de démarrage est signalée au Hub, puis le processus sort
        emit("error", stage="start", error=f"{type(exc).__name__}: {exc}")
        client.close()
        return 1

    emit("started", health=module.health().to_dict())
    next_health = time.monotonic() + health_interval_s
    code = 0
    try:
        while not client.closed:  # bus fermé = Hub arrêté : le module s'arrête aussi
            event = client.recv(timeout=0.5)
            if event is not None:
                if event.topic in (f"{prefix}.cmd.stop", "hub.shutdown"):
                    break
                try:
                    module.handle_event(event)
                except Exception as exc:  # noqa: BLE001 — un événement mal géré ne tue pas le module
                    emit("error", stage="handle_event", error=f"{type(exc).__name__}: {exc}")
            if time.monotonic() >= next_health:
                emit("health", **module.health().to_dict())
                next_health = time.monotonic() + health_interval_s
    finally:
        try:
            module.stop()
        except Exception as exc:  # noqa: BLE001
            emit("error", stage="stop", error=f"{type(exc).__name__}: {exc}")
            code = 1
        emit("stopped")
        time.sleep(0.1)  # laisse partir le dernier message
        client.close()
    return code


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage : python -m core.module_runner <dossier_du_module>", file=sys.stderr)
        sys.exit(2)
    sys.exit(run(Path(sys.argv[1])))
