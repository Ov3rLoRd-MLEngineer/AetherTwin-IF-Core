"""Aperçus des Collections (images Battle.net des montures et mascottes, icônes des objets, pièces des ensembles),
rendu du personnage recadré, et banque du personnage (addon 1.8 → onglet Sacs)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pygame

from tests.gaming_hud.test_market import FakeBnet, client


class CollectionsBnet(FakeBnet):
    """Ajoute à la fausse API les fiches de mascotte, de créature et d'ensemble."""

    def __call__(self, request, timeout=None):
        url = request.full_url
        if "/data/wow/pet/39" in url:
            self.urls.append(url)
            return self.reply({"id": 39, "creature": {"id": 2671}})
        if "/data/wow/creature/2671" in url:
            self.urls.append(url)
            return self.reply({"creature_displays": [{"id": 2404}]})
        if "/item-appearance/set/1000" in url:
            self.urls.append(url)
            return self.reply({"appearances": [{"id": 1}, {"id": 2}]})
        if "/item-appearance/1?" in url or "/item-appearance/2?" in url:
            self.urls.append(url)
            n = 1 if "/item-appearance/1?" in url else 2
            return self.reply({"slot": {"name": "Torse" if n == 1 else "Mains", "type": "CHEST" if n == 1 else "HAND"},
                               "item_display_info_id": 500 + n, "items": [{"id": 1000 + n, "name": f"Pièce {n}"}]})
        return super().__call__(request, timeout)


def test_pet_image_and_set_pieces_from_battle_net(tmp_path: Path) -> None:
    fake = CollectionsBnet()
    api = client(tmp_path, fake)
    path = api.pet_image(39)              # sans créature : lue dans la fiche de l'espèce
    assert path.endswith("pet_39.jpg") and any("/data/wow/pet/39" in u for u in fake.urls)
    fake.urls.clear()
    assert api.pet_image(39, 2671) == path  # créature exportée par l'addon : pas besoin de la fiche
    assert not any("/data/wow/pet/" in u for u in fake.urls)
    pieces = api.set_pieces(1000)
    assert pieces == [{"item": 1001, "name": "Pièce 1", "slot": "Torse", "slotType": "CHEST", "display": 501},
                      {"item": 1002, "name": "Pièce 2", "slot": "Mains", "slotType": "HAND", "display": 502}]


def test_transparent_margins_are_trimmed() -> None:
    from media import trim_transparent

    image = pygame.Surface((1600, 1200), pygame.SRCALPHA)
    pygame.draw.rect(image, (200, 100, 50, 255), (700, 300, 200, 600))
    trimmed = trim_transparent(image)
    assert 200 <= trimmed.get_width() <= 220 and 600 <= trimmed.get_height() <= 660
    opaque = pygame.Surface((300, 300))
    assert trim_transparent(opaque) is opaque


def _wait(cond, tries=60):
    for _ in range(tries):
        if cond():
            return True
        time.sleep(0.05)
    return False


def _shot(app, name):
    if os.environ.get("AETHERTWIN_SHOTS"):
        pygame.image.save(app.screen, str(Path(os.environ["AETHERTWIN_SHOTS"]) / name))


