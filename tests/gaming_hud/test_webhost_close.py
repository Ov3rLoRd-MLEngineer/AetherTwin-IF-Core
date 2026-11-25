"""Fermeture des widgets web (webhost.py) : rien ne doit viser une fenêtre étrangère, ni planter sans Windows / .NET."""
from __future__ import annotations

import webhost


def test_detach_unknown_title_does_nothing():
    assert webhost.detach_window("AetherTwin-titre-qui-n-existe-pas-7f3a") is False


def test_detach_and_guard_are_noops_off_windows(monkeypatch):
    monkeypatch.setattr(webhost.sys, "platform", "linux")
    assert webhost.detach_window("n'importe quoi") is False
    assert webhost.quiet_winforms_errors(object()) is False


def test_guard_without_dotnet_returns_false(monkeypatch):
    # Pas de fenêtre pywebview ni de .NET chargé : le garde-fou abandonne sans lever d'erreur.
    monkeypatch.setattr(webhost.sys, "platform", "win32")
    monkeypatch.setitem(webhost.sys.modules, "System", None)
    assert webhost.quiet_winforms_errors(object()) is False
