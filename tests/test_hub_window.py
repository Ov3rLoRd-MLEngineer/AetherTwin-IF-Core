"""Fenêtre du Hub et icône d'AetherTwin : lancement en mode application, repli sur le navigateur, icônes servies."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import app_window, daemon, hub_window

WEB = Path(__file__).resolve().parents[1] / "core" / "web"


def test_icons_exist_and_every_page_points_to_them() -> None:
    assert (WEB / "logo.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"  # en-tête ICO
    assert (WEB / "logo-256.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    for page in WEB.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert 'href="/static/logo-256.png"' in text, page.name


def test_app_args_open_an_isolated_window(tmp_path: Path) -> None:
    args = app_window.app_args("msedge.exe", "http://127.0.0.1:5750/", tmp_path, (1480, 960))
    assert args[:2] == ["msedge.exe", "--app=http://127.0.0.1:5750/"]
    assert f"--user-data-dir={tmp_path}" in args and "--window-size=1480,960" in args


def test_hub_window_falls_back_to_the_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(hub_window, "open_app", lambda *a, **k: None)
    monkeypatch.setattr(hub_window.webbrowser, "open", opened.append)
    assert hub_window.open_window(5761) is False
    assert opened == ["http://127.0.0.1:5761/"]


def test_hub_window_brands_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    class Proc:
        pid = 4242

    monkeypatch.setattr(hub_window, "open_app", lambda url, profile, size, app_id, name, command: Proc())
    monkeypatch.setattr(hub_window, "brand_window", lambda *a: calls.append(a) or 1)
    assert hub_window.open_window(5750) is True
    assert calls and calls[0][0] == 4242 and calls[0][1] == "AetherTwin.Hub"


def test_brand_window_is_harmless_without_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_window.sys, "platform", "linux")
    assert app_window.brand_window(1, "AetherTwin.Test", "AetherTwin", "x", timeout_s=0.1) == 0


def test_daemon_open_spawns_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[int] = []
    monkeypatch.setattr(hub_window, "spawn", spawned.append)
    daemon.open_dashboard(5750)
    assert spawned == [5750]


def test_favicon_and_png_are_served() -> None:
    from core.api import create_app

    client = TestClient(create_app(daemon.Daemon()))
    icon = client.get("/favicon.ico")
    assert icon.status_code == 200 and icon.headers["content-type"] == "image/x-icon"
    png = client.get("/static/logo-256.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    page = client.get("/").text
    assert re.search(r'id="btn-theme"', page) and "Aether<em>Twin</em>" in page
