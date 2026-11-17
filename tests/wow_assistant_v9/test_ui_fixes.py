"""Correctifs de WoW Assistant v9 : fermeture, saisie (répétition, curseur, presse-papier, clic droit), mise en page.

    AETHERTWIN_SHOTS=<dossier>  enregistre aussi une capture PNG de chaque écran rendu.
"""
from __future__ import annotations

import os
from pathlib import Path

import clipboard
import pygame
import pytest

SETTINGS_PAGES = ("game", "llm", "overlay", "widgets", "focus", "voice", "vision", "web")


def key(code: int, char: str = "", mod: int = 0):
    return pygame.event.Event(pygame.KEYDOWN, key=code, unicode=char, mod=mod)


def type_text(ui, text: str) -> None:
    for char in text:
        ui._handle_event(key(ord(char), char))
        ui._handle_event(pygame.event.Event(pygame.KEYUP, key=ord(char)))


def shot(ui, name: str) -> None:
    folder = os.environ.get("AETHERTWIN_SHOTS")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        pygame.image.save(ui.screen, str(Path(folder) / f"{name}.png"))


@pytest.fixture
def field(app):
    """Un champ de saisie avec la main, hors de toute modale."""
    app.inputs["champ"] = ""
    app.focus = "champ"
    app.input_box((100, 100, 300, 34), "champ", "…")
    return app


# --------------------------------------------------------------------------- fermeture de la fenêtre
def test_closing_the_main_window_quits_even_after_the_overlay_existed(app) -> None:
    close = pygame.event.Event(pygame.WINDOWCLOSE)  # SDL envoie ceci (et non QUIT) dès qu'il y a 2 fenêtres
    assert app.handle_events([close]) is False
    assert app.handle_events([pygame.event.Event(pygame.QUIT)]) is False


def test_closing_the_overlay_window_does_not_quit(app) -> None:
    if not app.open_overlay((900, 500), (0, 0)):
        pytest.skip(f"overlay indisponible en mode headless : {app.overlay_error}")
    close_overlay = pygame.event.Event(pygame.WINDOWCLOSE, window=app.overlay_win)
    assert app.handle_events([close_overlay]) is True and app.overlay_on is False
    # l'overlay est seulement masqué : la fenêtre principale doit toujours pouvoir se fermer
    assert app.handle_events([pygame.event.Event(pygame.WINDOWCLOSE)]) is False


# --------------------------------------------------------------------------- saisie
def test_typing_cursor_and_editing_keys(field) -> None:
    ui = field
    type_text(ui, "bonjour")
    assert ui.inputs["champ"] == "bonjour"
    ui._handle_event(key(pygame.K_HOME))
    type_text(ui, "x")
    assert ui.inputs["champ"] == "xbonjour"  # insertion à la position du curseur, plus seulement à la fin
    ui._handle_event(key(pygame.K_DELETE))
    assert ui.inputs["champ"] == "xonjour"
    ui._handle_event(key(pygame.K_END))
    ui._handle_event(key(pygame.K_LEFT))
    ui._handle_event(key(pygame.K_BACKSPACE))
    assert ui.inputs["champ"] == "xonjor"  # efface le « u », à gauche du curseur placé avant le « r »


def test_holding_a_key_repeats_it_inside_a_field(field) -> None:
    ui = field
    type_text(ui, "abcdef")
    for _ in range(4):  # touche maintenue : plusieurs KEYDOWN sans KEYUP
        ui._handle_event(key(pygame.K_BACKSPACE))
    assert ui.inputs["champ"] == "ab"
    assert pygame.key.get_repeat() == (400, 35)


def test_held_escape_does_not_quit_after_closing_a_field(field) -> None:
    ui = field
    assert ui._handle_event(key(pygame.K_ESCAPE)) is True and ui.focus is None  # 1er appui : ferme la saisie
    assert ui._handle_event(key(pygame.K_ESCAPE)) is True  # répétition de la touche maintenue : ignorée
    ui._handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_ESCAPE))
    assert ui._handle_event(key(pygame.K_ESCAPE)) is False  # nouvel appui hors saisie : Échap quitte, comme avant


