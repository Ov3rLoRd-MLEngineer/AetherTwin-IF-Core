"""Démon : modules dans de vrais processus séparés, déclencheurs, watchdog, mode dégradé, API locale."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.daemon import Daemon
from core.guardians.inoue import Verdict
from core.hardware.gpu_monitor import GpuInfo, GpuMonitor, UnknownBackend
from core.llm_router import LlmError, LlmRouter
from core.module_api import Event

DEMO_MODULE = '''
from core.module_api import Event, Health, ModuleBase


class Demo(ModuleBase):
    def start(self):
        self.count = 0

    def stop(self):
        pass

    def health(self):
        return Health(ok=True, degraded=True, detail="mode dégradé : pas de jeu")

    def handle_event(self, event):
        if event.topic == "module.demo.cmd.ping":
            self.count += 1
            self.publish(Event("module.demo.pong", {"count": self.count}, source="demo"))
        elif event.topic == "module.demo.cmd.echo":
            self.publish(Event("module.demo.result", {"request_id": event.payload.get("request_id"), "ok": True,
                                                      "result": event.payload.get("text")}, source="demo"))
        elif event.topic == "module.demo.cmd.crash":
            import os
            os._exit(7)
'''


def make_modules(root: Path, vram_min_gb: float = 0, extra: dict | None = None) -> Path:
    (root / "demo").mkdir(parents=True)
    (root / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo" / "main.py").write_text(DEMO_MODULE, encoding="utf-8")
    manifest = {"name": "demo", "version": "0.0.1", "description": "Module de test", "entry": "demo.main:Demo",
                "vram_min_gb": vram_min_gb, "vram_comfort_gb": vram_min_gb,
                "triggers": {"processes": ["obs64.exe"]}, **(extra or {})}
    (root / "demo" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "casse").mkdir()
    (root / "casse" / "manifest.json").write_text("{ invalide", encoding="utf-8")
    return root


def ollama_stopped(method: str, url: str, body: dict | None, timeout_s: float) -> dict:
    """Transport factice : Ollama est arrêté. Les tests du démon ne dépendent d'aucun serveur de modèles."""
    raise LlmError("Ollama injoignable (arrêté pour le test)")


class Processes:
    def __init__(self) -> None:
        self.names: set[str] | None = {"explorer.exe"}

    def __call__(self) -> set[str] | None:
        return None if self.names is None else set(self.names)


class OneGpu:
    name = "factice"

    def read(self) -> list[GpuInfo]:
        return [GpuInfo(0, "GPU", 16 * 1024, 0, temperature_c=91.0)]


