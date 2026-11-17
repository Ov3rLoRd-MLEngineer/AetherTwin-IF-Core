"""Boîtes automatiques : le modèle de vision local (Qwen2.5-VL) localise les mains ou les pieds.

Qwen2.5-VL donne des coordonnées **dans l'image telle qu'il la reçoit** ; Ollama redimensionne les images vers
environ 1 million de pixels (côtés multiples de 28). Pour ne pas dépendre de ce détail, l'image est envoyée
déjà à cette taille, et les boîtes sont ramenées à l'échelle d'origine ici.

Mesuré le 17/11/2026 sur une page de manga photographiée : les deux mains les plus visibles trouvées et bien
encadrées ; les petites mains des cases du bas manquées. Les boîtes servent de point de départ, à corriger.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import cv2
import numpy as np

TARGET_PIXELS = 1003520  # 1280 × 28 × 28 : taille où Ollama ne redimensionne plus l'image
LABELS = {"hand": "hand", "foot": "foot or shoe"}


def prepare(image_rgb: np.ndarray) -> tuple[str, float, float]:
    """Image en PNG base64 à la taille attendue par le modèle, et facteurs (x, y) pour revenir à l'original."""
    height, width = image_rgb.shape[:2]
    scale = (TARGET_PIXELS / (width * height)) ** 0.5
    new_w, new_h = max(28, int(width * scale // 28) * 28), max(28, int(height * scale // 28) * 28)
    resized = cv2.resize(image_rgb, (new_w, new_h), interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    ok, png = cv2.imencode(".png", cv2.cvtColor(resized, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError("encodage PNG impossible")
    return base64.b64encode(png.tobytes()).decode("ascii"), width / new_w, height / new_h


def prompt(target: str) -> str:
    label = LABELS[target]
    return (f"Locate every {label} visible in this image (drawn characters included). "
            f'Output only JSON: [{{"bbox_2d": [x1, y1, x2, y2], "label": "{target}"}}]. '
            "If there is none, output []")


def parse_boxes(text: str, sx: float, sy: float, width: int, height: int, pad: float = 0.12,
                limit: int = 12) -> list[list[int]]:
    """Boîtes du modèle ramenées à l'image d'origine, élargies un peu (SAM préfère une boîte un peu large),
    bornées à l'image ; les boîtes dégénérées ou hors image sont écartées."""
    match = re.search(r"\[.*\]", re.sub(r"<think>.*?</think>", "", text, flags=re.S), flags=re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except ValueError:
        return []
    boxes: list[list[int]] = []
    for item in items if isinstance(items, list) else []:
        raw = item.get("bbox_2d") if isinstance(item, dict) else None
        if not isinstance(raw, list) or len(raw) != 4 or not all(isinstance(v, int | float) for v in raw):
            continue
        x1, y1, x2, y2 = raw[0] * sx, raw[1] * sy, raw[2] * sx, raw[3] * sy
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        dx, dy = (x2 - x1) * pad, (y2 - y1) * pad
        box = [max(0, int(x1 - dx)), max(0, int(y1 - dy)), min(width - 1, int(x2 + dx)), min(height - 1, int(y2 + dy))]
        if box[2] - box[0] >= 4 and box[3] - box[1] >= 4:
            boxes.append(box)
        if len(boxes) == limit:
            break
    return boxes


def detect(image_rgb: np.ndarray, target: str, chat: Any, model: str = "qwen2.5vl:7b") -> list[list[int]]:
    """`chat(messages, model=…, num_ctx=…, options=…)` : le routeur LLM du Hub (règles VRAM appliquées)."""
    if target not in LABELS:
        raise ValueError(f"cible inconnue : {target!r}")
    data, sx, sy = prepare(image_rgb)
    answer = chat([{"role": "user", "content": prompt(target), "images": [data]}], model=model, num_ctx=4096,
                  options={"temperature": 0})
    height, width = image_rgb.shape[:2]
    return parse_boxes(answer["content"], sx, sy, width, height)
