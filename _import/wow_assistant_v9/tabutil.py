"""
Petits utilitaires partagés par les onglets.
"""
import time

import pygame

import mousepos


def hover(rect):
    return pygame.Rect(rect).collidepoint(mousepos.get())


def message(ui, rect, lines, color="gray"):
    x, y, w, h = rect
    py = y + h // 2 - 12 * len(lines)
    for line in lines:
        ui.text(line, "medium", color, (x + w // 2, py), anchor="center")
        py += 26


def format_age(timestamp):
    """'il y a 5 min' à partir d'un horodatage (ou 'jamais')."""
    if not timestamp:
        return "jamais"
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 90:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {seconds // 60} min"
    if seconds < 86400:
        return f"il y a {seconds // 3600} h"
    return f"il y a {seconds // 86400} j"


def format_remaining(seconds):
    seconds = int(seconds)
    if seconds <= 0:
        return "réinitialisé"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days} j {hours} h"
    return f"{hours} h {rest // 60} min"
