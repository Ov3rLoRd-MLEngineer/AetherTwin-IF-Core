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
def test_closing_the_main_window_asks_for_confirmation(app) -> None:
    close = pygame.event.Event(pygame.WINDOWCLOSE)  # SDL envoie ceci (et non QUIT) dès qu'il y a 2 fenêtres
    assert app.handle_events([close]) is True       # 1re demande : « Quitter WoW Assistant ? »
    assert app.modal["type"] == "quit"
    # un clic sur la croix = WINDOWCLOSE puis QUIT (vrai WM_CLOSE, vérifié le 23/11) : la question reste posée
    assert app.handle_events([pygame.event.Event(pygame.QUIT)]) is True and app.modal["type"] == "quit"
    assert app.handle_events([close, pygame.event.Event(pygame.QUIT)]) is True and app.modal["type"] == "quit"
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="")
    assert app.handle_events([enter]) is False                            # seul « Oui » / Entrée quitte


def test_quit_confirmation_no_restores_the_previous_window(app) -> None:
    app.modal = {"type": "compose-test"}
    assert app.handle_events([pygame.event.Event(pygame.QUIT)]) is True
    assert app.modal["type"] == "quit"
    app.close_modal()                                # « Non » / Échap
    assert app.modal == {"type": "compose-test"} and app._quit_now is False
    app.modal = None
    app.request_quit()
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="")
    assert app.handle_events([enter]) is False       # Entrée : oui


def test_closing_the_overlay_window_does_not_quit(app) -> None:
    if not app.open_overlay((900, 500), (0, 0)):
        pytest.skip(f"overlay indisponible en mode headless : {app.overlay_error}")
    close_overlay = pygame.event.Event(pygame.WINDOWCLOSE, window=app.overlay_win)
    assert app.handle_events([close_overlay]) is True and app.overlay_on is False
    # l'overlay est seulement masqué : la fenêtre principale doit toujours pouvoir se fermer (après confirmation)
    assert app.handle_events([pygame.event.Event(pygame.WINDOWCLOSE)]) is True and app.modal["type"] == "quit"
    app._quit_now = True                                                  # « Oui »
    assert app.handle_events([]) is False


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
    assert ui._handle_event(key(pygame.K_ESCAPE)) is False  # nouvel appui hors saisie : demande à quitter


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


# --------------------------------------------------------------------------- voix
def test_faster_whisper_never_receives_an_api_model_name(tmp_path: Path) -> None:
    import voice

    assert voice.faster_whisper_model("", "whisper-1") == "small"  # « whisper-1 » est un nom d'API : refusé
    assert voice.faster_whisper_model("medium", "whisper-1") == "medium"
    assert voice.faster_whisper_model("", "") == "small"
    assert voice.faster_whisper_model("", "Systran/faster-whisper-small") == "Systran/faster-whisper-small"
    assert voice.faster_whisper_model("", str(tmp_path)) == str(tmp_path)  # dossier de modèle local
    assert "whisper-1" not in voice.FASTER_WHISPER_MODELS


