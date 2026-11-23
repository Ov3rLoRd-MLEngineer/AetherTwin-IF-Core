"""Identifiants Battle.net : conservés d'un lancement à l'autre (perdus avant le 23/11 : toute clé absente des
valeurs par défaut était jetée au chargement), et réglables dans Paramètres généraux > Jeu."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pygame


def test_bnet_credentials_survive_a_restart(tmp_path: Path) -> None:
    import settings as settings_mod

    path = str(tmp_path / "settings.json")
    first = settings_mod.Settings(path)
    first.set("bnet.client_id", "identifiant")
    first.set("bnet.client_secret", "secret")
    first.set("futur.option", 3)          # clé inconnue des valeurs par défaut : gardée elle aussi
    first.save()
    second = settings_mod.Settings(path)  # nouveau lancement
    assert second.get("bnet.client_id") == "identifiant" and second.get("bnet.client_secret") == "secret"
    assert second.get("futur.option") == 3
    second.save()                         # un enregistrement suivant ne les efface pas
    stored = json.loads(Path(path).read_text(encoding="utf-8"))
    assert stored["bnet"]["client_secret"] == "secret"


def test_bnet_settings_on_the_game_page(app) -> None:
    app.open_settings("game")
    app.inputs["bn_id"], app.inputs["bn_secret"] = "abc", "def"
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    if os.environ.get("AETHERTWIN_SHOTS"):
        pygame.image.save(app.screen, str(Path(os.environ["AETHERTWIN_SHOTS"]) / "settings_game_bnet.png"))
    app._apply_settings_inputs(True)      # « Enregistrer » du bas de la fenêtre
    assert app.settings.get("bnet.client_id") == "abc" and app.settings.get("bnet.client_secret") == "def"


def test_credentials_are_shared_by_every_copy_of_the_app(tmp_path: Path) -> None:
    """Le dossier de l'appli recopié ailleurs (dossier Hermes) retrouve les identifiants : profil Windows."""
    import settings as settings_mod

    shared = str(tmp_path / "profil" / "shared.json")
    repo = settings_mod.Settings(str(tmp_path / "repo.json"), shared_path=shared)
    repo.set("bnet.client_id", "identifiant")
    repo.set("bnet.client_secret", "secret")
    assert repo.save()
    copy = settings_mod.Settings(str(tmp_path / "copie.json"), shared_path=shared)   # copie sans ses identifiants
    assert copy.get("bnet.client_id") == "identifiant" and copy.get("bnet.client_secret") == "secret"
    copy.set("app.pos", [1, 2])
    assert copy.save()                                   # la fermeture de la copie ne les efface pas
    assert settings_mod.Settings(str(tmp_path / "copie.json"), shared_path=shared).get("bnet.client_secret")
    copy.set("bnet.client_secret", "")                   # « × » : effacé partout
    assert copy.save()
    assert json.loads(Path(shared).read_text(encoding="utf-8"))["bnet.client_secret"] == ""
    assert not settings_mod.Settings(str(tmp_path / "autre.json"), shared_path=shared).get("bnet.client_secret")
    # chemin d'essai (tests) : jamais le profil de l'utilisateur
    assert settings_mod.Settings(str(tmp_path / "t.json")).shared_path == ""
