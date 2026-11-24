"""Palettes du studio : palettes intégrées (créées pour AetherTwin), rampes de couleurs, palette tirée d'une image.

Une rampe suit la technique classique du pixel art : en descendant vers l'ombre, la teinte glisse vers le bleu-violet
et la saturation monte ; vers la lumière, elle glisse vers le jaune et la luminosité monte.

    ramp("#c0703a", 5)        # 5 tons, du plus sombre au plus clair, le ton de base au milieu
"""
from __future__ import annotations

import colorsys
import io
import re
from typing import Any

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_COLORS = 256


def check_hex(value: Any) -> str:
    text = str(value).strip()
    if len(text) == 4 and text.startswith("#"):  # #abc -> #aabbcc
        text = "#" + "".join(c * 2 for c in text[1:])
    if not HEX.match(text):
        raise ValueError(f"couleur invalide : {value!r} (forme « #rrggbb »)")
    return text.lower()


def rgb_of(value: str) -> tuple[int, int, int]:
    text = check_hex(value)
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)


def hex_of(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in (r, g, b))


def ramp(base: str, count: int = 5, hue_shift: float = 0.06) -> list[str]:
    """`count` tons du plus sombre au plus clair autour de `base` (au milieu), avec glissement de teinte."""
    if not 2 <= int(count) <= 16:
        raise ValueError("une rampe compte de 2 à 16 tons")
    count = int(count)
    r, g, b = (v / 255 for v in rgb_of(base))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    middle = (count - 1) / 2
    out = []
    for i in range(count):
        k = (i - middle) / max(middle, 1)  # -1 (ombre) … 0 (base) … +1 (lumière)
        # vers l'ombre : teinte vers ~0.70 (bleu-violet) ; vers la lumière : vers ~0.15 (jaune)
        target = 0.70 if k < 0 else 0.15
        delta = ((target - h + 0.5) % 1.0) - 0.5
        hh = (h + delta * min(1.0, abs(k) * hue_shift * 4)) % 1.0
        ss = max(0.0, min(1.0, s * (1 + 0.25 * -k) if k < 0 else s * (1 - 0.45 * k)))
        vv = max(0.0, min(1.0, v * (1 + 0.55 * k) if k < 0 else v + (1 - v) * 0.75 * k))
        out.append(hex_of(*(c * 255 for c in colorsys.hsv_to_rgb(hh, ss, vv))))
    return out


def _aether32() -> list[str]:
    colors = ["#0e1116", "#3b4250", "#8f98a8", "#eef1f5"]  # neutres
    for base in ("#2ec4d6", "#e8a33a", "#d6455d", "#4caf50", "#7048e8", "#c0703a", "#e0c27a"):
        colors += ramp(base, 4)
    return colors


BUILTIN: dict[str, dict[str, Any]] = {
    "aether16": {"label": "Æther 16", "colors": [
        "#0e1116", "#262b35", "#4a5263", "#8f98a8", "#eef1f5", "#0f6f7c", "#2ec4d6", "#9de8ef",
        "#8a5a12", "#e8a33a", "#ffe08a", "#7a1f35", "#d6455d", "#2b6b35", "#4caf50", "#5536b0"]},
    "aether32": {"label": "Æther 32 (rampes)", "colors": _aether32()},
    "chats": {"label": "Pelages (Fuma et Inoue)", "colors": [
        "#1a1412", "#3d2b22", "#6b4630", "#a3683d", "#d9934f", "#f2c38a", "#fbe7c8", "#ffffff",
        "#2a2d33", "#55595f", "#8a8e94", "#c4c7cb", "#e86b8a", "#7fd36b", "#4f9be8", "#f4d03f"]},
    "console4": {"label": "Console 4 verts", "colors": ["#0f2a1d", "#33583b", "#7a9e5a", "#c4d7a0"]},
    "gris8": {"label": "Gris 8 tons", "colors": [hex_of(v, v, v) for v in (0, 36, 73, 109, 146, 182, 219, 255)]},
    "foret": {"label": "Forêt et pierre", "colors": ramp("#3f8f4a", 5) + ramp("#7d6b5a", 5) + ramp("#4f7fbf", 4)},
}


def catalog() -> list[dict[str, Any]]:
    return [{"id": key, "label": spec["label"], "colors": list(spec["colors"])} for key, spec in BUILTIN.items()]


def resolve(value: Any) -> list[str]:
    """Nom d'une palette intégrée, ou liste de couleurs « #rrggbb »."""
    if isinstance(value, str):
        if value not in BUILTIN:
            raise ValueError(f"palette inconnue : {value!r} (intégrées : {', '.join(BUILTIN)})")
        return list(BUILTIN[value]["colors"])
    if not isinstance(value, list) or not value:
        raise ValueError("palette attendue : nom intégré ou liste de couleurs")
    if len(value) > MAX_COLORS:
        raise ValueError(f"{MAX_COLORS} couleurs au plus")
    return [check_hex(c) for c in value]


def from_image(data: bytes, count: int = 16) -> list[str]:
    """Palette de `count` couleurs tirée d'une image (pixels transparents ignorés), triée par luminosité."""
    from PIL import Image

    if not 2 <= int(count) <= MAX_COLORS:
        raise ValueError(f"de 2 à {MAX_COLORS} couleurs")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 — fichier illisible pour Pillow
        raise ValueError(f"image illisible ({type(exc).__name__})") from None
    image = image.convert("RGBA")
    image.thumbnail((256, 256))
    pixels = [p[:3] for p in image.getdata() if p[3] >= 128]
    if not pixels:
        raise ValueError("image entièrement transparente")
    opaque = Image.new("RGB", (len(pixels), 1))
    opaque.putdata(pixels)
    quantized = opaque.quantize(colors=int(count), method=Image.Quantize.MEDIANCUT)
    raw = quantized.getpalette()[: 3 * len(set(quantized.getdata()))]
    colors = {hex_of(*raw[i:i + 3]) for i in range(0, len(raw), 3)}
    return sorted(colors, key=lambda c: sum(w * v for w, v in zip((0.299, 0.587, 0.114), rgb_of(c), strict=True)))
