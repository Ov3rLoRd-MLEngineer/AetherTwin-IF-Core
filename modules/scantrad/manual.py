"""Mode manuel : les zones de texte sont posées à la main, dans l'ordre de lecture.

L'utilisateur trace une boîte autour de chaque bulle (l'ordre des tracés est l'ordre de lecture) ; le texte de
chaque boîte est lu par l'OCR du Hub, traduit, puis réécrit dans la boîte. L'effacement se fait à la gomme dans
le navigateur, ou par `erase_in_boxes`, qui retire l'encre fine à l'intérieur des boîtes sans toucher au contour
de la bulle. Plus de détection automatique : pas de bulle oubliée ni de texte posé sur le dessin.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from modules.scantrad.detect import detect_text_blocks, sort_reading, upscale_small_page
from modules.scantrad.languages import LANGUAGES
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


def _gaps(profile: np.ndarray, min_length: float = 2) -> list[int]:
    """Largeurs des bandes vides (d'au moins `min_length`) entre deux zones d'encre."""
    found, run, seen_ink = [], 0, False
    for filled in profile:
        if filled:
            if seen_ink and run >= min_length:
                found.append(run)
            run, seen_ink = 0, True
        else:
            run += 1
    return found


def is_vertical(crop: np.ndarray) -> bool:
    """Texte en colonnes (lecture verticale) ou en lignes ? Une encre très allongée (une seule colonne, une seule
    ligne) se juge à sa forme. Sinon on compare les bandes vides qui traversent tout le bloc : l'espace entre
    deux colonnes (ou deux lignes) est plus large que l'espace entre deux caractères qui se suivent. On compare
    leurs largeurs, pas leur nombre : dans un texte aligné en grille, les petits espaces entre caractères
    traversent eux aussi le bloc."""
    mask = ink_mask(crop, grow=False) > 0
    if mask.sum() < 20:
        return crop.shape[0] > crop.shape[1]
    ys, xs = np.nonzero(mask)
    box = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    tall = box.shape[0] > box.shape[1]
    if max(box.shape) > 1.6 * min(box.shape):
        return tall
    columns, lines = _gaps(box.any(axis=0)), _gaps(box.any(axis=1))
    if columns and lines:
        return float(np.median(columns)) > float(np.median(lines))
    if columns or lines:
        return bool(columns)
    return tall


def split_columns(crop: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Colonnes d'un texte vertical, de droite à gauche (ordre de lecture), en (x, y, l, h) dans `crop`.
    Le modèle de vision mélange l'ordre des colonnes courtes d'une même bulle (essai du 22/11) ; lues une par
    une, elles sont justes. Les colonnes très fines (furigana) sont écartées."""
    mask = ink_mask(crop, grow=False) > 0
    if mask.sum() < 20:
        return []
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    sizes = [max(int(s[2]), int(s[3])) for s in stats[1:] if s[4] >= 4]
    char = float(np.percentile(sizes, 75)) if sizes else 10.0
    # seules les traces de la taille d'un caractère comptent : un contour de bulle (long trait fin) ou un
    # morceau de dessin pris dans le cadre ferait une fausse colonne (« 一七 » ajouté, essai du 22/11)
    height, width = mask.shape

    def stray(label: int) -> bool:  # trop grand pour un caractère, ou collé au bord du cadre (le texte n'y touche pas)
        x, y, w, h = (int(v) for v in stats[label][:4])
        return max(w, h) > 2.5 * char or x == 0 or y == 0 or x + w >= width or y + h >= height

    big = [label for label in range(1, count) if stray(label)]
    if big:
        mask = mask & ~np.isin(labels, big)
        if mask.sum() < 20:
            return []
    filled = mask.any(axis=0)
    gap = max(3.0, 0.12 * char)
    spans, start, run = [], None, 0
    for x, ink in enumerate(list(filled) + [False] * int(gap + 1)):
        if ink:
            if start is None:
                start = x
            run = 0
        elif start is not None:
            run += 1
            if run >= gap:
                spans.append((start, x - run + 1))
                start, run = None, 0
    if not spans:
        return []
    widest = max(b - a for a, b in spans)
    columns = []
    for a, b in reversed(spans):  # de droite à gauche
        if b - a < 0.45 * widest:
            continue  # furigana, ou trait isolé
        ys = np.nonzero(mask[:, a:b].any(axis=1))[0]
        pad = max(2, int(0.15 * char))
        x0, x1 = max(0, a - pad), min(crop.shape[1], b + pad)
        y0, y1 = max(0, int(ys.min()) - pad), min(crop.shape[0], int(ys.max()) + 1 + pad)
        columns.append((x0, y0, x1 - x0, y1 - y0))
    return columns


def widen_area(page: np.ndarray, box: tuple[int, int, int, int], bright: int = 200) -> tuple[int, int, int, int]:
    """Zone d'écriture d'une zone étroite (une colonne japonaise) : élargie sur les côtés tant que le papier reste
    clair sur toute la hauteur de la zone. Le français, horizontal, a besoin de largeur : sinon il est écrit
    minuscule (« Je suis Vaccine Man. », essai de Jérémy du 22/11)."""
    x, y, w, h = box
    if w >= 0.8 * h:
        return box
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if page.ndim == 3 else page
    band = gray[y:y + h]
    limit = int(0.9 * h)  # au plus une bulle presque carrée
    x0, x1 = x, x + w
    clear = lambda col: (band[:, col] >= bright).mean() >= 0.97  # noqa: E731
    grown = True
    while grown and x1 - x0 < limit:
        grown = False
        if x0 > 0 and clear(x0 - 1):
            x0, grown = x0 - 1, True
        if x1 < gray.shape[1] and x1 - x0 < limit and clear(x1):
            x1, grown = x1 + 1, True
    return x0, y, x1 - x0, h


def ink_mask(crop: np.ndarray, grow: bool = True) -> np.ndarray:
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
    if not grow:
        return mask
    size = max(2, int(round(min(height, width) / 60)))  # halo gris des caractères scannés
    return cv2.dilate(mask, np.ones((2 * size + 1, 2 * size + 1), np.uint8))


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


def cover(a: list[int] | tuple[int, ...], b: list[int] | tuple[int, ...]) -> float:
    """Part de la boîte `a` recouverte par la boîte `b` (0 à 1)."""
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return ix * iy / max(1, a[2] * a[3])


def evaluate(data_dir: Path) -> dict[str, Any]:
    """Mesure la détection automatique sur les pages faites en mode manuel (vérité de terrain) :
    - **rappel** : part des zones posées à la main qu'une détection recouvre au moins à moitié ;
    - **fausses détections** : détections hors de toute zone (avant le tri par l'OCR, qui en écarte une partie) ;
    - **ordre** : part des paires de bulles consécutives que la détection lit dans le même ordre.
    C'est la base de tout réglage ou apprentissage futur : on ne garde un changement que s'il améliore ces chiffres."""
    from modules.scantrad.cli import read_image

    pages = []
    for job_path in sorted((data_dir / "sorties").glob("*_travail.json")):
        job = json.loads(job_path.read_text(encoding="utf-8"))
        source = data_dir / "entrees" / str(job.get("source", ""))
        if job.get("mode") != "manuel" or not source.is_file():
            continue
        truth = [b["box"] for b in job["bubbles"] if b.get("kind", "bulle") == "bulle"]  # annexes : hors mesure
        if not truth:
            continue
        lang = LANGUAGES.get(str(job.get("lang", "ja")), LANGUAGES["ja"])
        found = suggest_boxes(read_image(source), lang.right_to_left)
        best = [max(range(len(found)), key=lambda i, t=t: cover(t, found[i])) if found else -1 for t in truth]
        hit = [i >= 0 and cover(t, found[i]) >= 0.5 for t, i in zip(truth, best, strict=True)]
        false_pos = sum(1 for f in found if max((cover(f, t) for t in truth), default=0) < 0.3)
        pairs = [(best[k], best[k + 1]) for k in range(len(truth) - 1) if hit[k] and hit[k + 1]]
        pages.append({"page": source.name, "series": job.get("series", ""), "zones": len(truth),
                      "found": sum(hit), "false_positives": false_pos,
                      "order_ok": sum(1 for a, b in pairs if a < b), "order_pairs": len(pairs)})
    zones = sum(p["zones"] for p in pages)
    order_pairs = sum(p["order_pairs"] for p in pages)
    return {"pages": len(pages), "zones": zones,
            "recall": round(sum(p["found"] for p in pages) / zones, 3) if zones else None,
            "false_positives": sum(p["false_positives"] for p in pages),
            "order_agreement": round(sum(p["order_ok"] for p in pages) / order_pairs, 3) if order_pairs else None,
            "per_page": pages}


def suggest_boxes(page: np.ndarray, right_to_left: bool = True, spread: bool | None = None) -> list[list[int]]:
    """Boîtes de la détection automatique, dans l'ordre de lecture, comme point de départ à corriger
    (coordonnées de la page reçue)."""
    big = upscale_small_page(page)
    scale = page.shape[0] / big.shape[0]
    boxes = []
    for bubble in sort_reading(detect_text_blocks(big), big.shape[0], big.shape[1], right_to_left, spread):
        x, y, w, h = bubble.box
        boxes.append([int(x * scale), int(y * scale), max(1, int(w * scale)), max(1, int(h * scale))])
    return boxes