def test_number_keys_do_not_repeat_tab_switches(app) -> None:
    switched = []
    app._switch_tab = switched.append
    for _ in range(3):
        app._handle_event(key(pygame.K_2, "2"))
    assert switched == [1]


def test_ctrl_a_c_x_v(field) -> None:
    ui = field
    previous = clipboard.get_text()
    try:
        type_text(ui, "texte à copier")
        ui._handle_event(key(pygame.K_c, "\x03", pygame.KMOD_LCTRL))
        assert clipboard.get_text() == "texte à copier" and ui.inputs["champ"] == "texte à copier"
        ui._handle_event(key(pygame.K_a, "\x01", pygame.KMOD_LCTRL))
        assert ui.select_all == "champ"
        type_text(ui, "Z")  # taper remplace la sélection
        assert ui.inputs["champ"] == "Z"
        ui._handle_event(key(pygame.K_v, "\x16", pygame.KMOD_LCTRL))
        assert ui.inputs["champ"] == "Ztexte à copier"
        ui._handle_event(key(pygame.K_x, "\x18", pygame.KMOD_LCTRL))
        assert ui.inputs["champ"] == "" and clipboard.get_text() == "Ztexte à copier"
        ui._handle_event(key(pygame.K_INSERT, "", pygame.KMOD_LSHIFT))  # Maj+Inser colle aussi
        assert ui.inputs["champ"] == "Ztexte à copier"
    finally:
        clipboard.set_text(previous)


def test_paste_is_cleaned_and_limited(field) -> None:
    ui = field
    previous = clipboard.get_text()
    try:
        clipboard.set_text("ligne 1\r\nligne 2\t" + "x" * 500)
        ui.edit_action("paste", "champ")
        assert "\n" not in ui.inputs["champ"] and "\t" not in ui.inputs["champ"]
        assert ui.inputs["champ"].startswith("ligne 1 ligne 2") and len(ui.inputs["champ"]) == 200
    finally:
        clipboard.set_text(previous)


def test_altgr_characters_are_typed_not_taken_as_shortcuts(field) -> None:
    ui = field
    altgr = pygame.KMOD_LCTRL | pygame.KMOD_RALT  # AltGr sous Windows
    ui._handle_event(key(pygame.K_0, "@", altgr))
    ui._handle_event(key(pygame.K_v, "v", 0))
    assert ui.inputs["champ"] == "@v"


def test_masked_field_is_never_copied(app) -> None:
    previous = clipboard.get_text()
    try:
        clipboard.set_text("avant")
        app.inputs["cle"] = "valeur-secrete"
        app.focus = "cle"
        app.input_box((100, 100, 300, 34), "cle", "…", mask=True)
        app._handle_event(key(pygame.K_c, "\x03", pygame.KMOD_LCTRL))
        app._handle_event(key(pygame.K_x, "\x18", pygame.KMOD_LCTRL))
        assert clipboard.get_text() == "avant" and app.inputs["cle"] == "valeur-secrete"
        app._handle_event(key(pygame.K_v, "\x16", pygame.KMOD_LCTRL))  # coller dans un champ masqué reste possible
        assert app.inputs["cle"] == "valeur-secreteavant"
    finally:
        clipboard.set_text(previous)


def test_long_text_scrolls_so_the_cursor_stays_visible(field) -> None:
    ui = field
    ui.inputs["champ"] = "m" * 150
    ui._caret = ("champ", 150)
    ui.screen.cut.clear()
    ui.input_box((100, 100, 300, 34), "champ", "…")
    assert ui._input_rects["champ"][3] > 0  # le début du texte a défilé
    assert ui.screen.cut == []  # et rien ne dépasse du champ


