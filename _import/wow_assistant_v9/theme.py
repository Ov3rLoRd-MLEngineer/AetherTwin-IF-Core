"""
Couleurs et petits utilitaires d'affichage partagés par l'interface et les onglets.
"""
import re

QUALITY_COLORS = {0: (157, 157, 157), 1: (255, 255, 255), 2: (30, 255, 0), 3: (0, 112, 221),
                  4: (163, 53, 238), 5: (255, 128, 0), 6: (230, 204, 128), 7: (0, 204, 255)}

C = {
    "bg_top": (34, 35, 40), "bg_bottom": (12, 12, 15),
    "frame": (88, 90, 98), "frame_hi": (140, 142, 150), "frame_lo": (24, 24, 28),
    "panel": (16, 16, 20), "panel_alt": (22, 22, 27), "row_hover": (34, 32, 24),
    "header": (38, 37, 40), "header_border": (120, 104, 62),
    "gold": (255, 209, 0), "text": (236, 230, 210), "label": (232, 200, 120),
    "gray": (140, 138, 130), "light_gray": (200, 198, 190),
    "green": (80, 220, 100), "red": (255, 90, 90), "orange": (255, 180, 60), "blue": (90, 160, 255),
    "xp": (140, 80, 220), "xp_back": (40, 30, 62),
}

# couleurs des types d'événements du journal d'activité
EVENT_COLORS = {
    "level": (255, 209, 0), "zone": (90, 160, 255), "gold": (232, 200, 120), "gear": (163, 53, 238),
    "quest": (80, 220, 100), "death": (255, 90, 90), "achievement": (255, 128, 0), "collection": (0, 204, 255), "spec": (244, 140, 186),
}

_WOW_CODES = [
    (re.compile(r"\|c[0-9a-fA-F]{8}"), ""), (re.compile(r"\|cn[^:|]*:"), ""), (re.compile(r"\|r"), ""),
    (re.compile(r"\|T[^|]*\|t"), ""), (re.compile(r"\|A[^|]*\|a"), ""),
    (re.compile(r"\|H[^|]*\|h"), ""), (re.compile(r"\|h"), ""), (re.compile(r"\|n"), " "),
]


def clean_wow_text(text):
    """Retire les codes de mise en forme de WoW (|cff...|r, icônes, liens)."""
    for pattern, repl in _WOW_CODES:
        text = pattern.sub(repl, text)
    return text


def hex_to_rgb(value, default=(255, 255, 255)):
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (TypeError, ValueError):
        return default


def format_gold(copper):
    """12 345 600 -> '1 234 or'"""
    return f"{int(copper or 0) // 10000:,}".replace(",", " ") + " or"
