"""Bus d'événements (dont un vrai second processus) et file d'attente GPU."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from core.bus import BusClient, EventBus
from core.guardians.inoue import Inoue
from core.hardware.gpu_monitor import GpuInfo, GpuMonitor
from core.module_api import Event
from core.scheduler import GpuScheduler, VramRefused

REPO_ROOT = Path(__file__).resolve().parents[2]

ECHO_CLIENT = """
import sys
from core.bus import BusClient
from core.module_api import Event
client = BusClient.from_env("enfant")
client.subscribe("demo.ping")
client.publish(Event("demo.ready", source="enfant"))
event = client.recv(timeout=20)
client.publish(Event("demo.pong", {"echo": event.payload["text"].upper()}, source="enfant"))
import time; time.sleep(0.3)
"""


@pytest.fixture
def bus():
    hub = EventBus()
    hub.start()
    yield hub
    hub.stop()


def wait_for(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_bus_only_listens_on_loopback() -> None:
    with pytest.raises(ValueError, match="boucle locale"):
        EventBus(host="0.0.0.0")  # noqa: S104 — c'est justement ce qui doit être refusé


def test_local_subscribers_and_history(bus: EventBus) -> None:
    seen: list[str] = []
    bus.subscribe("gpu", lambda e: seen.append(e.topic))
    bus.subscribe("*", lambda e: 1 / 0)  # un abonné défaillant ne bloque pas les autres
    bus.publish(Event("gpu.alert.temperature"))
    bus.publish(Event("process.started"))
    assert seen == ["gpu.alert.temperature"]
    assert [e.topic for e in bus.history] == ["gpu.alert.temperature", "process.started"]


def test_client_receives_only_subscribed_topics(bus: EventBus) -> None:
    client = BusClient(bus.address, bus.authkey, "test")
    client.subscribe("module.demo.cmd", "hub")
    bus.publish(Event("module.autre.cmd.stop"))
    bus.publish(Event("module.demo.cmd.stop", {"why": "test"}))
    event = client.recv(timeout=5)
    assert event is not None and event.topic == "module.demo.cmd.stop" and event.payload == {"why": "test"}
    assert client.recv(timeout=0.2) is None
    assert wait_for(lambda: bus.clients() == ["test"])
    client.close()
    assert wait_for(lambda: bus.clients() == [])


def test_wrong_key_is_rejected(bus: EventBus) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011 — AuthenticationError ou connexion coupée selon la plateforme
        BusClient(bus.address, b"mauvaise-cle", "intrus")
    assert bus.clients() == []
    good = BusClient(bus.address, bus.authkey, "ok")  # le bus continue de servir après un refus
    good.subscribe("x")
    good.close()


def test_event_crosses_process_boundary(bus: EventBus, tmp_path: Path) -> None:
    received: list[Event] = []
    bus.subscribe("demo", received.append)
    script = tmp_path / "echo_client.py"
    script.write_text(ECHO_CLIENT, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), **bus.child_env())
    proc = subprocess.Popen([sys.executable, str(script)], env=env, cwd=str(REPO_ROOT))
    try:
        assert wait_for(lambda: any(e.topic == "demo.ready" for e in received)), "le processus enfant n'a pas rejoint"
        bus.publish(Event("demo.ping", {"text": "bonjour"}))
        assert wait_for(lambda: any(e.topic == "demo.pong" for e in received))
        pong = next(e for e in received if e.topic == "demo.pong")
        assert pong.payload == {"echo": "BONJOUR"} and pong.source == "enfant"
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_client_notices_when_the_hub_stops() -> None:
    hub = EventBus()
    hub.start()
    client = BusClient(hub.address, hub.authkey, "c")
    client.subscribe("x")
    hub.stop()
    assert wait_for(lambda: client.closed)


# --------------------------------------------------------------------------- ordonnanceur GPU
class FakeBackend:
    name = "factice"

    def read(self) -> list[GpuInfo]:
        return [GpuInfo(0, "GPU", 20 * 1024, 0)]  # budget : 18 Go


@pytest.fixture
def scheduler():
    sched = GpuScheduler(Inoue(GpuMonitor(FakeBackend())), wait_timeout_s=0.6, poll_s=0.02)
    yield sched
    sched.shutdown()


def test_jobs_run_one_at_a_time_in_order_and_release_vram(scheduler: GpuScheduler) -> None:
    order: list[str] = []
    running = {"now": 0, "max": 0}

    def job(name: str) -> str:
        running["now"] += 1
        running["max"] = max(running["max"], running["now"])
        time.sleep(0.05)
        order.append(name)
        running["now"] -= 1
        return name

    futures = [scheduler.submit(n, 12, lambda n=n: job(n)) for n in ("a", "b", "c")]
    assert [f.result(timeout=10) for f in futures] == ["a", "b", "c"]
    assert order == ["a", "b", "c"] and running["max"] == 1
    assert scheduler.inoue.allocated_gb() == 0 and scheduler.state()["done"] == 3


def test_job_error_is_returned_and_vram_is_released(scheduler: GpuScheduler) -> None:
    def boom() -> None:
        raise ValueError("image illisible")

    with pytest.raises(ValueError, match="illisible"):
        scheduler.submit("casse", 4, boom).result(timeout=10)
    assert scheduler.inoue.allocated_gb() == 0
    assert scheduler.submit("suivant", 4, lambda: 42).result(timeout=10) == 42


def test_job_larger_than_budget_is_refused(scheduler: GpuScheduler) -> None:
    with pytest.raises(VramRefused):
        scheduler.submit("geant", 19, lambda: None).result(timeout=10)


def test_job_waits_for_vram_held_by_a_module(scheduler: GpuScheduler) -> None:
    scheduler.inoue.request("mangastudio", 12)
    future = scheduler.submit("scan", 10, lambda: "fait")
    threading.Timer(0.15, lambda: scheduler.inoue.release("mangastudio")).start()
    assert future.result(timeout=10) == "fait"


def test_job_gives_up_after_the_wait_timeout(scheduler: GpuScheduler) -> None:
    scheduler.inoue.request("mangastudio", 12)
    with pytest.raises(VramRefused, match="pas de VRAM libre"):
        scheduler.submit("scan", 10, lambda: None).result(timeout=10)
    assert scheduler.inoue.state()["queue"] == []
