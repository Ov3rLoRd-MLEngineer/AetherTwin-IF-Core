"""Moniteur GPU : analyse de nvidia-smi, mode dégradé, et lecture réelle si un GPU NVIDIA est présent."""
from __future__ import annotations

import subprocess

import pytest

from core.hardware import gpu_monitor as gm

SMI_OUTPUT = (
    "0, NVIDIA GeForce RTX 5080, 16303, 1817, 12, 41, 38.50\n"
    "1, NVIDIA GeForce RTX 5060 Ti, 16311, 0, 0, 33, [N/A]\n"
    "ligne illisible\n"
)


class FailingBackend:
    name = "cassé"

    def read(self) -> list[gm.GpuInfo]:
        raise RuntimeError("pilote absent")


def test_parse_nvidia_smi_csv() -> None:
    gpus = gm.parse_nvidia_smi_csv(SMI_OUTPUT)
    assert [g.name for g in gpus] == ["NVIDIA GeForce RTX 5080", "NVIDIA GeForce RTX 5060 Ti"]
    assert gpus[0].vram_total_mib == 16303 and gpus[0].vram_free_mib == 16303 - 1817
    assert gpus[0].temperature_c == 41 and gpus[0].power_w == 38.5
    assert gpus[1].power_w is None  # « [N/A] » reste inconnu, jamais remplacé par 0


def test_nvidia_smi_backend_uses_a_fixed_argument_list() -> None:
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, SMI_OUTPUT, "")

    gpus = gm.NvidiaSmiBackend(runner).read()
    assert len(gpus) == 2 and seen["cmd"][0] == "nvidia-smi" and isinstance(seen["cmd"], list)


def test_nvidia_smi_failure_gives_empty_list() -> None:
    backend = gm.NvidiaSmiBackend(lambda cmd, **kw: subprocess.CompletedProcess(cmd, 9, "", "erreur"))
    assert backend.read() == []


def test_degraded_mode_without_gpu_never_raises() -> None:
    monitor = gm.GpuMonitor(gm.UnknownBackend())
    report = monitor.report()
    assert monitor.snapshot() == [] and monitor.total_vram_mib() == 0
    assert report["backend"] == "inconnu" and report["degraded"] is True and report["gpu_count"] == 0


def test_backend_error_is_caught_and_reported() -> None:
    monitor = gm.GpuMonitor(FailingBackend())
    assert monitor.snapshot() == []
    assert "pilote absent" in monitor.last_error


def test_detect_backend_falls_back_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_pynvml() -> None:
        raise ImportError("pynvml absent")

    monkeypatch.setattr(gm, "PynvmlBackend", no_pynvml)
    monkeypatch.setattr(gm.NvidiaSmiBackend, "usable", staticmethod(lambda: False))
    assert gm.detect_backend().name == "inconnu"
    monkeypatch.setattr(gm.NvidiaSmiBackend, "usable", staticmethod(lambda: True))
    assert gm.detect_backend().name == "nvidia-smi"


def test_real_gpus_if_present() -> None:
    """Lecture réelle. Ignoré sur une machine sans GPU NVIDIA (CI) : le mode dégradé est testé plus haut."""
    monitor = gm.GpuMonitor()
    gpus = monitor.snapshot()
    if not gpus:
        pytest.skip(f"aucun GPU NVIDIA détecté (backend {monitor.backend_name})")
    for gpu in gpus:
        assert gpu.name and gpu.vram_total_mib > 0 and 0 <= gpu.vram_used_mib <= gpu.vram_total_mib
    if gm.NvidiaSmiBackend.usable() and monitor.backend_name == "pynvml":
        smi = gm.NvidiaSmiBackend().read()  # les deux backends doivent voir la même topologie
        assert [(g.name, g.vram_total_mib) for g in smi] == [(g.name, g.vram_total_mib) for g in gpus]
