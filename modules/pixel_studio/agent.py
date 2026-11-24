"""Le studio pixel comme outil des agents locaux : un modèle dessine un sprite en texte, le studio le range.

Même forme que la calculatrice (`TOOL_SPECS`, schémas « function calling ») : bus du Hub
(`module.pixel_studio.cmd.tool`) et serveur MCP stdio (`mcp_server.py`, nom `aethertwin_pixel` chez Hermes).

Un sprite s'écrit en **grille de texte** : une chaîne par ligne, « . » = transparent, puis `0-9`, `a-z`, `A-Z` =
indice de la couleur dans la palette. Exemple, un cœur 7×6 sur la palette « aether16 » (c = rouge) :

    [".cc.cc.", "ccccccc", "ccccccc", ".ccccc.", "..ccc..", "...c..."]

Le projet créé s'ouvre ensuite dans le studio comme les autres. Les outils ne lèvent jamais : erreur →
`{"ok": False, "error": …}` avec un message qui dit quoi corriger.
"""
from __future__ import annotations

from typing import Any

from modules.pixel_studio import palettes, project
from modules.pixel_studio.studio import Studio

MAX_AGENT_SIDE = 64
ROWS = {"type": "array", "items": {"type": "string"},
        "description": "Une chaîne par ligne de pixels : « . » transparent, 0-9 a-z A-Z = indice de la palette."}

TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "pixel_list_projects",
        "description": "Liste les projets du studio pixel d'AetherTwin (nom, taille, nombre d'images, carte).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "pixel_palettes",
        "description": "Palettes intégrées du studio (id, nom, couleurs « #rrggbb »). L'indice d'une couleur dans "
                       "la liste est son symbole dans les grilles de texte (0-9 puis a-z puis A-Z).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "pixel_make_palette",
        "description": "Rampe de couleurs pour le pixel art (de l'ombre à la lumière, avec glissement de teinte : "
                       "ombres vers le bleu-violet, lumières vers le jaune), autour d'une couleur de base.",
        "parameters": {"type": "object", "properties": {
            "base_color": {"type": "string", "description": "Couleur de base « #rrggbb »."},
            "count": {"type": "integer", "description": "Nombre de tons, 2 à 16 (5 par défaut)."}},
            "required": ["base_color"]}}},
    {"type": "function", "function": {
        "name": "pixel_create_sprite",
        "description": "Crée (ou remplace avec overwrite=true) un sprite dans le studio à partir de grilles de "
                       f"texte. {MAX_AGENT_SIDE}×{MAX_AGENT_SIDE} pixels au plus. Donne soit `rows` (une image), "
                       "soit `frames` (animation : liste de {rows, duration en ms}).",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Nom du projet (lettres, chiffres, « _ », « - »)."},
            "width": {"type": "integer"}, "height": {"type": "integer"},
            "palette": {"description": "Id d'une palette intégrée (ex. « aether16 ») ou liste de « #rrggbb ».",
                        "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
            "rows": ROWS,
            "frames": {"type": "array", "items": {"type": "object", "properties": {
                "rows": ROWS, "duration": {"type": "integer"}}, "required": ["rows"]}},
            "overwrite": {"type": "boolean", "description": "Remplacer un projet existant du même nom."}},
            "required": ["name", "width", "height", "palette"]}}},
    {"type": "function", "function": {
        "name": "pixel_read_sprite",
        "description": "Lit une image d'un projet en grille de texte (calques visibles superposés), avec sa "
                       "palette. Les couleurs hors palette sont ajoutées à la fin de la palette rendue.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "frame": {"type": "integer", "description": "Indice de l'image (0 = première)."}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "pixel_export_for_game",
        "description": "Prépare un projet pour les jeux Python de la calculatrice Æther CAS : ensuite "
                       "`jeu.sprite(nom, x, y, echelle, image)` le dessine, et `jeu.carte(nom, x, y, echelle)` "
                       "dessine sa carte en tuiles s'il en a une.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
]
TOOL_NAMES = {spec["function"]["name"] for spec in TOOL_SPECS}


def _create(studio: Studio, args: dict[str, Any]) -> dict[str, Any]:
    name = project.clean_name(args.get("name"))
    try:
        width, height = int(args.get("width", 0)), int(args.get("height", 0))
    except (TypeError, ValueError):
        raise ValueError("`width` et `height` entiers attendus") from None
    if not (1 <= width <= MAX_AGENT_SIDE and 1 <= height <= MAX_AGENT_SIDE):
        raise ValueError(f"taille de 1 à {MAX_AGENT_SIDE} pixels de côté pour un sprite d'agent")
    palette = palettes.resolve(args.get("palette", "aether16"))
    frames_in = args.get("frames")
    if frames_in is None:
        frames_in = [{"rows": args.get("rows")}]
    if not isinstance(frames_in, list) or not 1 <= len(frames_in) <= 64:
        raise ValueError("`frames` : de 1 à 64 images")
    if studio.store.path(name).is_file() and not args.get("overwrite"):
        raise ValueError(f"le projet « {name} » existe déjà (overwrite=true pour le remplacer)")
    frames = []
    for i, frame in enumerate(frames_in):
        frame = frame if isinstance(frame, dict) else {}
        try:
            image = project.from_rows(frame.get("rows"), palette, width, height)
        except ValueError as exc:
            raise ValueError(f"image {i + 1} : {exc}") from None
        frames.append({"duration": int(frame.get("duration", 120)), "cels": [project.png_b64(image)]})
    saved = studio.store.save({"name": name, "width": width, "height": height, "palette": palette,
                               "layers": [{"name": "Calque 1"}], "frames": frames})
    return {"ok": True, "name": saved["name"], "frames": len(frames),
            "message": "sprite créé ; il s'ouvre dans le studio pixel (onglet Outils du Hub)"}


def call_tool(studio: Studio, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Exécute un outil. Ne lève jamais : toute erreur devient `{"ok": False, "error": …}`."""
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if name not in TOOL_NAMES:
            raise ValueError(f"outil inconnu : {name!r} (outils : {', '.join(sorted(TOOL_NAMES))})")
        if name == "pixel_list_projects":
            result: dict[str, Any] = {"ok": True, "projects": [
                {k: p[k] for k in ("name", "width", "height", "frames", "layers", "map")} for p in studio.store.list()]}
        elif name == "pixel_palettes":
            result = {"ok": True, "palettes": palettes.catalog()}
        elif name == "pixel_make_palette":
            result = {"ok": True, "colors": palettes.ramp(str(args.get("base_color", "")), int(args.get("count", 5)))}
        elif name == "pixel_create_sprite":
            result = _create(studio, args)
        elif name == "pixel_read_sprite":
            doc = studio.store.load(project.clean_name(args.get("name")))
            frame = int(args.get("frame", 0))
            if not 0 <= frame < len(doc["frames"]):
                raise ValueError(f"image {frame} inexistante ({len(doc['frames'])} image(s), indices dès 0)")
            if doc["width"] > MAX_AGENT_SIDE or doc["height"] > MAX_AGENT_SIDE:
                raise ValueError(f"image de plus de {MAX_AGENT_SIDE} pixels de côté : trop grande pour du texte")
            rows, colors = project.to_rows(project.compose(doc, frame), doc["palette"])
            result = {"ok": True, "name": doc["name"], "width": doc["width"], "height": doc["height"],
                      "frames": len(doc["frames"]), "frame": frame, "palette": colors, "rows": rows}
        else:
            result = {"ok": True, **studio.game_export(project.clean_name(args.get("name")))}
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return {"ok": False, "tool": name, "error": str(exc) or type(exc).__name__}
    return {"tool": name, **result}
