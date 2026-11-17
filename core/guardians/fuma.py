"""Fuma — gardien de la stabilité et du mode nocturne.

- **Watchdog** : interroge la santé des modules, redémarre ceux qui sont tombés, avec un délai
  croissant et un nombre maximal d'essais (un module qui plante en boucle est mis au repos).
- **Limites thermiques** : signale un GPU qui dépasse une température ou une puissance donnée.
- **Mode nocturne** : les tâches lourdes (ingestion vectorielle, indexation) attendent la plage
  de nuit ; l'interface peut passer en thème sombre.

L'horloge est injectée : tout se teste sans attendre.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.hardware.gpu_monitor import GpuInfo
from core.module_api import Health


@dataclass
class _Watched:
    health: Callable[[], Health]
    restart: Callable[[], None]
    restarts: int = 0
    next_try_at: float = 0.0
    resting: bool = False
    last_detail: str = ""
    healthy_since: float | None = None


@dataclass(frozen=True)
class Alert:
    kind: str  # « temperature » | « power »
    gpu_index: int
    value: float
    limit: float

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "gpu_index": self.gpu_index, "value": self.value, "limit": self.limit}


@dataclass
class _NightTask:
    name: str
    run: Callable[[], Any]
    done: bool = False
    error: str = ""
    recurring: bool = False


@dataclass
class Fuma:
    """Watchdog, limites thermiques et mode nocturne du Hub."""

    now: Callable[[], float] = time.time
    max_restarts: int = 3
    backoff_s: float = 5.0
    stable_after_s: float = 300.0  # un module sain aussi longtemps retrouve tous ses essais
    temperature_limit_c: float = 85.0
    power_limit_w: float | None = None
    night_start_hour: int = 23
    night_end_hour: int = 7
    local_hour: Callable[[float], int] = lambda ts: time.localtime(ts).tm_hour
    _watched: dict[str, _Watched] = field(default_factory=dict)
    _night_tasks: list[_NightTask] = field(default_factory=list)

    # -- watchdog
    def watch(self, name: str, health: Callable[[], Health], restart: Callable[[], None]) -> None:
        self._watched[name] = _Watched(health, restart)

    def unwatch(self, name: str) -> None:
        self._watched.pop(name, None)

    def tick(self) -> list[str]:
        """Un tour de surveillance. Retourne les noms des modules redémarrés pendant ce tour."""
        restarted = []
        now = self.now()
        for name, item in self._watched.items():
            try:
                status = item.health()
            except Exception as exc:  # noqa: BLE001 — un module qui lève pendant health() est considéré tombé
                status = Health(ok=False, detail=f"{type(exc).__name__}: {exc}")
            item.last_detail = status.detail
            if status.ok:
                item.healthy_since = item.healthy_since or now
                if item.restarts and now - item.healthy_since >= self.stable_after_s:
                    item.restarts, item.resting = 0, False
                continue
            item.healthy_since = None
            if item.resting or now < item.next_try_at:
                continue
            if item.restarts >= self.max_restarts:
                item.resting = True
                continue
            item.restarts += 1
            item.next_try_at = now + self.backoff_s * (2 ** (item.restarts - 1))
            try:
                item.restart()
                restarted.append(name)
            except Exception as exc:  # noqa: BLE001 — un redémarrage raté compte comme un essai
                item.last_detail = f"redémarrage impossible : {type(exc).__name__}: {exc}"
        return restarted

    def revive(self, name: str) -> None:
        """Remet à zéro les essais d'un module mis au repos (action manuelle)."""
        if name in self._watched:
            item = self._watched[name]
            item.restarts, item.resting, item.next_try_at = 0, False, 0.0

    # -- limites thermiques
    def check_gpus(self, gpus: list[GpuInfo]) -> list[Alert]:
        alerts = []
        for gpu in gpus:
            if gpu.temperature_c is not None and gpu.temperature_c > self.temperature_limit_c:
                alerts.append(Alert("temperature", gpu.index, gpu.temperature_c, self.temperature_limit_c))
            if self.power_limit_w is not None and gpu.power_w is not None and gpu.power_w > self.power_limit_w:
                alerts.append(Alert("power", gpu.index, gpu.power_w, self.power_limit_w))
        return alerts

    # -- mode nocturne
    def is_night(self) -> bool:
        """Vrai dans la plage de nuit. Une plage qui passe minuit (23 h → 7 h) est gérée."""
        hour = self.local_hour(self.now())
        start, end = self.night_start_hour, self.night_end_hour
        if start == end:
            return False
        return start <= hour < end if start < end else hour >= start or hour < end

    def schedule_night_task(self, name: str, run: Callable[[], Any], recurring: bool = False) -> None:
        """Planifie une tâche lourde pour la nuit (ingestion vectorielle, indexation…).

        `recurring` : la tâche est réarmée en journée et tourne donc une fois **chaque** nuit.
        """
        self._night_tasks.append(_NightTask(name, run, recurring=recurring))

    def run_night_tasks(self, force: bool = False) -> list[str]:
        """Exécute les tâches en attente si c'est la nuit (ou si `force`). Retourne celles qui ont tourné."""
        if not (force or self.is_night()):
            for task in self._night_tasks:
                if task.recurring and task.done:
                    task.done = False
            return []
        ran = []
        for task in self._night_tasks:
            if task.done:
                continue
            try:
                task.run()
            except Exception as exc:  # noqa: BLE001 — une tâche ratée ne bloque pas les suivantes
                task.error = f"{type(exc).__name__}: {exc}"
            task.done = True
            ran.append(task.name)
        return ran

    # -- état (interface du daemon)
    def state(self) -> dict[str, Any]:
        return {
            "guardian": "Fuma",
            "role": "stabilité et mode nocturne",
            "night": self.is_night(),
            "night_hours": [self.night_start_hour, self.night_end_hour],
            "modules": {name: {"restarts": item.restarts, "resting": item.resting, "detail": item.last_detail}
                        for name, item in self._watched.items()},
            "night_tasks": [{"name": t.name, "done": t.done, "error": t.error} for t in self._night_tasks],
        }
