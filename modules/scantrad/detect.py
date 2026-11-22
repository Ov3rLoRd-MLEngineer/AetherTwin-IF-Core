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
    return sort_reading(bubbles, height, page.shape[1])


def detect_text_blocks(page: np.ndarray, char_min: float = 0.011, char_max: float = 0.075,
                       bright_drop: int = 45, min_chars: int = 2) -> list[Bubble]:
    """Détection **par le texte** (pages réelles : papier gris, bulles ouvertes, texte vertical).

    1. l'encre est isolée par un seuil adaptatif (le papier scanné n'est jamais blanc pur) ;
    2. les composantes de la taille d'un caractère, entourées de papier clair, sont candidates ;
    3. les candidates proches sont regroupées en blocs (colonnes ou lignes) ; un bloc isolé d'un seul
       caractère est écarté (pétales, traits du dessin) ;
    4. la zone d'écriture est la plage de papier clair qui entoure le bloc (la bulle, même ouverte).
    Les faux positifs restants sont écartés par l'OCR (« pas de texte »).
    """
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if page.ndim == 3 else page
    height, width = gray.shape
    paper = float(np.percentile(gray, 97))
    bright = gray >= paper - bright_drop
    block_size = max(15, (height // 20) | 1)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block_size, 12)
    ink[gray > paper - 20] = 0  # le grain du papier n'est pas de l'encre
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    lo, hi = char_min * height, char_max * height
    small = np.zeros(count, bool)  # encre « fine » : caractères, ponctuation, furigana (pas les contours)
    candidates = np.zeros((height, width), np.uint8)
    sizes: list[int] = []
    for label in range(1, count):
        x, y, w, h, _area = (int(v) for v in stats[label])
        if max(w, h) <= hi:
            small[label] = True
    for label in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[label])
        if not (lo <= max(w, h) <= hi and min(w, h) >= lo * 0.25):
            continue
        if not 0.08 <= area / (w * h) <= 0.75:
            continue  # tache pleine (dessin) ou trait isolé : pas un caractère
        pad = max(2, h // 3)
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(width, x + w + pad), min(height, y + h + pad)
        window_bright = bright[y0:y1, x0:x1] | small[labels[y0:y1, x0:x1]] & (labels[y0:y1, x0:x1] > 0)
        ring = np.ones((y1 - y0, x1 - x0), bool)
        ring[y - y0:y - y0 + h, x - x0:x - x0 + w] = False
        if window_bright[ring].mean() < 0.8:
            continue  # pas sur du papier clair : élément du dessin
        candidates[y:y + h, x:x + w] = 255
        sizes.append(max(w, h))
    if not sizes:
        return []
    char = float(np.median(sizes))
    gap = max(3, int(char * 0.7))
    merged = cv2.dilate(candidates, np.ones((gap, gap), np.uint8))
    block_count, block_labels, block_stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    blocks: list[Bubble] = []
    singles: list[tuple[int, int, int, int]] = []
    groups: list[tuple[int, int, int, int]] = []
    for label in range(1, block_count):
        x, y, w, h, _area = (int(v) for v in block_stats[label])
        region = (block_labels[y:y + h, x:x + w] == label) & (candidates[y:y + h, x:x + w] > 0)
        chars = cv2.connectedComponents(region.astype(np.uint8), connectivity=8)[0] - 1
        (groups if chars >= min_chars else singles).append((x, y, w, h))
    # Un caractère isolé (fin de ligne espacée, kana en plusieurs traits) rejoint le bloc voisin s'il est aligné
    # avec lui et à moins d'un caractère et demi ; seul, il reste écarté (pétales, traits du dessin).
    # Rattachement aux blocs d'ORIGINE seulement (pas d'enchaînement de proche en proche), 3 au plus par bloc :
    # sinon des pétales alignés finissent par former un grand bloc sur le dessin.
    grown = list(groups)
    attached = [0] * len(groups)
    for single in singles:
        for i, group in enumerate(groups):
            if attached[i] < 3 and _line_like(group, single) and _aligned_near(single, group, 1.5 * char):
                grown[i] = union_box(grown[i], single)
                attached[i] += 1
                break
    for x, y, w, h in grown:
        box = (x, y, w, h)
        blocks.append(Bubble(0, box, np.full((h, w), 255, np.uint8), np.zeros((h, w), np.uint8),
                             area=writing_area(bright, labels, small, box), vertical=h > 1.4 * w))
    paper = cv2.morphologyEx((bright | small[labels] & (labels > 0)).astype(np.uint8), cv2.MORPH_OPEN,
                             np.ones((3, 3), np.uint8))
    paper_id = cv2.connectedComponents(paper, connectivity=4)[1]
    blocks = merge_same_bubble(blocks, char, paper_id)
    pad = int(char * 0.5)  # la ponctuation (…, 、, !) est souvent plus petite qu'un caractère
    for block in blocks:
        x, y, w, h = block.box
        tx, ty = max(0, x - pad), max(0, y - pad)
        tw, th = min(width - tx, w + 2 * pad), min(height - ty, h + 2 * pad)
        inside = labels[ty:ty + th, tx:tx + tw]
        # masque d'effacement : l'encre fine autour du bloc (caractères, ponctuation, furigana)
        block.text_mask = (small[inside] & (inside > 0)).astype(np.uint8) * 255
        block.text_box = (tx, ty, tw, th)
    return sort_reading(blocks, height, page.shape[1])


def _line_like(group: tuple[int, int, int, int], single: tuple[int, int, int, int]) -> bool:
    """Le bloc a la forme d'une ligne (ou d'une colonne) de texte, et le caractère isolé la même hauteur (ou la
    même largeur) : une tache de dessin, plutôt carrée, ne grossit pas en avalant ses voisins."""
    _gx, _gy, gw, gh = group
    _sx, _sy, sw, sh = single
    # 0,5 : la boîte du bloc inclut la marge de regroupement, elle est plus haute que ses caractères
    if gw >= 1.8 * gh:  # ligne horizontale
        return 0.5 <= sh / max(1, gh) <= 1.6
    if gh >= 1.8 * gw:  # colonne verticale
        return 0.5 <= sw / max(1, gw) <= 1.6
    return False


def _aligned_near(a: tuple[int, int, int, int], b: tuple[int, int, int, int], distance: float) -> bool:
    """`a` prolonge `b` : sur la même ligne (ou colonne) à plus de moitié, et l'écart est d'au plus `distance`."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    gap_x = max(bx - (ax + aw), ax - (bx + bw), 0)
    gap_y = max(by - (ay + ah), ay - (by + bh), 0)
    overlap_y = max(0, min(ay + ah, by + bh) - max(ay, by)) / max(1, min(ah, bh))
    overlap_x = max(0, min(ax + aw, bx + bw) - max(ax, bx)) / max(1, min(aw, bw))
    return (gap_x <= distance and gap_y == 0 and overlap_y >= 0.5) or \
        (gap_y <= distance and gap_x == 0 and overlap_x >= 0.5)


def union_box(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    return x0, y0, max(a[0] + a[2], b[0] + b[2]) - x0, max(a[1] + a[3], b[1] + b[3]) - y0


def upscale_small_page(page: np.ndarray, min_height: int = 1100) -> np.ndarray:
    """Agrandit une page trop petite (capture, vignette) : les caractères de 12 px se fondent en taches."""
    height = page.shape[0]
    if height >= min_height:
        return page
    scale = min_height / height
    return cv2.resize(page, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def _inside(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int], tolerance: float = 0.75) -> bool:
    x, y, w, h = inner
    ox, oy, ow, oh = outer
    ix = max(0, min(x + w, ox + ow) - max(x, ox))
    iy = max(0, min(y + h, oy + oh) - max(y, oy))
    return ix * iy >= tolerance * w * h


def _same_bubble(a: tuple[int, int, int, int], b: tuple[int, int, int, int], char: float,
                 paper_id: np.ndarray) -> bool:
    """Deux blocs voisins (écart < 2 caractères), alignés (recouvrement ≥ 30 % sur l'autre axe), posés sur la
    même plage claire : deux colonnes (ou lignes) de la même bulle."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    gap_x = max(bx - (ax + aw), ax - (bx + bw), 0)
    gap_y = max(by - (ay + ah), ay - (by + bh), 0)
    overlap_y = max(0, min(ay + ah, by + bh) - max(ay, by)) / min(ah, bh)
    overlap_x = max(0, min(ax + aw, bx + bw) - max(ax, bx)) / min(aw, bw)
    neighbours = (gap_x <= 2 * char and overlap_y >= 0.3) or (gap_y <= 2 * char and overlap_x >= 0.3)
    if not neighbours:
        return False
    ids_a = paper_id[ay:ay + ah, ax:ax + aw]
    ids_b = paper_id[by:by + bh, bx:bx + bw]
    common = set(np.unique(ids_a[ids_a > 0])) & set(np.unique(ids_b[ids_b > 0]))
    return bool(common)


def merge_same_bubble(blocks: list[Bubble], char: float = 0.0, paper_id: np.ndarray | None = None) -> list[Bubble]:
    """Réunit les colonnes d'une même bulle (voir `_same_bubble`), ou deux blocs dont chacun tient dans la zone
    claire de l'autre."""
    merged = True
    while merged:
        merged = False
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                a, b = blocks[i], blocks[j]
                same = paper_id is not None and _same_bubble(a.box, b.box, char, paper_id)
                if same or (a.area and b.area and _inside(a.box, b.area) and _inside(b.box, a.area)):
                    x0, y0 = min(a.box[0], b.box[0]), min(a.box[1], b.box[1])
                    x1 = max(a.box[0] + a.box[2], b.box[0] + b.box[2])
                    y1 = max(a.box[1] + a.box[3], b.box[1] + b.box[3])
                    # une bulle ne dépasse pas ~20 caractères de long ni ~12 de large : au-delà, la fusion a
                    # enchaîné deux bulles par des onomatopées du dessin (double page de Jérémy, 22/11)
                    if char and (max(x1 - x0, y1 - y0) > 20 * char or min(x1 - x0, y1 - y0) > 12 * char):
                        continue
                    box = (x0, y0, x1 - x0, y1 - y0)
                    area = union_box(a.area or a.box, b.area or b.box)
                    blocks[i] = Bubble(0, box, np.full((y1 - y0, x1 - x0), 255, np.uint8),
                                       np.zeros((y1 - y0, x1 - x0), np.uint8), area=area,
                                       vertical=a.vertical or b.vertical)
                    del blocks[j]
                    merged = True
                    break
            if merged:
                break
    return blocks


def writing_area(bright: np.ndarray, labels: np.ndarray, small: np.ndarray,
                 box: tuple[int, int, int, int], grow: float = 0.9, margin: float = 0.1) -> tuple[int, int, int, int]:
    """Plage claire qui entoure le bloc (la bulle), bornée à une fenêtre autour du bloc. Rend (x, y, l, h)."""
    height, width = bright.shape
    x, y, w, h = box
    side = max(w, h)
    x0, y0 = max(0, int(x - grow * side)), max(0, int(y - grow * h * 0.4))
    x1, y1 = min(width, int(x + w + grow * side)), min(height, int(y + h + grow * h * 0.4))
    window = bright[y0:y1, x0:x1] | small[labels[y0:y1, x0:x1]]  # le texte compte comme de la bulle
    window = cv2.morphologyEx(window.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    _n, comp = cv2.connectedComponents(window, connectivity=4)
    seeds = comp[y - y0:y - y0 + h, x - x0:x - x0 + w]
    values, counts = np.unique(seeds[seeds > 0], return_counts=True)
    if not len(values):
        return box
    ys, xs = np.nonzero(comp == values[np.argmax(counts)])
    ax0, ax1, ay0, ay1 = xs.min() + x0, xs.max() + x0, ys.min() + y0, ys.max() + y0
    aw, ah = ax1 - ax0, ay1 - ay0
    ax0, ay0 = ax0 + int(aw * margin), ay0 + int(ah * margin)
    aw, ah = int(aw * (1 - 2 * margin)), int(ah * (1 - 2 * margin))
    if aw * ah < w * h:  # plage plus petite que le texte lui-même : on garde la boîte du texte
        return box
    return int(ax0), int(ay0), int(aw), int(ah)


def clean_text(page: np.ndarray, blocks: list[Bubble], grow: int = 0, radius: int = 3) -> np.ndarray:
    """Efface l'encre fine de chaque bloc (caractères, ponctuation, furigana) par inpainting ; les contours
    de bulle et le dessin, plus gros, ne sont pas dans le masque. Le masque est élargi selon la taille de la
    page pour emporter aussi le halo gris des caractères scannés."""
    grow = grow or max(1, round(page.shape[0] * 0.0035))
    mask = np.zeros(page.shape[:2], np.uint8)
    kernel = np.ones((2 * grow + 1, 2 * grow + 1), np.uint8)
    for block in blocks:
        x, y, w, h = block.text_box or block.box
        mask[y:y + h, x:x + w] |= cv2.dilate(block.text_mask, kernel)
    return cv2.inpaint(page, mask, radius, cv2.INPAINT_TELEA) if np.count_nonzero(mask) else page.copy()


def sort_reading(bubbles: list[Bubble], page_height: int, page_width: int, right_to_left: bool = True,
                 spread: bool | None = None) -> list[Bubble]:
    """Ordre de lecture : première page puis seconde (double page) ; dans une page, rangées de haut en bas, et
    dans une rangée de droite à gauche (manga) ou de gauche à droite (manhwa, manhua, comic). Une rangée réunit
    les bulles qui se recouvrent au moins à moitié en hauteur : des bandes fixes coupaient deux bulles côte à
    côte (mesuré sur la page de Jérémy). `spread` : double page imposée (True), page simple (False), ou devinée
    à la forme de l'image (None : plus large que haute)."""
    double = page_width > 1.25 * page_height if spread is None else spread

    def side(b: Bubble) -> int:
        x, _y, w, _h = b.box
        on_left = x + w / 2 < page_width / 2
        return 0 if not double else (int(on_left) if right_to_left else int(not on_left))

    def span(b: Bubble) -> tuple[int, int]:  # hauteur de la bulle (plage claire) si connue, sinon du texte
        box = b.area or b.box
        return box[1], box[3]

    ordered: list[Bubble] = []
    for s in (0, 1):
        rows: list[list[Bubble]] = []
        for bubble in sorted((b for b in bubbles if side(b) == s), key=lambda b: span(b)[0]):
            y, h = span(bubble)
            for row in rows:
                top = min(span(b)[0] for b in row)
                bottom = max(sum(span(b)) for b in row)
                if min(y + h, bottom) - max(y, top) >= 0.5 * min(h, bottom - top):
                    row.append(bubble)
                    break
            else:
                rows.append([bubble])
        for row in rows:
            ordered.extend(sorted(row, key=lambda b: -(b.box[0] + b.box[2]) if right_to_left else b.box[0]))
    for index, bubble in enumerate(ordered, start=1):
        bubble.index = index
    return ordered


def reading_key(box: tuple[int, int, int, int], page_height: int, page_width: int = 0) -> tuple[int, int, int]:
    """Ordre de lecture du manga : de haut en bas par bandes, et de droite à gauche dans une bande. Une double
    page (plus large que haute) se lit page de droite d'abord, puis page de gauche : mesuré sur la double page
    de Jérémy en mode manuel, l'ordre automatique n'y était juste que pour 4 paires de bulles sur 7."""
    x, y, w, h = box
    side = 0
    if page_width > 1.25 * page_height:
        side = 0 if x + w / 2 >= page_width / 2 else 1
    band = int((y + h / 2) // max(1, page_height // 8))
    return side, band, -(x + w)


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
