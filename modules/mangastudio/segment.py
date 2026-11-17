"""Segmentation des mains et des pieds : HandSegNet et FootSegNet (modèles de Jérémy, Apache 2.0).

Les deux modèles sont des SAM ViT-B (Meta) dont seul le décodeur de masque a été affiné sur des images
d'anime. Ils prennent **une boîte** (x1, y1, x2, y2) autour d'**une** main ou d'**un** pied et rendent un
masque binaire. Deux mains = deux appels, masques réunis (`np.maximum`).

Dépendances lourdes **facultatives** : `torch`, `segment-anything`, `safetensors`, et les poids
(`*_vit_b_best.safetensors`, 375 Mo chacun, chemins dans `config/local.yaml`, section `mangastudio`).
S'il manque quelque chose, `make_segmenter` rend un segmenteur de **simulation** (GrabCut d'OpenCV dans la
boîte), toujours signalé comme tel : ses masques ne disent rien de la qualité de HandSegNet/FootSegNet.
"""
from __future__ import annotations

import importlib.util
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

TARGETS = {"hand": "HandSegNet", "foot": "FootSegNet"}
WEIGHT_KEYS = {"hand": "handsegnet_weights", "foot": "footsegnet_weights"}
DEFAULT_WEIGHTS = {"hand": "models/mangastudio/handsegnet_vit_b_best.safetensors",
                   "foot": "models/mangastudio/footsegnet_vit_b_best.safetensors"}
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Segmentation:
    mask: np.ndarray  # uint8 0/255, taille de l'image
    backend: str      # « HandSegNet », « FootSegNet » ou « simulation (GrabCut) »
    simulated: bool
    seconds: float
    score: float | None = None


def missing_dependencies() -> list[str]:
    return [name for name in ("torch", "segment_anything", "safetensors") if importlib.util.find_spec(name) is None]


def weights_path(target: str, settings: dict[str, Any]) -> Path:
    raw = str(settings.get(WEIGHT_KEYS[target]) or DEFAULT_WEIGHTS[target])
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def check_box(box: Any, width: int, height: int) -> tuple[int, int, int, int]:
    """Valide et borne une boîte (x1, y1, x2, y2) à l'image. Lève `ValueError` si elle est vide ou mal formée."""
    if not isinstance(box, list | tuple) or len(box) != 4:
        raise ValueError("boîte attendue : [x1, y1, x2, y2]")
    x1, y1, x2, y2 = (int(round(float(v))) for v in box)
    x1, x2 = sorted((max(0, min(width - 1, x1)), max(0, min(width - 1, x2))))
    y1, y2 = sorted((max(0, min(height - 1, y1)), max(0, min(height - 1, y2))))
    if x2 - x1 < 4 or y2 - y1 < 4:
        raise ValueError("boîte trop petite (4 pixels au moins de côté)")
    return x1, y1, x2, y2


def grabcut_segment(image_rgb: np.ndarray, box: tuple[int, int, int, int], iterations: int = 4) -> np.ndarray:
    """Simulation : GrabCut d'OpenCV initialisé par la boîte. Déterministe, sans GPU."""
    x1, y1, x2, y2 = box
    mask = np.zeros(image_rgb.shape[:2], np.uint8)
    background, foreground = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.setRNGSeed(0)
    cv2.grabCut(cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR), mask, (x1, y1, x2 - x1, y2 - y1), background,
                foreground, iterations, cv2.GC_INIT_WITH_RECT)
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


class SamSegmenter:
    """HandSegNet / FootSegNet : SAM ViT-B chargé avec les poids affinés. Chargé à la première demande."""

    def __init__(self, target: str, weights: Path, device: str = "") -> None:
        self.target, self.weights = target, weights
        self.device = device
        self._predictor: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        import torch
        from segment_anything import SamPredictor, sam_model_registry

        if self.weights.suffix == ".safetensors":
            from safetensors.torch import load_file

            state = load_file(str(self.weights))
        else:
            state = torch.load(str(self.weights), map_location="cpu", weights_only=True)
        sam = sam_model_registry["vit_b"](checkpoint=None)
        sam.load_state_dict(state)
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        sam.to(device).eval()
        return SamPredictor(sam)

    def unload(self) -> None:
        with self._lock:
            self._predictor = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def __call__(self, image_rgb: np.ndarray, box: tuple[int, int, int, int]) -> Segmentation:
        start = time.perf_counter()
        with self._lock:
            if self._predictor is None:
                self._predictor = self._load()
            import torch

            with torch.inference_mode():
                self._predictor.set_image(image_rgb)
                masks, scores, _ = self._predictor.predict(box=np.array(box), multimask_output=False)
        mask = (masks[0] > 0).astype(np.uint8) * 255
        return Segmentation(mask, TARGETS[self.target], False, round(time.perf_counter() - start, 3),
                            float(scores[0]))


class SimulatedSegmenter:
    def __init__(self, target: str, reason: str) -> None:
        self.target, self.reason = target, reason

    def unload(self) -> None:
        pass

    def __call__(self, image_rgb: np.ndarray, box: tuple[int, int, int, int]) -> Segmentation:
        start = time.perf_counter()
        mask = grabcut_segment(image_rgb, box)
        return Segmentation(mask, "simulation (GrabCut)", True, round(time.perf_counter() - start, 3))


def make_segmenter(target: str, settings: dict[str, Any]) -> SamSegmenter | SimulatedSegmenter:
    """Le vrai modèle si tout est là ; sinon la simulation, avec la raison précise."""
    if target not in TARGETS:
        raise ValueError(f"cible inconnue : {target!r} (hand ou foot)")
    missing = missing_dependencies()
    weights = weights_path(target, settings)
    if missing:
        return SimulatedSegmenter(target, f"dépendances absentes : {', '.join(missing)}")
    if not weights.is_file():
        return SimulatedSegmenter(target, f"poids {TARGETS[target]} introuvables ({weights.name})")
    return SamSegmenter(target, weights, str(settings.get("device", "")))


def combine(masks: list[np.ndarray]) -> np.ndarray:
    """Plusieurs mains (ou pieds) : réunion des masques."""
    out = np.zeros_like(masks[0])
    for mask in masks:
        out = np.maximum(out, mask)
    return out


def overlay(image_rgb: np.ndarray, mask: np.ndarray, color: tuple[int, int, int] = (255, 64, 160),
            alpha: float = 0.45) -> np.ndarray:
    """Image avec le masque teinté et son contour : pour voir d'un coup d'œil ce qui sera retouché."""
    out = image_rgb.copy()
    selected = mask > 0
    out[selected] = (out[selected] * (1 - alpha) + np.array(color) * alpha).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, color, 2)
    return out


Segmenter = Callable[[np.ndarray, tuple[int, int, int, int]], Segmentation]
