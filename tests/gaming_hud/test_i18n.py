"""Version anglaise : catalogue, modèles des f-strings, et tous les onglets dessinés en anglais sans texte coupé."""
import json
import os
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "modules" / "gaming_hud" / "app"


@pytest.fixture
def english():
    import i18n
    i18n.load("en")
    yield i18n
    i18n.load("fr")


def test_exact_patterns_and_fallback(english) -> None:
    tr = english.tr
    assert tr("Sacs") == "Bags" and tr("Journal des quêtes") == "Quest log"
    assert tr("Montures — 12 obtenues / 340") == "Mounts — 12 collected / 340"
    assert tr("Quête : Loups") == "Quest: Loups"                       # valeur non traduite : nom du jeu
    assert tr("Remise à zéro dans 2 j 5 h") == "Reset in 2 d 5 h"          # valeur traduite à son tour
    assert tr("Nalorakk") == "Nalorakk" and tr("") == ""
    assert english.answer_note().strip() == "(Answer in English.)"
    english.load("fr")
    assert tr("Sacs") == "Sacs" and english.answer_note() == ""


def test_catalog_keeps_placeholders() -> None:
    catalog = json.loads((APP / "i18n_en.json").read_text(encoding="utf-8"))
    assert len(catalog) > 1000
    for fr, en in catalog.items():
        assert sorted(re.findall(r"\{\d+\}", fr)) == sorted(re.findall(r"\{\d+\}", en)), fr


def test_every_tab_in_english_without_cut_text(app, english) -> None:
    shots = os.environ.get("AETHERTWIN_SHOTS")
    for index, name in enumerate(app.TABS):
        app.active_tab = index
        for _ in range(2):
            app.screen.cut.clear()
            app.draw(app.test_ctx)
        assert app.screen.cut == [], name
        if shots and name in ("Personnage", "Semaine", "Hermes", "Hôtel des ventes", "Collections du bataillon"):
            import pygame
            Path(shots).mkdir(parents=True, exist_ok=True)
            pygame.image.save(app.screen, os.path.join(shots, f"en_{index}.png"))


def test_language_setting_is_saved(app) -> None:
    import i18n
    try:
        app.set_language("en")
        assert i18n.language() == "en" and app.settings.get("ui.language") == "en"
    finally:
        app.set_language("fr")
    assert i18n.language() == "fr"
