"""Réincrustation : texte traduit centré dans la bulle, taille ajustée, retours à la ligne automatiques."""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from modules.scantrad.pipeline import Bubble

FONT_CANDIDATES = ["comic.ttf", "arial.ttf", "DejaVuSans.ttf"]
FontLoader = Callable[[int], ImageFont.FreeTypeFont | ImageFont.ImageFont]


def font_loader(path: str = "") -> FontLoader:
    """Police choisie (chemin), sinon une police courante du système, sinon celle fournie avec Pillow."""
    candidates = [path] if path else []
    if sys.platform == "win32":
        candidates += [str(Path("C:/Windows/Fonts") / name) for name in FONT_CANDIDATES]
    candidates += FONT_CANDIDATES

    def load(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        return ImageFont.load_default(size)
    return load


def text_area(bubble: Bubble) -> tuple[int, int, int, int]:
    """Rectangle d'écriture dans la bulle (coordonnées de la page) : la zone où la bulle est la plus large,
    réduite pour rester à l'intérieur d'une forme ronde."""
    x, y, w, h = bubble.box
    moments = cv2.moments(bubble.mask, binaryImage=True)
    cx = moments["m10"] / moments["m00"] if moments["m00"] else w / 2
    cy = moments["m01"] / moments["m00"] if moments["m00"] else h / 2
    inner_w, inner_h = int(w * 0.72), int(h * 0.66)
    return int(x + cx - inner_w / 2), int(y + cy - inner_h / 2), inner_w, inner_h


def wrap(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, width: int,
         draw: ImageDraw.ImageDraw) -> list[str] | None:
    """Coupe aux espaces pour tenir dans `width`. `None` si un mot seul est trop large."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        if draw.textlength(word, font=font) > width:
            return None
        attempt = f"{current} {word}".strip()
        if draw.textlength(attempt, font=font) <= width:
            current = attempt
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit(text: str, width: int, height: int, load: FontLoader, draw: ImageDraw.ImageDraw,
        max_size: int = 30, min_size: int = 8) -> tuple[int, list[str], int]:
    """Plus grande taille de police qui fait tenir le texte : (taille, lignes, hauteur de ligne)."""
    for size in range(max_size, min_size - 1, -1):
        font = load(size)
        lines = wrap(text, font, width, draw)
        line_height = int(size * 1.18)
        if lines is not None and len(lines) * line_height <= height:
            return size, lines, line_height
    font = load(min_size)
    return min_size, wrap(text, font, width, draw) or [text], int(min_size * 1.18)


def make_typesetter(font_path: str = "", color: tuple[int, int, int] = (0, 0, 0)) -> Callable[..., np.ndarray]:
    load = font_loader(font_path)

    def typeset(page: np.ndarray, bubbles: list[Bubble]) -> np.ndarray:
        image = Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image)
        for bubble in bubbles:
            if not bubble.translation:
                continue
            ax, ay, aw, ah = text_area(bubble)
            size, lines, line_height = fit(bubble.translation, aw, ah, load, draw)
            font = load(size)
            top = ay + (ah - len(lines) * line_height) / 2
            for i, line in enumerate(lines):
                left = ax + (aw - draw.textlength(line, font=font)) / 2
                draw.text((left, top + i * line_height), line, font=font, fill=color)
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    return typeset
