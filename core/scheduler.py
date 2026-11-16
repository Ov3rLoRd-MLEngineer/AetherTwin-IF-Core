"""File d'attente GPU unique pour les tâches de vision et de diffusion (scantrad, mangastudio).

Une seule tâche à la fois. Avant chaque tâche, l'ordonnanceur demande la VRAM à Inoue ;
il la rend dès que la tâche se termine, qu'elle réussisse ou non.
"""
from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from core.guardians.inoue import Inoue, Verdict


class VramRefused(RuntimeError):
    """La tâche demande plus de VRAM que le budget, ou n'a pas obtenu de place à temps."""


@dataclass
class _Job:
    name: str
    vram_gb: float
    fn: Callable[[], Any]
    future: Future[Any]


class GpuScheduler:
    """Exécute les tâches GPU une par une, dans l'ordre d'arrivée."""

    def __init__(self, inoue: Inoue, wait_timeout_s: float = 600.0, poll_s: float = 0.2) -> None:
        self.inoue = inoue
        self.wait_timeout_s = wait_timeout_s
        self.poll_s = poll_s
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._current: str | None = None
        self._count = 0
        self._worker = threading.Thread(target=self._loop, name="gpu-scheduler", daemon=True)
        self._worker.start()

    def submit(self, name: str, vram_gb: float, fn: Callable[[], Any]) -> Future[Any]:
        """Met une tâche en file. Le résultat (ou l'erreur) arrive par le `Future` retourné."""
        future: Future[Any] = Future()
        self._jobs.put(_Job(name, vram_gb, fn, future))
        return future

    def state(self) -> dict[str, Any]:
        return {"running": self._current, "waiting": self._jobs.qsize(), "done": self._count}

    def shutdown(self) -> None:
        self._jobs.put(None)
        self._worker.join(timeout=5)

    def _acquire(self, key: str, vram_gb: float) -> None:
        deadline = time.monotonic() + self.wait_timeout_s
        while True:
            decision = self.inoue.request(key, vram_gb)
            if decision.verdict is Verdict.GRANTED:
                return
            if decision.verdict is Verdict.REFUSED:
                raise VramRefused(decision.reason)
            if time.monotonic() >= deadline:
                self.inoue.release(key)  # retire la demande de la file d'Inoue
                raise VramRefused(f"pas de VRAM libre après {self.wait_timeout_s:.0f} s ({decision.reason})")
            time.sleep(self.poll_s)

    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            if not job.future.set_running_or_notify_cancel():
                continue
            self._count += 1
            key = f"job:{job.name}#{self._count}"
            try:
                self._acquire(key, job.vram_gb)
            except VramRefused as exc:
                job.future.set_exception(exc)
                continue
            self._current = job.name
            try:
                job.future.set_result(job.fn())
            except Exception as exc:  # noqa: BLE001 — l'erreur de la tâche est rendue à l'appelant
                job.future.set_exception(exc)
            finally:
                self._current = None
                self.inoue.release(key)