def test_missing_package_message_names_the_python_actually_running(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    import sys

    import settings as settings_mod
    import voice
    import webwidget

    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert f"py -{version} -m pip install pywebview" in webwidget.EXIT_MESSAGES[3]
    real_import = builtins.__import__

    def no_faster_whisper(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("absent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_faster_whisper)
    with pytest.raises(RuntimeError, match=rf"py -{version} -m pip install faster-whisper"):
        voice.Transcriber(settings_mod.Settings(path="inexistant.json"))._faster(b"")


def test_faster_whisper_model_is_chosen_with_buttons(app) -> None:
    app.settings.set("voice.stt.backend", "faster-whisper")
    app.open_settings("voice")
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    shot(app, "parametres_voice_faster_whisper")
    assert app.screen.cut == []
    assert app.settings.get("voice.stt.fw_model") == "small"  # valeur par défaut valide
    drawn_now = {k for k, v in app._input_rects.items() if v[2] == app._frame}
    assert "set_v_stt_model" not in drawn_now  # plus de champ libre où taper un nom de modèle invalide


def test_long_status_message_does_not_overlap_the_footer(app) -> None:
    app.open_settings("voice")
    app.modal["status"] = ("Invalid model size 'whisper-1', expected one of: tiny.en, tiny, base.en, base, "
                           "small.en, small, medium.en, medium, large-v1, large-v2, large-v3")
    app.modal["status_ok"] = False
    app.draw(app.test_ctx)
    app.screen.blits.clear()
    app.draw(app.test_ctx)
    shot(app, "parametres_voice_message_long")
    left_edge, bottom = (app.W - 960) // 2, (app.H - 780) // 2 + 780  # cadre de la fenêtre de paramètres
    row = sorted((r for r in app.screen.blits
                  if bottom - 62 <= r.y <= bottom - 36 and left_edge <= r.x <= left_edge + 960 and r.h < 30),
                 key=lambda r: r.x)
    assert len(row) >= 4  # « Enregistrer », « Fermer », le message, la mention de droite
    for left, right in zip(row, row[1:], strict=False):
        assert left.right <= right.left, f"deux textes se chevauchent en bas de la fenêtre : {left} / {right}"


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


def test_several_ai_servers_can_be_saved_toggled_and_queried(app, monkeypatch) -> None:
    """Plusieurs serveurs IA : liste enregistrée, actif / inactif, modèles de chaque serveur actif ; choisir un
    modèle sélectionne aussi son serveur (demande de Jérémy, 22/11)."""
    import llm
    import ui as ui_mod

    asked = []

    def fake_list(url, key=""):
        asked.append(url)
        return ({"http://127.0.0.1:5750": ["qwen3-27b:latest"], "http://127.0.0.1:11434/v1": ["llava:34b"]}
                .get(url, []), "" if "5750" in url or "11434" in url else "injoignable")

    monkeypatch.setattr(ui_mod, "list_models_at", fake_list)
    app.open_settings("llm")
    app.inputs["set_endpoint"] = "http://127.0.0.1:5750"
    app._add_server()
    app.inputs["set_endpoint"] = "http://127.0.0.1:11434/v1"
    app._add_server()
    app._add_server()  # déjà présent : pas de doublon
    app.inputs["set_endpoint"] = "http://127.0.0.1:9999"
    app._add_server()
    assert [s["url"] for s in app.settings.get("llm.servers")] == [
        "http://127.0.0.1:5750", "http://127.0.0.1:11434/v1", "http://127.0.0.1:9999"]
    app._toggle_server(2)  # le serveur 9999 n'est plus interrogé
    app.inputs["set_endpoint"] = "http://127.0.0.1:5750"
    app._load_models()
    while not app.modal["bg"]["done"]:
        pass
    app.draw(app.test_ctx)
    assert sorted(asked) == ["http://127.0.0.1:11434/v1", "http://127.0.0.1:5750"]
    assert ("llava:34b", "http://127.0.0.1:11434/v1", "") in app.modal["models"]
    assert "2 serveur(s)" in app.modal["status"]
    app.draw(app.test_ctx)
    shot(app, "settings_llm_servers")
    assert app.settings.get("llm.servers")[0]["provider"] == "Hub AetherTwin"
    assert "Ollama" in app.modal["providers"].values()
    app._cycle_provider(0)
    assert app.settings.get("llm.servers")[0]["provider"] == "Strata"
    app._use_server(1)
    assert app.inputs["set_endpoint"] == "http://127.0.0.1:11434/v1"
    app._remove_server(2)
    assert len(app.settings.get("llm.servers")) == 2
    assert llm.enabled_servers(app.settings, "http://127.0.0.1:5750/")[0]["url"] == "http://127.0.0.1:5750"


def test_strata_server_is_one_click_and_local(app) -> None:
    """Strata (moteur des gros modèles MoE, 23/11) : un bouton l'ajoute une seule fois, sur 127.0.0.1:8090."""
    import llm

    assert llm.guess_provider(llm.STRATA_ENDPOINT) == "Strata" and llm.STRATA_ENDPOINT.startswith("http://127.0.0.1:")
    assert llm.guess_provider("http://127.0.0.1:8080/v1") == "Open WebUI"
    app.open_settings("llm")
    app._add_strata()
    app._add_strata()
    servers = app.settings.get("llm.servers")
    assert servers == [{"url": llm.STRATA_ENDPOINT, "api_key": "", "enabled": True, "provider": "Strata"}]
    app.draw(app.test_ctx)
    shot(app, "settings_llm_strata")
