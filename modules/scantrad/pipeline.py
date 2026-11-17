"""Chaîne de traduction d'une page : détection → OCR → effacement → traduction → réincrustation.

Chaque étape est un objet remplaçable (protocoles ci-dessous) ; la chaîne mesure le temps de chaque étape
et la VRAM occupée. Rien ne part sur Internet : l'OCR et la traduction passent par le Hub local.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass
class Bubble:
    """Une bulle : boîte (x, y, l, h) dans la page, masque plein de la bulle et masque du texte (même taille que
    la boîte, valeurs 0/255)."""

    index: int
    box: tuple[int, int, int, int]
    mask: np.ndarray
    text_mask: np.ndarray
    source: str = ""
    translation: str = ""
    area: tuple[int, int, int, int] | None = None  # zone d'écriture (page) ; None = déduite du masque
    vertical: bool = False  # texte d'origine en colonnes
    text_box: tuple[int, int, int, int] | None = None  # cadre de `text_mask` s'il diffère de `box`

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "box": list(self.box), "source": self.source, "translation": self.translation,
                "area": list(self.area) if self.area else None}


class Detector(Protocol):
    def __call__(self, page: np.ndarray) -> list[Bubble]: ...


class Ocr(Protocol):
    def __call__(self, page: np.ndarray, bubble: Bubble) -> str: ...


class Cleaner(Protocol):
    def __call__(self, page: np.ndarray, bubbles: list[Bubble]) -> np.ndarray: ...


class Translator(Protocol):
    def __call__(self, texts: list[str]) -> list[str]: ...


class Typesetter(Protocol):
    def __call__(self, page: np.ndarray, bubbles: list[Bubble]) -> np.ndarray: ...


@dataclass
class PageResult:
    image: np.ndarray
    bubbles: list[Bubble]
    metrics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {"bubbles": [b.to_dict() for b in self.bubbles], "metrics": self.metrics}


@dataclass
class Scantrad:
    detect: Detector
    ocr: Ocr | None
    clean: Cleaner
    translate: Translator | None
    typeset: Typesetter
    vram_used_mib: Callable[[], int | None] = lambda: None
    clock: Callable[[], float] = time.perf_counter
    prepare: Callable[[np.ndarray], np.ndarray] | None = None  # ex. agrandir une page trop petite

    def run(self, page: np.ndarray) -> PageResult:
        """Traduit une page (image BGR, uint8). Sans OCR ou sans traducteur : détection et effacement seuls."""
        times: dict[str, float] = {}
        vram: list[int] = []
        if self.prepare is not None:
            page = self.prepare(page)

        def stage(name: str, fn: Callable[[], Any]) -> Any:
            start = self.clock()
            result = fn()
            times[name] = round(self.clock() - start, 3)
            used = self.vram_used_mib()
            if used is not None:
                vram.append(used)
            return result

        bubbles = stage("detection", lambda: self.detect(page))
        rejected = 0
        if self.ocr is not None:
            def read_all() -> list[Bubble]:
                kept = []
                for bubble in bubbles:
                    bubble.source = self.ocr(page, bubble).strip()  # type: ignore[misc]
                    if bubble.source:  # l'OCR dit « pas de texte » : faux positif de la détection, écarté
                        kept.append(bubble)
                for index, bubble in enumerate(kept, start=1):
                    bubble.index = index
                return kept
            detected = len(bubbles)
            bubbles = stage("ocr", read_all)
            rejected = detected - len(bubbles)
        cleaned = stage("effacement", lambda: self.clean(page, bubbles))
        output = cleaned
        if self.translate is not None and any(b.source for b in bubbles):
            def translate_all() -> None:
                todo = [b for b in bubbles if b.source]
                for bubble, text in zip(todo, self.translate([b.source for b in todo]), strict=True):
                    bubble.translation = text.strip()
            stage("traduction", translate_all)
            output = stage("incrustation", lambda: self.typeset(cleaned, bubbles))
        metrics = {"seconds": times, "total_s": round(sum(times.values()), 3), "bubbles": len(bubbles),
                   "rejected_by_ocr": rejected,
                   "vram_peak_mib": max(vram) if vram else None,
                   "steps": list(times)}
        return PageResult(output, bubbles, metrics)
