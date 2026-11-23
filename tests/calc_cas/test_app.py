"""calc_cas, fenêtre de bureau : choix du navigateur, ligne de commande sans shell, page servie par le Hub,
aucune ressource externe, déclaration dans le manifeste."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.module_api import load_manifest
from modules.calc_cas import app

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "core" / "web"


def test_manifest_declares_the_window() -> None:
    manifest = load_manifest(ROOT / "modules" / "calc_cas")
    assert manifest.app == ("Calculatrice Æther CAS", "modules.calc_cas.app")


def test_find_browser_takes_the_first_existing(tmp_path: Path) -> None:
    edge = tmp_path / "edge.exe"
    assert app.find_browser((str(tmp_path / "absent.exe"),)) is None
    edge.write_bytes(b"")
    assert app.find_browser((str(tmp_path / "absent.exe"), str(edge))) == str(edge)
    assert app.find_browser((r"%VARIABLE_QUI_N_EXISTE_PAS%\x.exe",)) is None


def test_browser_args_open_an_isolated_app_window(tmp_path: Path) -> None:
    args = app.browser_args("msedge.exe", "http://127.0.0.1:5750/static/calc_app.html", tmp_path)
    assert args[0] == "msedge.exe" and "--app=http://127.0.0.1:5750/static/calc_app.html" in args
    assert f"--user-data-dir={tmp_path}" in args and any(a.startswith("--window-size=") for a in args)


def test_hub_url_follows_the_daemon_port(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import config

    monkeypatch.setattr(config, "section", lambda name, path=None: {"port": 5761} if name == "daemon" else {})
    assert app.hub_url() == "http://127.0.0.1:5761/static/calc_app.html"
    monkeypatch.setattr(config, "section", lambda name, path=None: (_ for _ in ()).throw(OSError("absent")))
    assert app.hub_url().endswith(":5750/static/calc_app.html")


def test_main_falls_back_to_default_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(app, "find_browser", lambda: None)
    monkeypatch.setattr(app.webbrowser, "open", opened.append)
    assert app.main() == 0 and opened and opened[0].endswith("/static/calc_app.html")


def test_window_page_is_self_contained() -> None:
    page = (WEB / "calc_app.html").read_text(encoding="utf-8")
    script = (WEB / "calc_app.js").read_text(encoding="utf-8")
    style = (WEB / "calc_app.css").read_text(encoding="utf-8")
    assert "/static/calc_app.js" in page and "/static/calc_app.css" in page
    assert " style=" not in page  # la CSP du Hub refuse les styles en ligne
    for text in (page, script, style):  # ni CDN, ni police distante
        assert not re.search(r"https?://(?!127\.0\.0\.1)", text)
    ids = set(re.findall(r'\$\("([\w-]+)"\)', script))
    missing = sorted(i for i in ids if f'id="{i}"' not in page)
    assert not missing, f"identifiants absents de la page : {missing}"
    assert "Texas" not in page + script and "Nspire" not in page + script  # identité propre


def test_window_files_are_served_by_the_hub(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from core.api import create_app
    from core.daemon import Daemon
    from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
    from core.llm_router import LlmRouter
    from tests.core.test_daemon import ollama_stopped

    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    client = TestClient(create_app(daemon))
    for name, kind in (("calc_app.html", "text/html"), ("calc_app.css", "text/css"), ("calc_app.js", "javascript")):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200 and kind in response.headers["content-type"]
