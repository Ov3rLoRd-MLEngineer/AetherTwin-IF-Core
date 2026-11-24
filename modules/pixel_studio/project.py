"""Projets du studio pixel : format, contrôle, assemblage des calques, exports (Pillow).

Un projet est un JSON (`.aether-pixel`) :

    {"format": "aether-pixel", "version": 1, "name": "fuma", "width": 32, "height": 32,
     "palette": ["#0e1116", …],
     "layers": [{"name": "Fond", "visible": true, "opacity": 1.0}, …],      # du bas vers le haut
     "frames": [{"duration": 120, "cels": ["<PNG base64>" | null, …]}, …],  # une case par calque
     "tilemap": {"cols": 20, "rows": 12, "ground": [-1, 3, …], "decor": [...], "solid": [0, 1, …]}}

Chaque case (`cel`) est une image PNG RGBA de la taille du projet, encodée en base64 : compact, et lisible par la
page comme par Pillow. La carte en tuiles utilise les images du projet comme tuiles (indice d'image, -1 = vide) ;
deux couches (sol, décor) et un drapeau « bloquant » par case pour les jeux.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Any

from modules.pixel_studio.palettes import check_hex

FORMAT = "aether-pixel"
MAX_SIDE = 512
MAX_LAYERS = 32
MAX_FRAMES = 256
MAX_MAP = 128
MAX_FILE = 40_000_000
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def clean_name(value: Any) -> str:
    """Nom de fichier sûr : minuscules, chiffres, « _ » et « - » (accents et espaces convertis)."""
    import unicodedata

    text = str(value or "").lower()
    for ligature, plain in (("œ", "oe"), ("æ", "ae"), ("ß", "ss")):
        text = text.replace(ligature, plain)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9_-]+", "_", text).strip("_-")[:40]
    if not NAME.match(text):
        raise ValueError("nom de projet vide ou invalide (lettres, chiffres, « _ », « - »)")
    return text


def _image():
    from PIL import Image

    return Image


def png_b64(image: Any) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def decode_png(data: str, size: tuple[int, int]) -> Any:
    Image = _image()
    try:
        raw = base64.b64decode(str(data).split(",")[-1], validate=True)
        image = Image.open(io.BytesIO(raw))
        if image.format != "PNG":
            raise ValueError("pas un PNG")
        image.load()
    except Exception as exc:  # noqa: BLE001 — donnée invalide : message lisible
        raise ValueError(f"image de calque illisible ({type(exc).__name__})") from None
    if image.size != size:
        raise ValueError(f"image de calque de {image.size[0]}×{image.size[1]}, attendu {size[0]}×{size[1]}")
    return image.convert("RGBA")


def blank(width: int, height: int) -> Any:
    return _image().new("RGBA", (width, height), (0, 0, 0, 0))


def validate(doc: Any) -> dict[str, Any]:
    """Contrôle complet d'un projet reçu de la page ou d'un fichier ; rend une copie normalisée."""
    if not isinstance(doc, dict) or doc.get("format", FORMAT) != FORMAT:
        raise ValueError("projet invalide (format « aether-pixel » attendu)")
    try:
        width, height = int(doc["width"]), int(doc["height"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("largeur et hauteur attendues") from None
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise ValueError(f"taille de 1 à {MAX_SIDE} pixels de côté")
    palette = [check_hex(c) for c in (doc.get("palette") or [])][:256]
    layers_in = doc.get("layers") or [{"name": "Calque 1"}]
    if not isinstance(layers_in, list) or not 1 <= len(layers_in) <= MAX_LAYERS:
        raise ValueError(f"de 1 à {MAX_LAYERS} calques")
    layers = []
    for i, layer in enumerate(layers_in):
        layer = layer if isinstance(layer, dict) else {}
        opacity = float(layer.get("opacity", 1.0))
        layers.append({"name": str(layer.get("name") or f"Calque {i + 1}")[:40],
                       "visible": bool(layer.get("visible", True)), "opacity": max(0.0, min(1.0, opacity))})
    frames_in = doc.get("frames") or [{}]
    if not isinstance(frames_in, list) or not 1 <= len(frames_in) <= MAX_FRAMES:
        raise ValueError(f"de 1 à {MAX_FRAMES} images")
    if width * height * len(layers) * len(frames_in) > 64_000_000:
        raise ValueError("projet trop lourd (taille × calques × images)")
    frames = []
    for frame in frames_in:
        frame = frame if isinstance(frame, dict) else {}
        cels = list(frame.get("cels") or [])
        cels = (cels + [None] * len(layers))[:len(layers)]
        for cel in cels:
            if cel is not None:
                decode_png(cel, (width, height))
        duration = int(frame.get("duration", 100))
        frames.append({"duration": max(10, min(10_000, duration)),
                       "cels": [str(c).split(",")[-1] if c is not None else None for c in cels]})
    out = {"format": FORMAT, "version": 1, "name": str(doc.get("name") or "sans_nom")[:40], "width": width,
           "height": height, "palette": palette, "layers": layers, "frames": frames}
    tilemap = doc.get("tilemap")
    if isinstance(tilemap, dict):
        out["tilemap"] = _validate_map(tilemap, len(frames))
    return out


def _validate_map(tilemap: dict[str, Any], frame_count: int) -> dict[str, Any]:
    cols, rows = int(tilemap.get("cols", 16)), int(tilemap.get("rows", 12))
    if not (1 <= cols <= MAX_MAP and 1 <= rows <= MAX_MAP):
        raise ValueError(f"carte de 1 à {MAX_MAP} cases de côté")
    out: dict[str, Any] = {"cols": cols, "rows": rows}
    for key in ("ground", "decor"):
        cells = list(tilemap.get(key) or [])
        cells = (cells + [-1] * (cols * rows))[:cols * rows]
        out[key] = [int(c) if isinstance(c, int | float) and 0 <= int(c) < frame_count else -1 for c in cells]
    solid = list(tilemap.get("solid") or [])
    out["solid"] = [1 if s else 0 for s in (solid + [0] * (cols * rows))[:cols * rows]]
    return out


def new_project(name: str, width: int, height: int, palette: list[str], frames: int = 1) -> dict[str, Any]:
    return validate({"name": name, "width": width, "height": height, "palette": palette,
                     "layers": [{"name": "Calque 1"}], "frames": [{"cels": [None]} for _ in range(frames)]})


# ---------- assemblage et exports ----------
def compose(doc: dict[str, Any], index: int) -> Any:
    """Image d'une image (frame) : calques visibles superposés, avec leur opacité."""
    Image = _image()
    size = (doc["width"], doc["height"])
    out = blank(*size)
    for layer, cel in zip(doc["layers"], doc["frames"][index]["cels"], strict=True):
        if not layer["visible"] or cel is None:
            continue
        image = decode_png(cel, size)
        if layer["opacity"] < 1:
            alpha = image.getchannel("A").point(lambda a, o=layer["opacity"]: round(a * o))
            image.putalpha(alpha)
        out = Image.alpha_composite(out, image)
    return out


