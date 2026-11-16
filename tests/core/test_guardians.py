"""Gardiens Inoue (VRAM) et Fuma (stabilité, mode nocturne), en simulation : GPU factices, horloge injectée."""
from __future__ import annotations

import pytest

from core.guardians.fuma import Fuma
from core.guardians.inoue import Inoue, Verdict
from core.hardware.gpu_monitor import GpuInfo, GpuMonitor, UnknownBackend
from core.module_api import Health


class FakeBackend:
    name = "factice"

    def __init__(self, gpus: list[GpuInfo]) -> None:
        self.gpus = gpus

    def read(self) -> list[GpuInfo]:
        return self.gpus


def monitor(*total_gb: float) -> GpuMonitor:
    return GpuMonitor(FakeBackend([GpuInfo(i, f"GPU {i}", int(gb * 1024), 0) for i, gb in enumerate(total_gb)]))


# --------------------------------------------------------------------------- Inoue
def test_budget_keeps_ten_percent_margin() -> None:
    inoue = Inoue(monitor(16, 16))
    assert inoue.total_gb() == 32 and inoue.budget_gb() == pytest.approx(28.8)


def test_grants_comfort_when_it_fits_else_minimum() -> None:
    inoue = Inoue(monitor(16, 16))  # budget 28,8 Go
    first = inoue.request("scantrad", min_gb=6, comfort_gb=10)
    assert first.verdict is Verdict.GRANTED and first.granted_gb == 10
    second = inoue.request("mangastudio", min_gb=12, comfort_gb=24)
    assert second.verdict is Verdict.GRANTED and second.granted_gb == 12  # le confortable ne tient plus
    assert inoue.available_gb() == pytest.approx(6.8)
    assert inoue.request("scantrad", 6, 10).reason == "déjà attribué"


def test_refuses_what_can_never_fit_and_queues_what_does_not_fit_now() -> None:
    inoue = Inoue(monitor(16, 16))
    refused = inoue.request("trop_gros", min_gb=30)  # 30 > 28,8 : la marge n'est jamais consommée
    assert refused.verdict is Verdict.REFUSED and "marge" in refused.reason
    inoue.request("a", 20)
    assert inoue.request("b", 12).verdict is Verdict.QUEUED
    assert inoue.request("b", 12).verdict is Verdict.QUEUED and inoue.state()["queue"] == ["b"]  # pas de doublon
    served = inoue.release("a")
    assert [(name, d.verdict) for name, d in served] == [("b", Verdict.GRANTED)]
    assert inoue.state()["queue"] == [] and inoue.state()["allocations"] == {"b": 12}


def test_without_gpu_only_modules_without_vram_need_start() -> None:
    inoue = Inoue(GpuMonitor(UnknownBackend()))
    assert inoue.budget_gb() == 0 and inoue.state()["degraded"] is True
    assert inoue.request("genesis_lab", 0).verdict is Verdict.GRANTED
    assert inoue.request("scantrad", 4).verdict is Verdict.REFUSED


def test_single_large_llm_at_a_time() -> None:
    inoue = Inoue(monitor(16, 16))
    decision, unload = inoue.plan_llm_load("qwen3-27b", 17)
    assert decision.verdict is Verdict.GRANTED and unload == []
    decision, unload = inoue.plan_llm_load("qwen3-coder:30b", 19)
    assert decision.verdict is Verdict.GRANTED and unload == ["qwen3-27b"]  # à décharger avant de charger
    assert inoue.state()["loaded_llms"] == ["qwen3-coder:30b"] and inoue.allocated_gb() == 19
    assert inoue.plan_llm_load("qwen3-coder:30b", 19)[0].reason == "déjà chargé"
    assert inoue.plan_llm_load("geant", 40)[0].verdict is Verdict.REFUSED
    inoue.confirm_llm_unloaded("qwen3-coder:30b")
    assert inoue.allocated_gb() == 0 and inoue.state()["loaded_llms"] == []


def test_llm_waits_when_modules_hold_the_vram() -> None:
    inoue = Inoue(monitor(16, 16))
    inoue.request("mangastudio", 20)
    decision, _ = inoue.plan_llm_load("qwen3-27b", 17)
    assert decision.verdict is Verdict.QUEUED and inoue.state()["loaded_llms"] == []


def test_invalid_margin() -> None:
    with pytest.raises(ValueError, match="marge"):
        Inoue(monitor(16), safety_margin=1.5)


