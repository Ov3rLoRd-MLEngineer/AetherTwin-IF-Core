"""Dossiers et opérations partagés par le module du Hub et le serveur MCP : projets, exports, sprites des jeux.

    data/pixel_studio/projects/<nom>.aether-pixel    projets
    data/pixel_studio/exports/                       PNG, planches, GIF, cartes exportés
    data/pixel_studio/sprites/<nom>.png + .json      sprites prêts pour `jeu.sprite()` / `jeu.carte()` (calculatrice)

Le format d'un sprite de jeu : une planche d'une ligne (toutes les images côte à côte, taille réelle) et un JSON
`{"format": "aether-sprite", "frame_width", "frame_height", "frames", "durations", "map"?: {cols, rows, ground,
decor, solid}}`. La carte, si le projet en a une, utilise ces images comme tuiles.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from modules.pixel_studio import project

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "pixel_studio"
SPRITES_DIR = DATA_DIR / "sprites"
KINDS = ("png", "sheet", "gif", "map")


class Studio:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.store = project.ProjectStore(self.data_dir / "projects")
        self.exports = self.data_dir / "exports"
        self.sprites = self.data_dir / "sprites"

    def export(self, doc: dict[str, Any], kind: str, scale: int = 1, frame: int = 0,
               columns: int = 0) -> dict[str, Any]:
        """Exporte (fichier écrit dans `exports/`) et rend le contenu en base64 pour le téléchargement."""
        doc = project.validate(doc)
        name = project.clean_name(doc["name"])
        doc["name"] = name
        scale = max(1, min(int(scale), 32))
        meta: dict[str, Any] | None = None
        if kind == "png":
            data, mime = project.export_png(doc, int(frame), scale), "image/png"
            filename = f"{name}_{int(frame) + 1}.png"
        elif kind == "sheet":
            data, meta = project.export_sheet(doc, scale, int(columns))
            filename, mime = f"{name}_planche.png", "image/png"
            meta["image"] = filename
        elif kind == "gif":
            data, filename, mime = project.export_gif(doc, scale), f"{name}.gif", "image/gif"
        elif kind == "map":
            data, meta = project.export_map(doc, scale)
            filename, mime = meta["image"], "image/png"
        else:
            raise ValueError(f"export inconnu : {kind!r} ({', '.join(KINDS)})")
        self.exports.mkdir(parents=True, exist_ok=True)
        (self.exports / filename).write_bytes(data)
        out: dict[str, Any] = {"filename": filename, "mime": mime, "bytes": len(data),
                               "data": base64.b64encode(data).decode("ascii"), "path": str(self.exports / filename)}
        if meta is not None:
            meta_name = filename.rsplit(".", 1)[0] + ".json"
            (self.exports / meta_name).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            out["meta"] = meta
            out["meta_filename"] = meta_name
        return out

    def game_export(self, name: str) -> dict[str, Any]:
        """Écrit le sprite (et sa carte) d'un projet enregistré pour les jeux de la calculatrice."""
        doc = self.store.load(name)
        name = project.clean_name(doc["name"])
        sheet, meta = project.export_sheet(doc, 1, 0)
        info: dict[str, Any] = {"format": "aether-sprite", "version": 1, "frame_width": doc["width"],
                                "frame_height": doc["height"], "frames": meta["frames"],
                                "durations": meta["durations"]}
        if doc.get("tilemap"):
            info["map"] = {k: doc["tilemap"][k] for k in ("cols", "rows", "ground", "decor", "solid")}
        self.sprites.mkdir(parents=True, exist_ok=True)
        (self.sprites / f"{name}.png").write_bytes(sheet)
        (self.sprites / f"{name}.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        usage = f'jeu.sprite("{name}", x, y, echelle=2, image=0)'
        if "map" in info:
            usage += f' ; jeu.carte("{name}", 0, 0, echelle=2)'
        return {"name": name, "frames": info["frames"], "map": "map" in info, "usage": usage}