def _image(tmp_path: Path, name: str, size=(600, 600)) -> str:
    surf = pygame.Surface(size)
    surf.fill((30, 40, 70))
    pygame.draw.circle(surf, (170, 150, 210), (size[0] // 2, size[1] // 2), min(size) // 3)
    path = tmp_path / name
    pygame.image.save(surf, str(path))
    return str(path)


def test_every_collection_shows_a_preview_without_cut_text(app, tmp_path: Path) -> None:
    from media import MediaStore

    mount_png, pet_png = _image(tmp_path, "m.png"), _image(tmp_path, "p.png")

    class FakeApi:
        def configured(self):
            return True

        def mount_image(self, mount_id):
            return mount_png

        def pet_image(self, species, creature=0):
            assert creature == 2671
            return pet_png

        def set_pieces(self, set_id):
            slots = ("Tête", "Épaules", "Torse", "Mains", "Taille", "Jambes", "Pieds", "Poignets")
            return [{"item": 1000 + i, "name": f"Pièce {i}", "slot": s} for i, s in enumerate(slots)]

    app.media = MediaStore(FakeApi())
    data = app.test_ctx.data
    long_source = ("Vendeur : Eliza Killian Région : Couronne de glace Coût : 100"
                   "|TINTERFACE\\ICONS\\Ability_Paladin_ArtofW")
    data.mounts = {"updated": 0, "list": [{"id": 6, "spellID": 458, "name": "Cheval de guerre des Réprouvés",
                                            "collected": True, "source": long_source,
                                            "desc": "Lorsque les héros défunts sont relevés à la non-mort."}]}
    data.pets = {"updated": 0, "list": [{"id": 39, "name": "Écureuil mécanique", "owned": 1, "level": 25, "rarity": 4,
                                         "type": 10, "creature": 2671, "source": "Métier : Ingénierie",
                                         "desc": "Certains disent qu'ils aiment les pignons.", "battle": True}]}
    data.toys = {"updated": 0, "list": [{"id": 187344, "name": "Engin à kits d'offrandes", "owned": True,
                                         "quality": 3}]}
    data.heirlooms = {"updated": 0, "list": [{"id": 122349, "name": "Cotte de mailles", "owned": False,
                                              "slot": "INVTYPE_CHEST", "source": "Vendeur"}]}
    data.transmog = {"updated": 0, "setsUpdated": 0,
                     "cats": [{"id": 1, "name": "Tête", "weapon": False, "collected": 1, "total": 1}],
                     "items": {"1": [{"source": 7, "id": 50177, "name": "Heaume", "quality": 4, "classID": 4,
                                      "subClassID": 3, "equipLoc": "INVTYPE_HEAD"}]},
                     "sets": [{"id": 1000, "name": "Habits de seconde vue", "label": "Normal", "classMask": 0,
                               "expansion": 0, "have": 3, "total": 8}]}
    app.active_tab = app.TABS.index("Collections du bataillon")
    for view in ("mounts", "pets", "toys", "heirlooms", "transmog"):
        app.state["collection"] = view
        if view == "transmog":
            app.state["tm_sel"] = ("set", 1000)
        app.draw(app.test_ctx)
        key = {"mounts": "mount:6", "pets": "pet:39", "transmog": "set:1000"}.get(view)
        if key:
            assert _wait(lambda k=key: app.media.state(k) == "prête"), view
        app.screen.cut.clear()
        app.draw(app.test_ctx)
        assert app.screen.cut == [], view
        _shot(app, f"collections_{view}.png")
    app.state["tm_sel"] = ("item", 1, 7)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    _shot(app, "collections_transmog_item.png")


def test_character_render_is_cropped_to_the_frame(app, tmp_path: Path) -> None:
    from media import MediaStore

    image = pygame.Surface((1600, 1200), pygame.SRCALPHA)
    pygame.draw.ellipse(image, (200, 160, 90, 255), (700, 330, 220, 620))
    path = tmp_path / "render.png"
    pygame.image.save(image, str(path))

    class FakeApi:
        def configured(self):
            return True

        def character_render(self, realm, name):
            return str(path)

    app.media = MediaStore(FakeApi())
    app.test_ctx.character.realm = "Ysondre"
    app.active_tab = 0
    app.draw(app.test_ctx)
    assert _wait(lambda: app.media.state("char:Ysondre:Aeliana") == "prête")
    surface = app.media.surface("char:Ysondre:Aeliana")
    assert surface.get_height() < 700   # marges transparentes retirées : la silhouette remplit le cadre
    app.draw(app.test_ctx)
    _shot(app, "character_render_cropped.png")


def test_character_bank_in_the_bags_tab(app) -> None:
    from game_connection import _normalize_bank

    bank = _normalize_bank({"updated": 1, "money": 0, "tabs": {
        1: {"name": "Banque",
            "items": {1: {"id": 2589, "name": "Étoffe de lin", "count": 40, "quality": 1, "type": ""}}},
        2: {"name": "Composants", "items": {}}}})
    assert [t["name"] for t in bank["tabs"]] == ["Banque", "Composants"]
    app.test_ctx.data.characterBank = bank
    app.active_tab = app.TABS.index("Sacs")
    app.state["bag_view"] = "character"
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    _shot(app, "bags_character_bank.png")
    app.test_ctx.data.characterBank = {"updated": 0, "money": 0, "tabs": []}
    app.draw(app.test_ctx)   # jamais consultée : message, pas d'erreur


def test_transmog_try_on_sheet_applies_a_whole_set_and_fits_the_frame(app, tmp_path: Path) -> None:
    from media import MediaStore

    class FakeApi:
        def configured(self):
            return True

        def character_render(self, realm, name):
            return _image(tmp_path, "c.png")

        def set_pieces(self, set_id):
            kinds = ("HEAD", "SHOULDER", "CHEST", "HAND", "WAIST", "LEGS", "FEET", "WRIST")
            return [{"item": 1000 + i, "name": f"Pièce {i}", "slot": k, "slotType": k, "display": 500 + i}
                    for i, k in enumerate(kinds)]

    app.media = MediaStore(FakeApi())
    app.test_ctx.character.realm = "Ysondre"
    data = app.test_ctx.data
    data.transmog = {"updated": 0, "setsUpdated": 0,
                     "cats": [{"id": 1, "name": "Tête", "weapon": False, "collected": 1, "total": 1}],
                     "items": {"1": [{"source": 7, "id": 50177, "name": "Heaume", "quality": 4, "classID": 4,
                                      "subClassID": 3, "equipLoc": "INVTYPE_HEAD"}]},
                     "sets": [{"id": 1000, "name": "Habits de seconde vue", "label": "Normal", "classMask": 0,
                               "expansion": 0, "have": 3, "total": 8}]}
    app.active_tab = app.TABS.index("Collections du bataillon")
    app.state["collection"] = "transmog"
    app.state["tm_sel"] = ("set", 1000)
    app.draw(app.test_ctx)
    assert _wait(lambda: app.media.state("set:1000") == "prête")
    app.draw(app.test_ctx)
    assert sorted(app.state["tm_try"]) == [1, 3, 5, 6, 7, 8, 9, 10]      # l'ensemble entier est posé
    assert app.state["tm_try"][5]["display"] == 502
    app.state["tm_sel"] = ("item", 1, 7)                                  # une apparence : remplace la tête
    app.draw(app.test_ctx)
    assert app.state["tm_try"][1]["item"] == 50177 and len(app.state["tm_try"]) == 8
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    inside = [rect for rect, _fn in app._buttons if rect.top < app.BOTTOM and rect.w < app.W]   # (hors barre d'onglets)
    assert inside and all(rect.bottom <= app.BOTTOM - 4 for rect in inside), "rien ne déborde du cadre"
    _shot(app, "collections_transmog_tryon.png")
