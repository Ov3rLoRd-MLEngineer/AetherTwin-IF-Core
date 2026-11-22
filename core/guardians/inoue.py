"""Inoue — gardienne de l'énergie et de la VRAM.

Règles appliquées (voir CLAUDE.md, « Règles VRAM strictes ») :
  1. un seul gros modèle de langage chargé à la fois par défaut ;
  2. tout module déclare son besoin (min / confortable) ; ce qui dépasse le budget est refusé,
     ce qui ne tient pas *maintenant* est mis en file d'attente ;
  3. une marge de sécurité de 10 % de la VRAM totale n'est jamais attribuée.

Inoue tient une comptabilité des attributions ; elle ne charge ni ne décharge rien elle-même.
La place libre tient compte aussi de la VRAM **réellement mesurée** : ce que la comptabilité ignore (un jeu, le
navigateur, le contexte CUDA d'un module, un modèle d'embedding) réduit d'autant ce qu'elle accorde. Sans cette
règle, le Hub de Jérémy a atteint 29,8 Go mesurés pour un budget de 28,7 Go (22/11).
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.hardware.gpu_monitor import GpuMonitor

SAFETY_MARGIN = 0.10
MIB_PER_GB = 1024.0


class Verdict(StrEnum):
    GRANTED = "accordé"
    QUEUED = "en file"
    REFUSED = "refusé"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    granted_gb: float = 0.0
    reason: str = ""


@dataclass
class _Waiting:
    name: str
    min_gb: float
    comfort_gb: float


class Inoue:
    """Budget VRAM du Hub. Sans GPU détecté, le budget vaut 0 : seuls les modules sans besoin VRAM démarrent."""

    def __init__(self, monitor: GpuMonitor, safety_margin: float = SAFETY_MARGIN,
                 max_loaded_llms: int = 1) -> None:
        if not 0 <= safety_margin < 1:
            raise ValueError("la marge de sécurité doit être dans [0, 1[")
        self.monitor = monitor
        self.safety_margin = safety_margin
        self.max_loaded_llms = max_loaded_llms
        self._allocations: dict[str, float] = {}
        self._queue: deque[_Waiting] = deque()
        self._llms: dict[str, float] = {}  # modèle -> Go attribués
        self._lock = threading.RLock()

    # -- budget
    def total_gb(self) -> float:
        return self.monitor.total_vram_mib() / MIB_PER_GB

    def budget_gb(self) -> float:
        """VRAM attribuable : total moins la marge de sécurité."""
        return self.total_gb() * (1.0 - self.safety_margin)

    def allocated_gb(self) -> float:
        with self._lock:
            return sum(self._allocations.values())

    def measured_gb(self) -> float:
        """VRAM occupée d'après les cartes (0 sans mesure)."""
        try:
            return self.monitor.report()["vram_used_mib"] / MIB_PER_GB
        except Exception:  # noqa: BLE001 — pas de mesure : la comptabilité seule fait foi
            return 0.0

    def available_gb(self) -> float:
        """Place libre : budget moins le plus grand du prévu (attributions) et du réel (mesure)."""
        return max(0.0, self.budget_gb() - max(self.allocated_gb(), self.measured_gb()))

    # -- demandes
    def request(self, name: str, min_gb: float, comfort_gb: float | None = None) -> Decision:
        """Demande de VRAM. Accorde le confortable s'il tient, sinon le minimum, sinon met en file."""
        comfort = max(min_gb, comfort_gb if comfort_gb is not None else min_gb)
        with self._lock:
            if name in self._allocations:
                return Decision(Verdict.GRANTED, self._allocations[name], "déjà attribué")
            budget = self.budget_gb()
            if min_gb > budget + 1e-9:
                return Decision(Verdict.REFUSED, 0.0,
                                f"besoin minimal {min_gb:.1f} Go > budget {budget:.1f} Go "
                                f"(marge de sécurité de {self.safety_margin:.0%} déduite)")
            free = self.available_gb()
            if min_gb <= free + 1e-9:
                granted = comfort if comfort <= free + 1e-9 else min_gb
                self._allocations[name] = granted
                self._queue = deque(w for w in self._queue if w.name != name)
                return Decision(Verdict.GRANTED, granted,
                                "confortable" if granted == comfort else "minimum (confortable indisponible)")
            if all(w.name != name for w in self._queue):
                self._queue.append(_Waiting(name, min_gb, comfort))
            return Decision(Verdict.QUEUED, 0.0, f"{free:.1f} Go libres sur {budget:.1f}, {min_gb:.1f} demandés")

    def adopt(self, name: str, gb: float, llm: str | None = None) -> Decision:
        """Enregistre ce qui est **déjà** en VRAM (un modèle chargé par un autre programme sur le même Ollama) :
        rien à réserver, sa place est déjà dans la mesure. Sans cela, il était compté deux fois et refusé
        (essai réel du 22/11 : modèle de vision déjà chargé, « 1,8 Go libres, 6,4 demandés »)."""
        with self._lock:
            self._allocations[name] = gb
            if llm is not None:
                self._llms[llm] = gb
            return Decision(Verdict.GRANTED, gb, "déjà en mémoire")

    def release(self, name: str) -> list[tuple[str, Decision]]:
        """Libère l'attribution d'un module, puis sert la file d'attente dans l'ordre d'arrivée."""
        with self._lock:
            self._allocations.pop(name, None)
            self._llms.pop(name, None)
            self._queue = deque(w for w in self._queue if w.name != name)
            served = []
            while self._queue and self._queue[0].min_gb <= self.available_gb() + 1e-9:
                waiting = self._queue.popleft()
                served.append((waiting.name, self.request(waiting.name, waiting.min_gb, waiting.comfort_gb)))
            return served

    # -- modèles de langage
    def plan_llm_load(self, model: str, vram_gb: float) -> tuple[Decision, list[str]]:
        """Prépare le chargement d'un gros modèle de langage.

        Retourne la décision et la liste des modèles à décharger AVANT (keep_alive=0 côté Ollama).
        L'appelant décharge, puis confirme avec `confirm_llm_unloaded`.
        """
        with self._lock:
            if model in self._llms:
                return Decision(Verdict.GRANTED, self._llms[model], "déjà chargé"), []
            to_unload = list(self._llms) if len(self._llms) >= self.max_loaded_llms else []
            freed = sum(self._llms[m] for m in to_unload)
            budget = self.budget_gb()
            if vram_gb > budget + 1e-9:
                return Decision(Verdict.REFUSED, 0.0, f"modèle {vram_gb:.1f} Go > budget {budget:.1f} Go"), []
            if vram_gb > self.available_gb() + freed + 1e-9:
                return Decision(Verdict.QUEUED, 0.0, "VRAM occupée par d'autres modules"), to_unload
            for name in to_unload:
                self._allocations.pop(f"llm:{name}", None)
                del self._llms[name]
            self._llms[model] = vram_gb
            self._allocations[f"llm:{model}"] = vram_gb
            return Decision(Verdict.GRANTED, vram_gb, "attribué"), to_unload

    def confirm_llm_unloaded(self, model: str) -> list[tuple[str, Decision]]:
        with self._lock:
            self._llms.pop(model, None)
            return self.release(f"llm:{model}")

    # -- état (interface du daemon)
    def state(self) -> dict[str, Any]:
        report = self.monitor.report()
        measured = report["vram_used_mib"] / MIB_PER_GB
        with self._lock:
            return {
                "over_budget": measured > self.budget_gb() + 1e-9 and measured > 0,
                "unaccounted_gb": round(max(0.0, measured - self.allocated_gb()), 2),
                "guardian": "Inoue",
                "role": "énergie et VRAM",
                "degraded": report["degraded"],
                "gpu_backend": report["backend"],
                "total_gb": round(self.total_gb(), 2),
                "safety_margin": self.safety_margin,
                "budget_gb": round(self.budget_gb(), 2),
                "allocated_gb": round(self.allocated_gb(), 2),
                "available_gb": round(self.available_gb(), 2),
                "measured_used_gb": round(report["vram_used_mib"] / MIB_PER_GB, 2),
                "allocations": dict(self._allocations),
                "queue": [w.name for w in self._queue],
                "loaded_llms": list(self._llms),
            }
