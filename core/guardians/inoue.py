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

Deux garde-fous s'ajoutent le 27/11 :
  - **par carte** (`single_card=True`) : un module PyTorch ou ONNX ne se répartit pas sur deux cartes. Il lui faut
    sa place sur **une** carte ; Inoue choisit celle qui a le plus de place et renvoie son index (`device`).
    Les modèles de langage, qu'Ollama répartit lui-même, restent sur le budget global ;
  - **mémoire vive** (`ram_gb`) : une demande qui dépasserait la RAM libre, réserve déduite, attend aussi.
    Ollama fait transiter les poids par la RAM, et PyTorch y garde son contexte CUDA.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.hardware.gpu_monitor import GpuMonitor

SAFETY_MARGIN = 0.10
MIB_PER_GB = 1024.0
RAM_RESERVE_MIN_GB = 2.0  # jamais attribué, même sur une petite machine
HISTORY = 20


def _gb(value: float) -> str:
    """1 décimale, virgule française (les raisons sont lues dans l'Accueil)."""
    return f"{value:.1f}".replace(".", ",")


def psutil_ram() -> tuple[float, float]:
    """(total, disponible) de la mémoire vive en Go, mesurés par psutil."""
    import psutil

    mem = psutil.virtual_memory()
    return mem.total / 2**30, mem.available / 2**30


class Verdict(StrEnum):
    GRANTED = "accordé"
    QUEUED = "en file"
    REFUSED = "refusé"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    granted_gb: float = 0.0
    reason: str = ""
    device: int | None = None  # carte choisie quand la demande exige une seule carte


@dataclass
class _Waiting:
    name: str
    min_gb: float
    comfort_gb: float
    ram_gb: float = 0.0
    single_card: bool = False
    reason: str = ""
    since: float = 0.0