def test_right_click_menu_cut_copy_paste(app) -> None:
    ui = app
    previous = clipboard.get_text()
    try:
        ui.open_settings("llm")
        ui.draw(ui.test_ctx)
        name, (_win, rect, _frame, _start) = next((k, v) for k, v in ui._input_rects.items() if v[2] == ui._frame)
        ui.inputs[name] = "http://127.0.0.1:11434"
        right = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=rect.center)
        ui._handle_event(right)
        assert ui._menu and ui._menu["key"] == name and ui.focus == name
        ui.draw(ui.test_ctx)
        shot(ui, "menu_clic_droit")
        menu = ui._menu["rect"]

        def click_item(index: int) -> None:
            ui.draw(ui.test_ctx)
            pos = (ui._menu["rect"].x + 30, ui._menu["rect"].y + 4 + index * 28 + 14)
            ui._handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))

        click_item(1)  # Copier
        assert clipboard.get_text() == "http://127.0.0.1:11434" and ui._menu is None and ui.focus == name
        ui._handle_event(right)
        click_item(0)  # Couper
        assert ui.inputs[name] == ""
        ui._handle_event(right)
        click_item(2)  # Coller
        assert ui.inputs[name] == "http://127.0.0.1:11434"
        ui._handle_event(right)
        click_item(3)  # Tout sélectionner
        assert ui.select_all == name
        assert menu.right <= ui.W and menu.bottom <= ui.H
        # un clic droit ailleurs que sur un champ n'ouvre rien
        ui._handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(5, 5)))
        assert ui._menu is None
    finally:
        clipboard.set_text(previous)


def test_click_places_the_cursor(field) -> None:
    ui = field
    ui.inputs["champ"] = "abcdefgh"
    ui.input_box((100, 100, 300, 34), "champ", "…")
    width = ui.fonts["small"].size("abc")[0]
    ui._focus_input("champ", 100 + 8 + width + 1)
    assert ui._caret == ("champ", 3)


# --------------------------------------------------------------------------- clés API
@pytest.mark.parametrize(("page", "field_key", "path"), [("llm", "set_key", "llm.api_key"),
                                                         ("voice", "set_v_stt_key", "voice.stt.api_key")])
def test_clear_button_removes_the_api_key_from_the_settings_file(app, page: str, field_key: str, path: str) -> None:
    import json

    app.settings.set(path, "cle-de-test-a-effacer")
    app.settings.save()
    assert "cle-de-test-a-effacer" in Path(app.settings.path).read_text(encoding="utf-8")
    app.open_settings(page)
    app.draw(app.test_ctx)
    app.draw(app.test_ctx)
    _win, field_rect, _frame, _start = app._input_rects[field_key]
    button = next(rect for rect, _fn in app._buttons
                  if rect.y == field_rect.y and rect.x > field_rect.right and rect.w < 50)
    assert button.x - field_rect.right < 20  # le bouton « × » est collé au champ de la clé
    app._handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.center))
    assert app.inputs[field_key] == "" and app.settings.get(path, "") == ""
    stored = Path(app.settings.path).read_text(encoding="utf-8")
    assert "cle-de-test-a-effacer" not in stored and json.loads(stored)  # effacée du fichier, sans « Enregistrer »


# --------------------------------------------------------------------------- mise en page
@pytest.mark.parametrize("page", SETTINGS_PAGES)
def test_settings_pages_have_no_text_cut_or_overflowing(app, page: str) -> None:
    app.open_settings(page)
    app.draw(app.test_ctx)  # première image : mesure de la hauteur du contenu
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    shot(app, f"parametres_{page}")
    assert app.screen.cut == [], f"page « {page} » : éléments coupés horizontalement {app.screen.cut}"


def test_toolbar_shows_every_button_entirely(app) -> None:
    if not app.open_overlay((1280, 720), (0, 0)):
        pytest.skip(f"overlay indisponible en mode headless : {app.overlay_error}")
    spy = type(app.screen)((1280, 720))
    app._ctx_store["overlay"]["screen"] = spy
    app.draw_overlay(app.test_ctx)
    app.draw_overlay(app.test_ctx)  # la barre s'élargit à la première image si besoin
    spy.cut.clear()
    app.draw_overlay(app.test_ctx)
    folder = os.environ.get("AETHERTWIN_SHOTS")
    if folder:
        pygame.image.save(spy, str(Path(folder) / "overlay_barre.png"))
    bar = app.manager.layout["barre"]
    assert spy.cut == [], f"éléments coupés dans l'overlay : {spy.cut}"
    labels_right = max(rect.right for rect, _fn in app._ctx_store["overlay"]["_buttons"] if rect.y < bar["y"] + 40
                       and rect.y >= bar["y"])
    assert labels_right <= bar["x"] + bar["w"], "un bouton de la barre d'outils dépasse de la barre"
