"""Effacement par reconstruction : LaMa (big-lama, Apache 2.0), version ONNX `Carve/LaMa-ONNX`.

LaMa redessine ce qui devrait se trouver sous le texte (trame, décor, dessin) au lieu de le recouvrir de blanc
ou de flouter les bords (inpainting OpenCV). Il tourne sur le processeur par onnxruntime : pas de PyTorch, et la
VRAM reste aux modèles de langage.

Le modèle travaille en 512 × 512 : chaque tache de texte est découpée avec du contexte autour, ramenée à 512,
reconstruite, puis seuls les pixels masqués sont recollés dans la page (le reste de la page n'est jamais touché).

Poids : `models/scantrad/lama_fp32.onnx` (198 Mo), téléchargés par `scripts\\setup.ps1 -Weights`.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = REPO_ROOT / "models" / "scantrad" / "lama_fp32.onnx"
SIZE = 512
_sessions: dict[str, object] = {}


def available(path: Path = DEFAULT_WEIGHTS) -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return path.is_file()


def _session(path: Path):
    key = str(path)
    if key not in _sessions:
        import onnxruntime

        _sessions[key] = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _sessions[key]


def _run(session, crop: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Une reconstruction en 512 × 512 : `crop` BGR uint8, `mask` 0/255. Rend un BGR uint8 de même taille."""
    h, w = mask.shape
    image = cv2.resize(crop, (SIZE, SIZE), interpolation=cv2.INTER_AREA if max(h, w) > SIZE else cv2.INTER_CUBIC)
    small = cv2.resize(mask, (SIZE, SIZE), interpolation=cv2.INTER_NEAREST)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    feed = {"image": rgb.transpose(2, 0, 1)[None], "mask": (small > 0).astype(np.float32)[None, None]}
    out = session.run(None, feed)[0][0].transpose(1, 2, 0)
    if out.max() <= 1.5:  # selon l'export, la sortie est en 0-1 ou en 0-255
        out = out * 255.0
    result = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    return cv2.resize(result, (w, h), interpolation=cv2.INTER_CUBIC)


def inpaint(page: np.ndarray, mask: np.ndarray, path: Path = DEFAULT_WEIGHTS, context: float = 1.0) -> np.ndarray:
    """Page (BGR) dont les pixels de `mask` (0/255, même taille) sont reconstruits par LaMa."""
    if not mask.any():
        return page.copy()
    session = _session(path)
    out = page.copy()
    height, width = mask.shape
    grown = cv2.dilate(mask, np.ones((15, 15), np.uint8))  # regroupe les caractères d'une même bulle
    count, _labels, stats, _ = cv2.connectedComponentsWithStats((grown > 0).astype(np.uint8), connectivity=8)
    for label in range(1, count):
        x, y, w, h, _area = (int(v) for v in stats[label])
        side = int(max(w, h) * (1 + 2 * context)) + 16  # carré avec du contexte autour : LaMa s'en inspire
        side = min(side, max(width, height))
        cx, cy = x + w // 2, y + h // 2
        x0 = max(0, min(width - side, cx - side // 2)) if side <= width else 0
        y0 = max(0, min(height - side, cy - side // 2)) if side <= height else 0
        x1, y1 = min(width, x0 + side), min(height, y0 + side)
        crop, local = out[y0:y1, x0:x1], mask[y0:y1, x0:x1]
        rebuilt = _run(session, crop, local)
        keep = local > 0
        crop[keep] = rebuilt[keep]
    return out