def scaled(image: Any, scale: int) -> Any:
    scale = max(1, min(int(scale), 32))
    if scale == 1:
        return image
    return image.resize((image.width * scale, image.height * scale), _image().Resampling.NEAREST)


def to_png(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def export_png(doc: dict[str, Any], frame: int = 0, scale: int = 1) -> bytes:
    if not 0 <= int(frame) < len(doc["frames"]):
        raise ValueError("image inexistante")
    return to_png(scaled(compose(doc, int(frame)), scale))


def export_sheet(doc: dict[str, Any], scale: int = 1, columns: int = 0) -> tuple[bytes, dict[str, Any]]:
    """Planche de sprites (images côte à côte, `columns` par ligne ; 0 = une seule ligne) et sa description."""
    count = len(doc["frames"])
    columns = count if columns <= 0 else min(int(columns), count)
    rows = -(-count // columns)
    w, h = doc["width"], doc["height"]
    sheet = blank(w * columns, h * rows)
    for i in range(count):
        sheet.paste(compose(doc, i), ((i % columns) * w, (i // columns) * h))
    meta = {"image": f"{doc['name']}.png", "frame_width": w * max(1, int(scale)),
            "frame_height": h * max(1, int(scale)), "columns": columns, "rows": rows, "frames": count,
            "durations": [f["duration"] for f in doc["frames"]]}
    return to_png(scaled(sheet, scale)), meta


def export_gif(doc: dict[str, Any], scale: int = 1) -> bytes:
    """GIF animé en boucle ; les pixels à moins de 50 % d'opacité deviennent transparents."""
    Image = _image()
    images = [scaled(compose(doc, i), scale) for i in range(len(doc["frames"]))]
    colors: dict[tuple[int, int, int], int] = {}
    for image in images:
        for r, g, b, a in image.getdata():
            if a >= 128 and (r, g, b) not in colors:
                colors[(r, g, b)] = len(colors)
                if len(colors) > 255:
                    break
    frames = []
    if len(colors) <= 255:  # palette exacte, indice 255 = transparent
        flat = [v for color in colors for v in color] + [0, 0, 0] * (256 - len(colors))
        for image in images:
            p = Image.new("P", image.size)
            p.putpalette(flat)
            p.putdata([colors[(r, g, b)] if a >= 128 else 255 for r, g, b, a in image.getdata()])
            frames.append(p)
    else:  # trop de couleurs : quantification par image
        for image in images:
            p = image.convert("RGB").quantize(colors=255)
            mask = image.getchannel("A").point(lambda a: 255 if a < 128 else 0)
            p.paste(255, mask=mask)
            frames.append(p)
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], loop=0, disposal=2,
                   transparency=255, duration=[f["duration"] for f in doc["frames"]], optimize=False)
    return buffer.getvalue()


def export_map(doc: dict[str, Any], scale: int = 1) -> tuple[bytes, dict[str, Any]]:
    """Image de la carte (sol puis décor, images du projet comme tuiles) et sa description (cases, blocages)."""
    tilemap = doc.get("tilemap")
    if not tilemap:
        raise ValueError("ce projet n'a pas de carte")
    w, h, cols, rows = doc["width"], doc["height"], tilemap["cols"], tilemap["rows"]
    tiles = [compose(doc, i) for i in range(len(doc["frames"]))]
    image = blank(cols * w, rows * h)
    for key in ("ground", "decor"):  # le décor par-dessus le sol
        for i, t in enumerate(tilemap[key]):
            if t >= 0:
                image.alpha_composite(tiles[t], ((i % cols) * w, (i // cols) * h))
    meta = {"image": f"{doc['name']}_carte.png", "cols": cols, "rows": rows, "tile_width": w * max(1, int(scale)),
            "tile_height": h * max(1, int(scale)), "ground": tilemap["ground"], "decor": tilemap["decor"],
            "solid": tilemap["solid"]}
    return to_png(scaled(image, scale)), meta


# ---------- texte <-> pixels (outils des agents) ----------
SYMBOLS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def from_rows(rows: list[str], palette: list[str], width: int, height: int) -> Any:
    """Image depuis une grille de texte : « . » transparent, puis 0-9, a-z, A-Z = indices de la palette."""
    if not isinstance(rows, list) or len(rows) != height:
        raise ValueError(f"{height} lignes attendues, {len(rows) if isinstance(rows, list) else 0} reçues")
    image = blank(width, height)
    pixels = image.load()
    for y, row in enumerate(rows):
        row = str(row)
        if len(row) != width:
            raise ValueError(f"ligne {y + 1} : {width} caractères attendus, {len(row)} reçus")
        for x, char in enumerate(row):
            if char in ". ":
                continue
            index = SYMBOLS.find(char)
            if index < 0 or index >= len(palette):
                raise ValueError(f"ligne {y + 1}, colonne {x + 1} : « {char} » n'est pas un indice de la palette "
                                 f"(0 à {SYMBOLS[len(palette) - 1]})")
            r, g, b = (int(palette[index][k:k + 2], 16) for k in (1, 3, 5))
            pixels[x, y] = (r, g, b, 255)
    return image


def to_rows(image: Any, palette: list[str]) -> tuple[list[str], list[str]]:
    """Grille de texte d'une image ; les couleurs hors palette y sont ajoutées (64 symboles au plus)."""
    colors = list(palette)
    lookup = {tuple(int(c[k:k + 2], 16) for k in (1, 3, 5)): i for i, c in enumerate(colors)}
    rows = []
    for y in range(image.height):
        line = []
        for x in range(image.width):
            r, g, b, a = image.getpixel((x, y))
            if a < 128:
                line.append(".")
                continue
            if (r, g, b) not in lookup:
                if len(colors) >= len(SYMBOLS):
                    raise ValueError("plus de 62 couleurs : grille de texte impossible")
                lookup[(r, g, b)] = len(colors)
                colors.append(f"#{r:02x}{g:02x}{b:02x}")
            line.append(SYMBOLS[lookup[(r, g, b)]])
        rows.append("".join(line))
    return rows, colors


# ---------- stockage ----------
class ProjectStore:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    def path(self, name: str) -> Path:
        return self.folder / f"{clean_name(name)}.aether-pixel"

    def list(self) -> list[dict[str, Any]]:
        out = []
        if not self.folder.is_dir():
            return out
        for path in sorted(self.folder.glob("*.aether-pixel"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                thumb = png_b64(compose(validate(doc), 0)) if doc["width"] * doc["height"] <= 128 * 128 else None
                out.append({"name": path.stem, "width": doc["width"], "height": doc["height"],
                            "frames": len(doc["frames"]), "layers": len(doc["layers"]),
                            "map": bool(doc.get("tilemap")), "updated": path.stat().st_mtime, "thumb": thumb})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return out

    def load(self, name: str) -> dict[str, Any]:
        path = self.path(name)
        if not path.is_file():
            raise ValueError(f"projet introuvable : {name}")
        return validate(json.loads(path.read_text(encoding="utf-8")))

    def save(self, doc: dict[str, Any]) -> dict[str, Any]:
        doc = validate(doc)
        doc["name"] = clean_name(doc["name"])
        text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        if len(text) > MAX_FILE:
            raise ValueError("projet de plus de 40 Mo")
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.path(doc["name"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return {"name": doc["name"], "saved": time.time(), "bytes": len(text)}

    def delete(self, name: str) -> bool:
        path = self.path(name)
        if not path.is_file():
            return False
        path.unlink()
        return True
