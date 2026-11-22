"""Mode manuel : les zones de texte sont posées à la main, dans l'ordre de lecture.

L'utilisateur trace une boîte autour de chaque bulle (l'ordre des tracés est l'ordre de lecture) ; le texte de
chaque boîte est lu par l'OCR du Hub, traduit, puis réécrit dans la boîte. L'effacement se fait à la gomme dans
le navigateur, ou par `erase_in_boxes`, qui retire l'encre fine à l'intérieur des boîtes sans toucher au contour
de la bulle. Plus de détection automatique : pas de bulle oubliée ni de texte posé sur le dessin.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from modules.scantrad.detect import detect_text_blocks, upscale_small_page
from modules.scantrad.pipeline import Bubble

MAX_BOXES = 200
MIN_SIDE = 8


def parse_boxes(raw: Any, shape: tuple[int, ...]) -> list[tuple[int, int, int, int]]:
    """Boîtes [x, y, largeur, hauteur] envoyées par la page, ramenées dans l'image. Refuse le reste."""
    if not isinstance(raw, list) or not raw or len(raw) > MAX_BOXES:
        raise ValueError(f"`boxes` : liste de 1 à {MAX_BOXES} boîtes [x, y, largeur, hauteur]")
    height, width = shape[:2]
    boxes = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 4 or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in item):
            raise ValueError("boîte invalide : [x, y, largeur, hauteur] attendu")
        x, y, w, h = (int(round(v)) for v in item)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
            raise ValueError(f"boîte trop petite ou hors de l'image : {list(item)}")
        boxes.append((x0, y0, x1 - x0, y1 - y0))
    return boxes


def bubbles_from_boxes(boxes: list[tuple[int, int, int, int]]) -> list[Bubble]:
    """Une bulle par boîte, numérotée dans l'ordre donné. La zone d'écriture est la boîte elle-même."""
    bubbles = []
    for index, (x, y, w, h) in enumerate(boxes, start=1):
        bubbles.append(Bubble(index, (x, y, w, h), np.full((h, w), 255, np.uint8), np.zeros((h, w), np.uint8),
                              area=(x, y, w, h)))
    return bubbles


def ink_mask(crop: np.ndarray) -> np.ndarray:
    """Encre du texte dans une boîte : traits sombres, petits, qui ne touchent pas le bord de la boîte.
    Le contour de la bulle (grand, ou coupé par le bord) et le dessin qui dépasse sont laissés."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    height, width = gray.shape
    paper = float(np.percentile(gray, 90))  # fond de la bulle : la valeur claire dominante
    dark = (gray < min(paper - 40, 200)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    mask = np.zeros_like(dark)
    for label in range(1, count):
        x, y, w, h, _area = stats[label]
        touches = x == 0 or y == 0 or x + w >= width or y + h >= height
        # contour de bulle : grand, ou long et coupé par le bord ; un caractère coupé par le bord reste du texte
        outline = (w > 0.6 * width and h > 0.6 * height) or (touches and (w > 0.4 * width or h > 0.4 * height))
        if not outline:
            mask[labels == label] = 255
    grow = max(2, int(round(min(height, width) / 60)))  # halo gris des caractères scannés
    return cv2.dilate(mask, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))


def erase_in_boxes(page: np.ndarray, boxes: list[tuple[int, int, int, int]], radius: int = 3) -> np.ndarray:
    """Efface le texte à l'intérieur des boîtes : un premier passage, la gomme finit le travail.
    Sur une bulle blanche, l'encre est recouverte de la couleur du papier (l'inpainting y laissait un fantôme
    gris) ; sur une trame ou un fond dessiné, elle est reconstruite par inpainting."""
    out = page.copy()
    for x, y, w, h in boxes:
        crop = out[y:y + h, x:x + w]
        mask = ink_mask(crop)
        if not mask.any():
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        around = gray[(mask == 0)]
        paper = np.percentile(around, 75) if around.size else 255
        if paper >= 215 and (around >= paper - 25).mean() > 0.6:  # fond clair et uni : papier de la bulle
            color = np.median(crop[(mask == 0) & (gray >= paper - 25)], axis=0)
            # halo clair autour des caractères (anticrénelage, artefacts JPEG) : recouvert aussi ; le trait sombre
            # d'un contour voisin, lui, est gardé
            near = cv2.dilate(mask, np.ones((7, 7), np.uint8)) > 0
            crop[(mask > 0) | (near & (gray > paper - 70))] = color
        else:
            out[y:y + h, x:x + w] = cv2.inpaint(crop, mask, radius, cv2.INPAINT_TELEA)
    return out


def suggest_boxes(page: np.ndarray) -> list[list[int]]:
    """Boîtes de la détection automatique, comme point de départ à corriger (coordonnées de la page reçue)."""
    big = upscale_small_page(page)
    scale = page.shape[0] / big.shape[0]
    boxes = []
    for bubble in detect_text_blocks(big):
        x, y, w, h = bubble.box
        boxes.append([int(x * scale), int(y * scale), max(1, int(w * scale)), max(1, int(h * scale))])
    return boxes
