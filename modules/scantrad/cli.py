"""Construction de la chaîne et ligne de commande.

    python -m modules.scantrad PAGE.png --series demo --out traduite.png
    python -m modules.scantrad --screen 100,100,800,1200 --series demo      # capture d'une zone de l'écran
    python -m modules.scantrad PAGE.png --no-llm                             # détection + effacement seuls
    python -m modules.scantrad --glossary demo --add "ユキ=Yuki"              # enrichit le glossaire

Le Hub doit tourner pour l'OCR et la traduction (`Lancer AetherTwin.bat`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from modules.scantrad.detect import (
    clean_bubbles,
    clean_text,
    detect_bubbles,
    detect_text_blocks,
    upscale_small_page,
)
from modules.scantrad.hub_stages import Glossary, hub_chat, make_translator, make_vision_ocr
from modules.scantrad.pipeline import Scantrad
from modules.scantrad.typeset import make_typesetter

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = REPO_ROOT / "data" / "scantrad"


def series_slug(name: str) -> str:
    """Nom de fichier sûr pour une série (« Ma Série ! » → « ma-serie ») : aucun chemin ne peut en sortir."""
    plain = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9_-]+", "-", plain).strip("-")
    if not slug:
        raise ValueError("nom de série vide ou invalide")
    return slug[:60]


def glossary_for(series: str, data_dir: Path = DEFAULT_DATA) -> Glossary:
    return Glossary.load(data_dir / "glossaires" / f"{series_slug(series)}.json")


def vram_reader():
    try:
        from core.hardware.gpu_monitor import GpuMonitor

        monitor = GpuMonitor()
    except Exception:  # noqa: BLE001 — pas de mesure : le pipeline tourne quand même
        return lambda: None

    def used() -> int | None:
        gpus = monitor.snapshot()
        return sum(g.vram_used_mib for g in gpus) if gpus else None
    return used


def build(settings: dict[str, Any], series: str = "", use_llm: bool = True) -> Scantrad:
    chat = hub_chat(str(settings.get("hub_api", "http://127.0.0.1:5750")))
    glossary = glossary_for(series, Path(settings.get("data_dir") or DEFAULT_DATA)) if series else None
    closed_bubbles = settings.get("detector") == "bubbles"  # ancienne heuristique : bulles fermées sur fond gris
    return Scantrad(
        detect=detect_bubbles if closed_bubbles else detect_text_blocks,
        ocr=make_vision_ocr(chat, str(settings.get("ocr_model", "qwen2.5vl:7b"))) if use_llm else None,
        clean=clean_bubbles if closed_bubbles else clean_text,
        prepare=upscale_small_page,
        translate=make_translator(chat, glossary, str(settings.get("model", ""))) if use_llm else None,
        typeset=make_typesetter(str(settings.get("font", ""))),
        vram_used_mib=vram_reader(),
    )


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)  # imread ne lit pas les chemins accentués sous Windows
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"image illisible : {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"écriture impossible : {path}")
    encoded.tofile(str(path))


def capture_screen(region: str) -> np.ndarray:
    from PIL import ImageGrab

    x, y, w, h = (int(v) for v in region.split(","))
    shot = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    return cv2.cvtColor(np.asarray(shot.convert("RGB")), cv2.COLOR_RGB2BGR)


def main(argv: list[str] | None = None) -> int:
    from core import config

    parser = argparse.ArgumentParser(description="Traduction locale d'une page de manga (usage personnel).")
    parser.add_argument("page", nargs="?", type=Path, help="image de la page")
    parser.add_argument("--screen", help="capture d'écran x,y,largeur,hauteur au lieu d'un fichier")
    parser.add_argument("--series", default="", help="nom de la série (glossaire persistant)")
    parser.add_argument("--out", type=Path, help="image traduite (défaut : <page>_fr.png)")
    parser.add_argument("--no-llm", action="store_true", help="détection et effacement seulement")
    parser.add_argument("--glossary", help="série dont on modifie le glossaire")
    parser.add_argument("--add", action="append", default=[], metavar="JP=FR", help="entrée de glossaire")
    args = parser.parse_args(argv)
    settings = config.section("scantrad")

    if args.glossary:
        glossary = glossary_for(args.glossary, Path(settings.get("data_dir") or DEFAULT_DATA))
        for item in args.add:
            source, _, target = item.partition("=")
            if not source or not target:
                parser.error(f"entrée invalide : {item!r} (attendu JP=FR)")
            glossary.terms[source.strip()] = target.strip()
        glossary.save()
        print(json.dumps({"characters": glossary.characters, "terms": glossary.terms}, ensure_ascii=False, indent=1))
        return 0

    if args.screen:
        page, default_out = capture_screen(args.screen), DEFAULT_DATA / "capture_fr.png"
    elif args.page:
        page, default_out = read_image(args.page), args.page.with_name(args.page.stem + "_fr.png")
    else:
        parser.error("donne une image ou --screen")
    try:
        result = build(settings, args.series, use_llm=not args.no_llm).run(page)
    except urllib.error.URLError as exc:  # Hub arrêté (ou modèle refusé : 409 VRAM, 503 Ollama)
        print(f"Le Hub ne répond pas ou refuse la demande ({exc}). Lance AetherTwin (raccourci du bureau), "
              "ou utilise --no-llm pour la détection et l'effacement seuls.", file=sys.stderr)
        return 2
    out = args.out or default_out
    write_image(out, result.image)
    print(json.dumps({**result.summary(), "output": str(out)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
