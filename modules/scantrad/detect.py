"""Détection heuristique des bulles (OpenCV) et effacement du texte d'origine (inpainting OpenCV).

Heuristique : une bulle est une zone **claire**, fermée, qui ne touche pas le bord de la page, de forme pleine
(ellipse, rectangle arrondi) et qui contient des **trous sombres** : les traits du texte.
Limites connues : les bulles sans contour sur fond blanc, le texte hors bulle et les onomatopées dessinées ne
sont pas détectés. Un modèle de détection appris peut remplacer cette fonction (même signature).
"""
from __future__ import annotations

import cv2
import numpy as np

from modules.scantrad.pipeline import Bubble


def detect_bubbles(page: np.ndarray, white_level: int = 200, min_area_ratio: float = 0.002,
                   max_area_ratio: float = 0.25, min_fill: float = 0.5,
                   text_ratio: tuple[float, float] = (0.005, 0.45)) -> list[Bubble]:
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if page.ndim == 3 else page
    height, width = gray.shape
    white = (gray >= white_level).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    page_area = height * width
    bubbles: list[Bubble] = []
    for label in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[label])
        if x == 0 or y == 0 or x + w >= width or y + h >= height:
            continue  # touche le bord : fond de page ou de case
        if not (min_area_ratio * page_area <= area <= max_area_ratio * page_area):
            continue
        component = (labels[y:y + h, x:x + w] == label).astype(np.uint8) * 255
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(component)
        cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
        filled_area = int(np.count_nonzero(filled))
        if filled_area < min_fill * w * h:
            continue  # forme trop creuse : pas une bulle
        holes = cv2.bitwise_and(filled, cv2.bitwise_not(component))
        ratio = np.count_nonzero(holes) / filled_area
        if not (text_ratio[0] <= ratio <= text_ratio[1]):
            continue  # pas de texte (ou trop : une zone de dessin)
        bubbles.append(Bubble(0, (x, y, w, h), filled, holes))
    bubbles.sort(key=lambda b: reading_key(b.box, height))
    for index, bubble in enumerate(bubbles, start=1):
        bubble.index = index
    return bubbles


def reading_key(box: tuple[int, int, int, int], page_height: int) -> tuple[int, int]:
    """Ordre de lecture du manga : de haut en bas par bandes, et de droite à gauche dans une bande."""
    x, y, w, h = box
    band = int((y + h / 2) // max(1, page_height // 8))
    return band, -(x + w)


def clean_bubbles(page: np.ndarray, bubbles: list[Bubble], radius: int = 3, grow: int = 2) -> np.ndarray:
    """Efface le texte de chaque bulle par inpainting (OpenCV, Telea), sans toucher au contour de la bulle."""
    out = page.copy()
    mask = np.zeros(page.shape[:2], dtype=np.uint8)
    kernel = np.ones((2 * grow + 1, 2 * grow + 1), np.uint8)
    for bubble in bubbles:
        x, y, w, h = bubble.box
        inner = cv2.erode(bubble.mask, np.ones((5, 5), np.uint8))  # on reste à l'intérieur du contour
        text = cv2.bitwise_and(cv2.dilate(bubble.text_mask, kernel), inner)
        mask[y:y + h, x:x + w] = cv2.bitwise_or(mask[y:y + h, x:x + w], text)
    if np.count_nonzero(mask):
        out = cv2.inpaint(out, mask, radius, cv2.INPAINT_TELEA)
    return out
