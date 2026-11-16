"""Moniteur GPU : mesure la topologie réelle au lieu de la présumer.

Backends, par ordre de préférence :
  1. `pynvml` (paquet nvidia-ml-py) ;
  2. `nvidia-smi` en sous-processus (aucune dépendance Python) ;
  3. « inconnu » : liste vide. Le Hub démarre quand même, en mode dégradé.

Aucun backend ne lève d'exception vers l'appelant. NVIDIA/CUDA uniquement (pas de backend AMD).
"""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol

SMI_FIELDS = "index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw"


@dataclass(frozen=True)
class GpuInfo:
    """État instantané d'un GPU. Une mesure indisponible vaut `None`, jamais une valeur inventée."""

    index: int
    name: str
    vram_total_mib: int
    vram_used_mib: int
    utilization_pct: float | None = None
    temperature_c: float | None = None
    power_w: float | None = None

    @property
    def vram_free_mib(self) -> int:
        return max(0, self.vram_total_mib - self.vram_used_mib)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "vram_free_mib": self.vram_free_mib}


class GpuBackend(Protocol):
    name: str

    def read(self) -> list[GpuInfo]: ...


def _number(text: str) -> float | None:
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None  # « [N/A] », « [Not Supported] »…


def parse_nvidia_smi_csv(output: str) -> list[GpuInfo]:
    """Analyse la sortie de `nvidia-smi --query-gpu=… --format=csv,noheader,nounits`."""
    gpus = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        index, total, used = _number(parts[0]), _number(parts[2]), _number(parts[3])
        if index is None or total is None:
            continue
        extra = [_number(p) for p in parts[4:7]] + [None, None, None]
        gpus.append(GpuInfo(int(index), parts[1], int(total), int(used or 0), extra[0], extra[1], extra[2]))
    return gpus


class NvidiaSmiBackend:
    """Lit `nvidia-smi` (commande fixe, sans shell)."""

    name = "nvidia-smi"

    def __init__(self, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self._runner = runner

    @staticmethod
    def usable() -> bool:
        return shutil.which("nvidia-smi") is not None

    def read(self) -> list[GpuInfo]:
        proc = self._runner(["nvidia-smi", f"--query-gpu={SMI_FIELDS}", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=10)
        return parse_nvidia_smi_csv(proc.stdout) if proc.returncode == 0 else []


class PynvmlBackend:
    """Lit NVML via `pynvml`. L'import est différé : le paquet est optionnel."""

    name = "pynvml"

    def __init__(self) -> None:
        import pynvml

        pynvml.nvmlInit()
        self._nvml = pynvml

    def _optional(self, call: Callable[[], float]) -> float | None:
        try:
            return float(call())
        except self._nvml.NVMLError:
            return None

    def read(self) -> list[GpuInfo]:
        nvml, gpus = self._nvml, []
        for index in range(nvml.nvmlDeviceGetCount()):
            handle = nvml.nvmlDeviceGetHandleByIndex(index)
            name = nvml.nvmlDeviceGetName(handle)
            memory = nvml.nvmlDeviceGetMemoryInfo(handle)
            power_mw = self._optional(lambda h=handle: nvml.nvmlDeviceGetPowerUsage(h))
            gpus.append(GpuInfo(
                index=index,
                name=name.decode() if isinstance(name, bytes) else str(name),
                vram_total_mib=int(memory.total // (1024 * 1024)),
                vram_used_mib=int(memory.used // (1024 * 1024)),
                utilization_pct=self._optional(lambda h=handle: nvml.nvmlDeviceGetUtilizationRates(h).gpu),
                temperature_c=self._optional(
                    lambda h=handle: nvml.nvmlDeviceGetTemperature(h, nvml.NVML_TEMPERATURE_GPU)),
                power_w=None if power_mw is None else power_mw / 1000.0,
            ))
        return gpus


class UnknownBackend:
    """Repli : aucun GPU NVIDIA détectable. N'empêche jamais le démarrage."""

    name = "inconnu"

    def read(self) -> list[GpuInfo]:
        return []


def detect_backend() -> GpuBackend:
    """Choisit le meilleur backend disponible, sans jamais lever d'exception."""
    try:
        return PynvmlBackend()
    except Exception:  # noqa: BLE001, S110 — paquet absent, pilote absent, pas de GPU : on essaie la suite
        pass
    if NvidiaSmiBackend.usable():
        return NvidiaSmiBackend()
    return UnknownBackend()


class GpuMonitor:
    """Point d'entrée unique pour l'état des GPU (utilisé par Inoue, Fuma et l'API du daemon)."""

    def __init__(self, backend: GpuBackend | None = None) -> None:
        self.backend: GpuBackend = backend or detect_backend()
        self.last_error = ""

    @property
    def backend_name(self) -> str:
        return self.backend.name

    def snapshot(self) -> list[GpuInfo]:
        """État de chaque GPU. En cas d'erreur de lecture : liste vide et `last_error` renseigné."""
        try:
            gpus = self.backend.read()
            self.last_error = ""
            return gpus
        except Exception as exc:  # noqa: BLE001 — un moniteur ne doit jamais faire tomber le Hub
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []

    def total_vram_mib(self) -> int:
        return sum(gpu.vram_total_mib for gpu in self.snapshot())

    def report(self) -> dict[str, Any]:
        """Résumé sérialisable (API `/gpu`, overlay OBS)."""
        gpus = self.snapshot()
        return {
            "backend": self.backend_name,
            "degraded": not gpus,
            "error": self.last_error,
            "gpu_count": len(gpus),
            "vram_total_mib": sum(g.vram_total_mib for g in gpus),
            "vram_used_mib": sum(g.vram_used_mib for g in gpus),
            "gpus": [g.to_dict() for g in gpus],
        }


if __name__ == "__main__":  # relevé manuel : python -m core.hardware.gpu_monitor
    import json

    print(json.dumps(GpuMonitor().report(), ensure_ascii=False, indent=2))