# --------------------------------------------------------------------------- Fuma
class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FlakyModule:
    def __init__(self, heal_after_restarts: int | None) -> None:
        self.heal_after, self.restarts, self.ok = heal_after_restarts, 0, False

    def health(self) -> Health:
        return Health(ok=self.ok, detail="" if self.ok else "processus arrêté")

    def restart(self) -> None:
        self.restarts += 1
        self.ok = self.heal_after is not None and self.restarts >= self.heal_after


def test_watchdog_restarts_a_crashed_module() -> None:
    clock, module = Clock(), FlakyModule(heal_after_restarts=1)
    fuma = Fuma(now=clock)
    fuma.watch("gaming_hud", module.health, module.restart)
    assert fuma.tick() == ["gaming_hud"] and module.ok
    assert fuma.tick() == []  # sain : plus rien à faire
    assert fuma.state()["modules"]["gaming_hud"]["restarts"] == 1


def test_watchdog_backs_off_then_rests_a_module_that_keeps_crashing() -> None:
    clock, module = Clock(), FlakyModule(heal_after_restarts=None)
    fuma = Fuma(now=clock, max_restarts=3, backoff_s=5)
    fuma.watch("casse", module.health, module.restart)
    assert fuma.tick() == ["casse"]
    assert fuma.tick() == []  # délai de 5 s non écoulé
    clock.t += 5
    assert fuma.tick() == ["casse"]
    clock.t += 9
    assert fuma.tick() == []  # le délai a doublé (10 s)
    clock.t += 1
    assert fuma.tick() == ["casse"]
    clock.t += 1000
    assert fuma.tick() == [] and module.restarts == 3  # 3 essais, puis repos : pas de boucle infinie
    assert fuma.state()["modules"]["casse"]["resting"] is True
    fuma.revive("casse")
    assert fuma.tick() == ["casse"]


def test_watchdog_treats_a_raising_health_check_as_a_crash() -> None:
    def broken() -> Health:
        raise RuntimeError("bus fermé")

    calls = []
    fuma = Fuma(now=Clock())
    fuma.watch("m", broken, lambda: calls.append(1))
    assert fuma.tick() == ["m"] and "bus fermé" in fuma.state()["modules"]["m"]["detail"]


def test_stable_module_gets_its_retries_back() -> None:
    clock, module = Clock(), FlakyModule(heal_after_restarts=1)
    fuma = Fuma(now=clock, stable_after_s=300)
    fuma.watch("m", module.health, module.restart)
    fuma.tick()
    fuma.tick()
    clock.t += 301
    fuma.tick()
    assert fuma.state()["modules"]["m"]["restarts"] == 0


def test_thermal_and_power_alerts() -> None:
    fuma = Fuma(temperature_limit_c=80, power_limit_w=250)
    gpus = [GpuInfo(0, "a", 16000, 0, temperature_c=86, power_w=300),
            GpuInfo(1, "b", 16000, 0, temperature_c=60, power_w=None),
            GpuInfo(2, "c", 16000, 0)]  # mesures inconnues : aucune alerte inventée
    assert [(a.kind, a.gpu_index) for a in fuma.check_gpus(gpus)] == [("temperature", 0), ("power", 0)]


@pytest.mark.parametrize(("hour", "night"), [(23, True), (2, True), (6, True), (7, False), (14, False), (22, False)])
def test_night_window_wraps_past_midnight(hour: int, night: bool) -> None:
    fuma = Fuma(now=Clock(), night_start_hour=23, night_end_hour=7, local_hour=lambda ts: hour)
    assert fuma.is_night() is night


def test_night_tasks_wait_for_the_night_and_survive_a_failure() -> None:
    hour = {"value": 14}
    done: list[str] = []

    def failing() -> None:
        raise OSError("disque plein")

    fuma = Fuma(now=Clock(), local_hour=lambda ts: hour["value"])
    fuma.schedule_night_task("ingestion", lambda: done.append("ingestion"))
    fuma.schedule_night_task("cassee", failing)
    fuma.schedule_night_task("indexation", lambda: done.append("indexation"))
    assert fuma.run_night_tasks() == [] and done == []  # en journée : rien ne tourne
    hour["value"] = 1
    assert fuma.run_night_tasks() == ["ingestion", "cassee", "indexation"] and done == ["ingestion", "indexation"]
    assert fuma.run_night_tasks() == []  # chaque tâche ne tourne qu'une fois
    assert "disque plein" in fuma.state()["night_tasks"][1]["error"]
    fuma.schedule_night_task("urgente", lambda: done.append("urgente"))
    hour["value"] = 14
    assert fuma.run_night_tasks(force=True) == ["urgente"]
