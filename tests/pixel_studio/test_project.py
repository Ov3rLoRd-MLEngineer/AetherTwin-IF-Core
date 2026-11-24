"""pixel_studio : palettes, contrôle des projets, stockage, exports (PNG, planche, GIF, carte), grilles de texte."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from modules.pixel_studio import palettes, project

Image = pytest.importorskip("PIL.Image")

HEART = [".cc.cc.", "ccccccc", "ccccccc", ".ccccc.", "..ccc..", "...c..."]
PAL = palettes.resolve("aether16")


def heart_doc(frames: int = 2, **extra) -> dict:
    cels = [project.png_b64(project.from_rows(HEART, PAL, 7, 6)), None]
    doc = {"name": "Cœur rouge", "width": 7, "height": 6, "palette": PAL,
           "layers": [{"name": "Fond"}, {"name": "Haut", "visible": False, "opacity": 0.5}],
           "frames": [{"duration": 120 + 10 * i, "cels": list(cels)} for i in range(frames)], **extra}
    return project.validate(doc)


def test_palettes() -> None:
    assert palettes.check_hex("#ABC") == "#aabbcc"
    with pytest.raises(ValueError):
        palettes.check_hex("rouge")
    ramp = palettes.ramp("#c0703a", 5)
    assert len(ramp) == 5 and ramp[2] == "#c0703a"
    lum = [sum(palettes.rgb_of(c)) for c in ramp]
    assert lum == sorted(lum)  # de l'ombre à la lumière
    assert {p["id"] for p in palettes.catalog()} >= {"aether16", "aether32", "chats", "console4"}
    assert len(palettes.resolve("aether32")) == 32
    with pytest.raises(ValueError, match="inconnue"):
        palettes.resolve("nes")
    image = Image.new("RGBA", (4, 1))
    image.putdata([(255, 0, 0, 255), (0, 0, 255, 255), (0, 0, 255, 255), (0, 0, 0, 0)])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    assert palettes.from_image(buffer.getvalue(), 4) == ["#0000ff", "#ff0000"]  # transparent ignoré, tri par luminosité
    with pytest.raises(ValueError, match="illisible"):
        palettes.from_image(b"pas une image")


def test_names_are_safe() -> None:
    assert project.clean_name("Cœur rouge !") == "coeur_rouge"
    assert project.clean_name("Écureuil-2") == "ecureuil-2"
    for bad in ("", "...", "../"):
        with pytest.raises(ValueError):
            project.clean_name(bad)


def test_validate_normalises_and_refuses() -> None:
    doc = heart_doc(tilemap={"cols": 3, "rows": 2, "ground": [0, 1, 9, "x"], "solid": [1, 0, 1]})
    assert doc["layers"][1] == {"name": "Haut", "visible": False, "opacity": 0.5}
    assert doc["tilemap"]["ground"] == [0, 1, -1, -1, -1, -1]  # indices hors des images → vide
    assert doc["tilemap"]["solid"] == [1, 0, 1, 0, 0, 0]
    for bad in ({"format": "autre"}, {"width": 0, "height": 4}, {"width": 600, "height": 4},
                {"width": 4, "height": 4, "layers": [{}] * 33}):
        with pytest.raises(ValueError):
            project.validate(bad)
    wrong_size = project.png_b64(project.blank(3, 3))
    with pytest.raises(ValueError, match="attendu 7×6"):
        project.validate({"width": 7, "height": 6, "frames": [{"cels": [wrong_size]}]})
    with pytest.raises(ValueError, match="illisible"):
        project.validate({"width": 7, "height": 6, "frames": [{"cels": ["pas du png"]}]})


def test_rows_roundtrip_and_errors() -> None:
    image = project.from_rows(HEART, PAL, 7, 6)
    assert image.getpixel((0, 0))[3] == 0 and image.getpixel((1, 0))[:3] == palettes.rgb_of(PAL[12])
    rows, colors = project.to_rows(image, PAL)
    assert rows == HEART and colors == PAL
    rows, colors = project.to_rows(image, ["#000000"])  # couleur hors palette : ajoutée
    assert colors == ["#000000", PAL[12]] and rows[1] == "1111111"
    with pytest.raises(ValueError, match="6 lignes"):
        project.from_rows(HEART[:2], PAL, 7, 6)
    with pytest.raises(ValueError, match="ligne 2 : 7 caractères"):
        project.from_rows([HEART[0], "cc", *HEART[2:]], PAL, 7, 6)
    with pytest.raises(ValueError, match="colonne 1"):
        project.from_rows(["z......", *HEART[1:]], PAL, 7, 6)


def test_compose_respects_visibility_and_opacity() -> None:
    doc = heart_doc(1)
    top = project.blank(7, 6)
    top.putpixel((0, 0), (255, 255, 255, 255))
    doc["frames"][0]["cels"][1] = project.png_b64(top)
    assert project.compose(doc, 0).getpixel((0, 0))[3] == 0  # calque du haut masqué
    doc["layers"][1]["visible"] = True
    assert project.compose(doc, 0).getpixel((0, 0)) == (255, 255, 255, 128)  # opacité 50 %


def test_exports() -> None:
    doc = heart_doc(3, tilemap={"cols": 4, "rows": 2, "ground": [0] * 8, "decor": [-1, 1], "solid": [1]})
    for i, frame in enumerate(doc["frames"]):  # images différentes (le GIF fusionne les images identiques)
        frame["cels"][0] = project.png_b64(project.from_rows([r.replace("c", "abc"[i]) for r in HEART], PAL, 7, 6))
    png = Image.open(io.BytesIO(project.export_png(doc, 1, 4)))
    assert png.size == (28, 24)
    with pytest.raises(ValueError):
        project.export_png(doc, 5)
    sheet, meta = project.export_sheet(doc, 2, 2)
    assert Image.open(io.BytesIO(sheet)).size == (28, 24)  # 2 colonnes × 2 lignes de 7×6, ×2
    assert meta["columns"] == 2 and meta["rows"] == 2 and meta["durations"] == [120, 130, 140]
    gif = Image.open(io.BytesIO(project.export_gif(doc, 2)))
    assert gif.format == "GIF" and gif.n_frames == 3 and gif.size == (14, 12) and gif.info["loop"] == 0
    assert gif.convert("RGBA").getpixel((0, 0))[3] == 0  # transparence gardée
    image, meta = project.export_map(doc, 1)
    assert Image.open(io.BytesIO(image)).size == (28, 12)
    assert meta["solid"][0] == 1 and meta["decor"][:2] == [-1, 1] and meta["tile_width"] == 7
    with pytest.raises(ValueError, match="pas de carte"):
        project.export_map(heart_doc(1))


def test_store(tmp_path: Path) -> None:
    store = project.ProjectStore(tmp_path / "projets")
    assert store.list() == []
    saved = store.save(heart_doc(2))
    assert saved["name"] == "coeur_rouge"
    path = tmp_path / "projets" / "coeur_rouge.aether-pixel"
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == "aether-pixel"
    listed = store.list()
    assert listed[0]["name"] == "coeur_rouge" and listed[0]["frames"] == 2 and listed[0]["thumb"]
    assert store.load("coeur_rouge")["layers"][0]["name"] == "Fond"
    (tmp_path / "projets" / "casse.aether-pixel").write_text("{", encoding="utf-8")
    assert [p["name"] for p in store.list()] == ["coeur_rouge"]  # fichier abîmé ignoré
    with pytest.raises(ValueError, match="introuvable"):
        store.load("absent")
    with pytest.raises(ValueError):
        store.load("../secret")
    assert store.delete("coeur_rouge") is True and store.delete("coeur_rouge") is False