def wait_for(predicate, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def hub(tmp_path: Path):
    processes = Processes()
    daemon = Daemon(make_modules(tmp_path / "modules"), monitor=GpuMonitor(UnknownBackend()),
                    process_names=processes, llm=LlmRouter(transport=ollama_stopped))
    daemon.fuma.backoff_s = 0.0
    daemon.processes = processes  # type: ignore[attr-defined]
    daemon.topics = []  # type: ignore[attr-defined]
    daemon.bus.subscribe("*", lambda e: daemon.topics.append(e.topic))  # type: ignore[attr-defined]
    daemon.start()
    yield daemon
    daemon.stop()


def test_starts_without_gpu_and_reports_broken_manifest(hub: Daemon) -> None:
    status = hub.status()
    assert status["ok"] and status["gpu_backend"] == "inconnu" and status["degraded"]["gpu"] is True
    assert list(hub.modules) == ["demo"] and "casse" in status["manifest_errors"]
    assert status["inoue"]["guardian"] == "Inoue" and status["fuma"]["guardian"] == "Fuma"
    assert "hub.started" in hub.topics


def test_module_runs_in_a_separate_process_and_talks_over_the_bus(hub: Daemon) -> None:
    assert hub.activate("demo").verdict is Verdict.GRANTED
    assert wait_for(lambda: "module.demo.started" in hub.topics), "le module n'a pas démarré"
    module = hub.modules["demo"]
    import os

    assert module.running() and module.proc is not None and module.proc.pid != os.getpid()
    assert module.last_health == {"ok": True, "degraded": True, "detail": "mode dégradé : pas de jeu"}
    hub.bus.publish(Event("module.demo.cmd.ping"))
    assert wait_for(lambda: "module.demo.pong" in hub.topics)
    assert hub.activate("demo").reason == "déjà actif" and module.starts == 1

    hub.deactivate("demo")
    assert not module.running() and not module.active and module.proc.returncode == 0  # arrêt propre
    assert "module.demo.stopped" in hub.topics
    assert hub.modules_status()[0]["active"] is False


def test_fuma_restarts_a_crashed_module(hub: Daemon) -> None:
    hub.activate("demo")
    assert wait_for(lambda: "module.demo.started" in hub.topics)
    hub.bus.publish(Event("module.demo.cmd.crash"))
    assert wait_for(lambda: not hub.modules["demo"].running())
    assert hub.modules["demo"].proc.returncode == 7
    assert hub.tick()["restarted"] == ["demo"]
    assert wait_for(lambda: hub.topics.count("module.demo.started") == 2), "le module n'a pas été relancé"
    assert hub.modules["demo"].starts == 2 and "module.demo.restarted" in hub.topics


def test_trigger_process_activates_then_deactivates_the_module(hub: Daemon) -> None:
    assert hub.tick()["started"] == [] and not hub.modules["demo"].active
    hub.processes.names.add("obs64.exe")
    changes = hub.tick()
    assert changes["started"] == ["obs64.exe"] and "process.started" in hub.topics
    assert hub.modules["demo"].active and hub.modules["demo"].auto
    assert wait_for(lambda: "module.demo.started" in hub.topics)
    hub.processes.names.discard("obs64.exe")
    assert hub.tick()["stopped"] == ["obs64.exe"]
    assert not hub.modules["demo"].active and not hub.modules["demo"].running()


def test_manually_activated_module_survives_the_trigger_going_away(hub: Daemon) -> None:
    hub.activate("demo")
    hub.processes.names.add("obs64.exe")
    hub.tick()
    hub.processes.names.discard("obs64.exe")
    hub.tick()
    assert hub.modules["demo"].active


def test_process_watch_degrades_without_psutil(hub: Daemon) -> None:
    hub.processes.names = None
    assert hub.tick()["started"] == [] and hub.status()["degraded"]["process_watch"] is True


def test_module_needing_vram_is_refused_without_gpu(tmp_path: Path) -> None:
    daemon = Daemon(make_modules(tmp_path / "modules", vram_min_gb=6), monitor=GpuMonitor(UnknownBackend()),
                    process_names=lambda: set())
    daemon.start()
    try:
        decision = daemon.activate("demo")
        assert decision.verdict is Verdict.REFUSED and not daemon.modules["demo"].active
        assert daemon.modules["demo"].proc is None  # aucun processus lancé
    finally:
        daemon.stop()


def test_overheating_gpu_raises_an_alert_on_the_bus(tmp_path: Path) -> None:
    daemon = Daemon(make_modules(tmp_path / "modules"), monitor=GpuMonitor(OneGpu()), process_names=lambda: set())
    topics: list[str] = []
    daemon.bus.subscribe("gpu", lambda e: topics.append(e.topic))
    daemon.start()
    try:
        assert daemon.tick()["alerts"][0]["kind"] == "temperature" and topics == ["gpu.alert.temperature"]
    finally:
        daemon.stop()


def test_night_task_runs_from_the_tick(hub: Daemon) -> None:
    done: list[int] = []
    hub.fuma.local_hour = lambda ts: 2
    hub.fuma.schedule_night_task("ingestion", lambda: done.append(1))
    assert hub.tick()["night_tasks"] == ["ingestion"] and done == [1]


# --------------------------------------------------------------------------- API HTTP locale
def test_local_api(hub: Daemon) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from core.api import create_app

    client = TestClient(create_app(hub))
    assert client.get("/health").json()["inoue"]["guardian"] == "Inoue"
    assert client.get("/gpu").json() == {"backend": "inconnu", "degraded": True, "error": "", "gpu_count": 0,
                                         "vram_total_mib": 0, "vram_used_mib": 0, "gpus": []}
    assert [m["name"] for m in client.get("/modules").json()] == ["demo"]
    assert client.post("/modules/demo/activate").json()["verdict"] == "accordé"
    assert wait_for(lambda: "module.demo.started" in hub.topics)
    assert client.get("/modules").json()[0]["running"] is True
    assert "module.demo.started" in [e["topic"] for e in client.get("/events").json()]
    reply = client.post("/modules/demo/command/echo", json={"text": "bonjour"}).json()
    assert reply["ok"] is True and reply["result"] == "bonjour"  # réponse rattachée par request_id
    assert client.post("/modules/demo/command/a.b", json={}).status_code == 400  # nom de commande filtré
    assert client.post("/modules/demo/deactivate").json() == {"name": "demo", "active": False}
    stopped = client.post("/modules/demo/command/echo", json={})
    assert stopped.status_code == 409 and "pas lancé" in stopped.json()["detail"]
    assert client.post("/modules/inconnu/activate").status_code == 404
    answer = client.post("/ask", json={"prompt": "bonjour"})
    assert answer.status_code == 503 and "modèle" in answer.json()["detail"]  # erreur claire, pas de plantage
    assert client.get("/health").json()["llm"]["reachable"] is False  # mode dégradé visible dans /health