class Inoue:
    """Budget VRAM du Hub. Sans GPU détecté, le budget vaut 0 : seuls les modules sans besoin VRAM démarrent."""

    def __init__(self, monitor: GpuMonitor, safety_margin: float = SAFETY_MARGIN,
                 max_loaded_llms: int = 1, ram_probe: Callable[[], tuple[float, float]] | None = psutil_ram,
                 clock: Callable[[], float] = time.time) -> None:
        if not 0 <= safety_margin < 1:
            raise ValueError("la marge de sécurité doit être dans [0, 1[")
        self.monitor = monitor
        self.safety_margin = safety_margin
        self.max_loaded_llms = max_loaded_llms
        self.ram_probe = ram_probe
        self._clock = clock
        self._allocations: dict[str, float] = {}
        self._cards: dict[str, int] = {}  # attribution -> carte, pour les demandes « une seule carte »
        self._ram: dict[str, float] = {}  # attribution -> Go de RAM réservés
        self._queue: deque[_Waiting] = deque()
        self._llms: dict[str, float] = {}  # modèle -> Go attribués
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY)
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

    # -- par carte
    def cards(self) -> list[dict[str, Any]]:
        """Chaque carte : total, mesuré, attribué (demandes « une seule carte »), budget et place libre, en Go."""
        try:
            gpus = self.monitor.snapshot()
        except Exception:  # noqa: BLE001 — pas de mesure : aucune carte connue
            return []
        with self._lock:
            out = []
            for gpu in gpus:
                total, used = gpu.vram_total_mib / MIB_PER_GB, gpu.vram_used_mib / MIB_PER_GB
                allocated = sum(self._allocations.get(n, 0.0) for n, i in self._cards.items() if i == gpu.index)
                budget = total * (1.0 - self.safety_margin)
                out.append({"index": gpu.index, "name": gpu.name, "total_gb": round(total, 2),
                            "used_gb": round(used, 2), "allocated_gb": round(allocated, 2),
                            "budget_gb": round(budget, 2),
                            "free_gb": round(max(0.0, budget - max(allocated, used)), 2),
                            "utilization_pct": gpu.utilization_pct, "temperature_c": gpu.temperature_c})
            return out

    # -- mémoire vive
    def ram(self) -> dict[str, Any] | None:
        """Mémoire vive mesurée, réserve et place attribuable (Go). None si la mesure est impossible."""
        if self.ram_probe is None:
            return None
        try:
            total, available = self.ram_probe()
        except Exception:  # noqa: BLE001 — pas de mesure : la RAM n'est pas contrôlée
            return None
        reserve = max(RAM_RESERVE_MIN_GB, total * self.safety_margin)
        with self._lock:
            reserved = sum(self._ram.values())
        return {"total_gb": round(total, 2), "available_gb": round(available, 2), "reserve_gb": round(reserve, 2),
                "reserved_gb": round(reserved, 2),
                "free_gb": round(max(0.0, available - reserve - reserved), 2)}

    def _log(self, name: str, decision: Decision) -> Decision:
        self._history.append({"at": self._clock(), "name": name, "verdict": decision.verdict.value,
                              "granted_gb": round(decision.granted_gb, 2), "reason": decision.reason,
                              "device": decision.device})
        return decision

    # -- demandes
    def request(self, name: str, min_gb: float, comfort_gb: float | None = None, *, ram_gb: float = 0.0,
                single_card: bool = False) -> Decision:
        """Demande de VRAM (et de RAM). Accorde le confortable s'il tient, sinon le minimum, sinon met en file.

        `single_card` : la demande doit tenir sur une seule carte (module PyTorch ou ONNX). La décision porte
        alors l'index de la carte choisie, celle qui a le plus de place.
        """
        comfort = max(min_gb, comfort_gb if comfort_gb is not None else min_gb)
        with self._lock:
            if name in self._allocations:
                return Decision(Verdict.GRANTED, self._allocations[name], "déjà attribué", self._cards.get(name))
            budget = self.budget_gb()
            if min_gb > budget + 1e-9:
                return self._log(name, Decision(Verdict.REFUSED, 0.0,
                                                f"besoin minimal {_gb(min_gb)} Go > budget {_gb(budget)} Go "
                                                f"(marge de sécurité de {self.safety_margin:.0%} déduite)"))
            cards = self.cards() if single_card and min_gb > 0 else []
            if cards and min_gb > max(c["budget_gb"] for c in cards) + 1e-9:
                return self._log(name, Decision(Verdict.REFUSED, 0.0,
                                                f"besoin minimal {_gb(min_gb)} Go > plus grande carte "
                                                f"({_gb(max(c['budget_gb'] for c in cards))} Go, marge déduite)"))
            free = self.available_gb()
            reason = ""
            device = None
            if min_gb > free + 1e-9:
                reason = f"VRAM : {_gb(free)} Go libres sur {_gb(budget)}, {_gb(min_gb)} demandés"
            elif cards:
                best = max(cards, key=lambda c: c["free_gb"])
                free = min(free, best["free_gb"])
                device = best["index"]
                if min_gb > free + 1e-9:
                    detail = ", ".join(f"carte {c['index']} : {_gb(c['free_gb'])}" for c in cards)
                    reason = f"VRAM : aucune carte n'a {_gb(min_gb)} Go libres d'un seul tenant ({detail})"
            ram = self.ram() if ram_gb > 0 else None
            if not reason and ram is not None and ram_gb > ram["free_gb"] + 1e-9:
                reason = (f"RAM : {_gb(ram['free_gb'])} Go attribuables ({_gb(ram['available_gb'])} libres, "
                          f"réserve {_gb(ram['reserve_gb'])}), {_gb(ram_gb)} demandés")
            if not reason:
                granted = comfort if comfort <= free + 1e-9 else min_gb
                self._allocations[name] = granted
                if device is not None:
                    self._cards[name] = device
                if ram_gb > 0:
                    self._ram[name] = ram_gb
                self._queue = deque(w for w in self._queue if w.name != name)
                return self._log(name, Decision(Verdict.GRANTED, granted,
                                                "confortable" if granted == comfort
                                                else "minimum (confortable indisponible)", device))
            waiting = next((w for w in self._queue if w.name == name), None)
            if waiting is None:
                self._queue.append(_Waiting(name, min_gb, comfort, ram_gb, single_card, reason, self._clock()))
                return self._log(name, Decision(Verdict.QUEUED, 0.0, reason))
            waiting.reason = reason
            return Decision(Verdict.QUEUED, 0.0, reason)

    def adopt(self, name: str, gb: float, llm: str | None = None) -> Decision:
        """Enregistre ce qui est **déjà** en VRAM (un modèle chargé par un autre programme sur le même Ollama) :
        rien à réserver, sa place est déjà dans la mesure. Sans cela, il était compté deux fois et refusé
        (essai réel du 22/11 : modèle de vision déjà chargé, « 1,8 Go libres, 6,4 demandés »)."""
        with self._lock:
            self._allocations[name] = gb
            if llm is not None:
                self._llms[llm] = gb
            return self._log(name, Decision(Verdict.GRANTED, gb, "déjà en mémoire"))

    def release(self, name: str) -> list[tuple[str, Decision]]:
        """Libère l'attribution d'un module, puis sert la file d'attente dans l'ordre d'arrivée."""
        with self._lock:
            self._allocations.pop(name, None)
            self._cards.pop(name, None)
            self._ram.pop(name, None)
            self._llms.pop(name, None)
            self._queue = deque(w for w in self._queue if w.name != name)
            served = []
            while self._queue and self._queue[0].min_gb <= self.available_gb() + 1e-9:
                waiting = self._queue[0]
                decision = self.request(waiting.name, waiting.min_gb, waiting.comfort_gb, ram_gb=waiting.ram_gb,
                                        single_card=waiting.single_card)
                if decision.verdict is not Verdict.GRANTED:
                    break  # la tête de file attend encore (une seule carte, ou la RAM) : l'ordre est gardé
                served.append((waiting.name, decision))
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
                return self._log(model, Decision(Verdict.REFUSED, 0.0,
                                                 f"modèle {_gb(vram_gb)} Go > budget {_gb(budget)} Go")), []
            free = self.available_gb() + freed
            if vram_gb > free + 1e-9:
                return self._log(model, Decision(
                    Verdict.QUEUED, 0.0,
                    f"VRAM occupée par d'autres modules ({_gb(free)} Go libres, {_gb(vram_gb)} demandés)")), to_unload
            for name in to_unload:
                self._allocations.pop(f"llm:{name}", None)
                del self._llms[name]
            self._llms[model] = vram_gb
            self._allocations[f"llm:{model}"] = vram_gb
            return self._log(model, Decision(Verdict.GRANTED, vram_gb, "attribué")), to_unload

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
                "queue_detail": [{"name": w.name, "min_gb": w.min_gb, "ram_gb": w.ram_gb, "reason": w.reason,
                                  "since": w.since} for w in self._queue],
                "loaded_llms": list(self._llms),
                "cards": self.cards(),
                "ram": self.ram(),
                "history": list(self._history),
            }
