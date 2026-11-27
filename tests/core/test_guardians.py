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
def test_measured_vram_outside_the_books_reduces_what_is_granted() -> None:
    """Un jeu ou un contexte CUDA occupe 20 Go que la comptabilité ignore : Inoue ne donne que le reste."""
    gpus = [GpuInfo(0, "GPU 0", 16 * 1024, 12 * 1024), GpuInfo(1, "GPU 1", 16 * 1024, 8 * 1024)]
    inoue = Inoue(GpuMonitor(FakeBackend(gpus)))  # budget 28,8 Go, 20 Go mesurés, 0 attribué
    assert inoue.available_gb() == pytest.approx(8.8)
    assert inoue.request("gros", min_gb=10).verdict is Verdict.QUEUED
    assert inoue.request("petit", min_gb=4).verdict is Verdict.GRANTED
    state = inoue.state()
    assert state["unaccounted_gb"] == pytest.approx(16) and state["over_budget"] is False
    gpus[1] = GpuInfo(1, "GPU 1", 16 * 1024, 16 * 1024)  # 28 + … : au-dessus du budget
    gpus[0] = GpuInfo(0, "GPU 0", 16 * 1024, 15 * 1024)
    assert inoue.state()["over_budget"] is True and inoue.available_gb() == 0


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


def test_single_card_request_goes_to_the_card_with_room() -> None:
    """Un module PyTorch ne se répartit pas : 10 Go libres au total ne suffisent pas s'il n'y a que 5 + 5."""
    gpus = [GpuInfo(0, "GPU 0", 16 * 1024, 12 * 1024), GpuInfo(1, "GPU 1", 16 * 1024, 4 * 1024)]
    inoue = Inoue(GpuMonitor(FakeBackend(gpus)), ram_probe=None)
    granted = inoue.request("mangastudio", min_gb=6, single_card=True)
    assert granted.verdict is Verdict.GRANTED and granted.device == 1  # la carte 1 a 10,4 Go libres
    assert inoue.cards()[1]["allocated_gb"] == 6
    gpus[1] = GpuInfo(1, "GPU 1", 16 * 1024, 10 * 1024)  # le module a chargé ses poids
    queued = inoue.request("voice", min_gb=5, single_card=True)  # 2,4 + 4,4 = 6,8 libres, mais pas sur une carte
    assert queued.verdict is Verdict.QUEUED and "aucune carte" in queued.reason
    assert inoue.request("autre", min_gb=5).verdict is Verdict.GRANTED  # sans contrainte : budget global
    assert inoue.request("geant", min_gb=15, single_card=True).verdict is Verdict.REFUSED  # 15 > 14,4 par carte
    assert inoue.state()["queue_detail"][0]["reason"].startswith("VRAM")


def test_single_card_queue_is_served_when_a_card_frees_up() -> None:
    gpus = [GpuInfo(0, "GPU 0", 16 * 1024, 0), GpuInfo(1, "GPU 1", 16 * 1024, 0)]
    inoue = Inoue(GpuMonitor(FakeBackend(gpus)), ram_probe=None)
    assert inoue.request("a", 12, single_card=True).device == 0
    assert inoue.request("b", 12, single_card=True).device == 1
    assert inoue.request("c", 12, single_card=True).verdict is Verdict.QUEUED
    served = inoue.release("a")
    assert [(name, d.verdict, d.device) for name, d in served] == [("c", Verdict.GRANTED, 0)]


def test_ram_request_waits_when_memory_is_short() -> None:
    ram = {"available": 10.0}
    inoue = Inoue(monitor(16, 16), ram_probe=lambda: (32.0, ram["available"]))
    state = inoue.state()["ram"]
    assert state["reserve_gb"] == pytest.approx(3.2) and state["free_gb"] == pytest.approx(6.8)
    assert inoue.request("voice", 0, ram_gb=4).verdict is Verdict.GRANTED
    queued = inoue.request("scantrad", 0, ram_gb=4)  # 6,8 − 4 réservés = 2,8
    assert queued.verdict is Verdict.QUEUED and queued.reason.startswith("RAM")
    served = inoue.release("voice")
    assert [(name, d.verdict) for name, d in served] == [("scantrad", Verdict.GRANTED)]
    ram["available"] = 1.0
    assert inoue.request("autre", 0, ram_gb=1).verdict is Verdict.QUEUED
    assert inoue.request("sans_ram", 0).verdict is Verdict.GRANTED  # rien demandé : rien de contrôlé


def test_ram_probe_failure_does_not_block() -> None:
    def broken() -> tuple[float, float]:
        raise OSError("pas de mesure")

    inoue = Inoue(monitor(16, 16), ram_probe=broken)
    assert inoue.ram() is None and inoue.request("a", 0, ram_gb=50).verdict is Verdict.GRANTED


def test_history_keeps_the_last_decisions_with_their_reason() -> None:
    inoue = Inoue(monitor(16, 16), ram_probe=None, clock=lambda: 42.0)
    inoue.request("a", 20)
    inoue.request("b", 20)
    inoue.plan_llm_load("qwen3-27b", 17)
    history = inoue.state()["history"]
    assert [(h["name"], h["verdict"]) for h in history] == [("a", "accordé"), ("b", "en file"),
                                                           ("qwen3-27b", "en file")]
    assert history[-1]["at"] == 42.0 and "Go libres" in history[-1]["reason"]


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


def test_recurring_night_task_runs_every_night() -> None:
    hour = {"value": 2}
    runs: list[int] = []
    fuma = Fuma(now=Clock(), local_hour=lambda ts: hour["value"])
    fuma.schedule_night_task("collecte", lambda: runs.append(hour["value"]), recurring=True)
    assert fuma.run_night_tasks() == ["collecte"] and fuma.run_night_tasks() == []  # une fois par nuit
    hour["value"] = 12
    fuma.run_night_tasks()  # en journée : réarmée
    hour["value"] = 3
    assert fuma.run_night_tasks() == ["collecte"] and runs == [2, 3]
