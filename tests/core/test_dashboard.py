"""Tableau de bord du Hub : fichiers servis, CSP stricte, aucun accès hors de `core/web/`."""
from __future__ import annotations

import pytest

from core.daemon import Daemon, port_in_use
from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
from core.llm_router import LlmRouter
from tests.core.test_daemon import ollama_stopped


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from core.api import create_app

    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    return TestClient(create_app(daemon))


def test_dashboard_page_and_assets(client) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "AetherTwin" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    for name, kind in (("dashboard.css", "text/css"), ("dashboard.js", "javascript"), ("logo.svg", "svg"),
                       ("ether_scene.js", "javascript")):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200 and kind in response.headers["content-type"]
    for script in ("dashboard.js", "ether_scene.js"):  # rien d'externe : ni CDN, ni police distante
        assert "http" not in client.get(f"/static/{script}").text.replace("http://127.0.0.1", "")
    assert "/static/ether_scene.js" in page.text


@pytest.mark.parametrize("path", ["/static/..%2Fapi.py", "/static/api.py", "/static/inconnu.css",
                                  "/static/..%2F..%2Fconfig%2Flocal.example.yaml"])
def test_static_refuses_other_files(client, path: str) -> None:
    assert client.get(path).status_code == 404


def test_dashboard_has_every_tab(client) -> None:
    page = client.get("/").text
    for tab in ("accueil", "jeu", "assistant", "professeur", "connaissances", "scantrad", "studio", "journal"):
        assert f'data-tab="{tab}"' in page and f'data-panel="{tab}"' in page
    assert "frame-src http://127.0.0.1:5757" in client.get("/").headers["content-security-policy"]


def make_app_hub(tmp_path):
    """Démon avec un module de démo qui déclare une application de bureau (la fausse appli `tests.core.sleeper`)."""
    import json

    from tests.core.test_daemon import make_modules

    root = make_modules(tmp_path / "modules")
    manifest = json.loads((root / "demo" / "manifest.json").read_text(encoding="utf-8"))
    manifest["app"] = {"label": "Démo", "module": "tests.core.sleeper"}
    (root / "demo" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return Daemon(root, monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                  llm=LlmRouter(transport=ollama_stopped))


def test_desktop_app_start_stop_and_notify(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from core.api import create_app
    from core.module_api import Event

    daemon = make_app_hub(tmp_path)
    daemon.start()
    client = TestClient(create_app(daemon))
    try:
        module = client.get("/modules").json()[0]
        assert module["app"] == "Démo" and module["app_running"] is False
        assert client.post("/modules/demo/app/start").json() == {"running": True, "started": True}
        assert client.post("/modules/demo/app/start").json()["started"] is False  # une seule instance
        assert client.get("/modules").json()[0]["app_running"] is True
        # la fausse appli n'a pas de fenêtre : la demande douce échoue, la fermeture est forcée au bout du délai
        assert client.post("/modules/demo/app/stop").json()["running"] is False
        assert client.get("/modules").json()[0]["app_running"] is False
        assert client.post("/modules/demo/app/explose").status_code == 404
        seen = []
        daemon.bus.subscribe("module.demo.cmd", lambda e: seen.append(e))
        assert client.post("/modules/demo/notify/showcase", json={"on": True}).json() == {"sent": True}
        assert client.post("/modules/demo/notify/a.b", json={}).status_code == 400
        daemon.bus.publish(Event("module.demo.state", {"showcase": True, "context": "Niveau 48"}, source="demo"))
        from tests.core.test_daemon import wait_for

        assert wait_for(lambda: seen and client.get("/modules/demo/state").json().get("context") == "Niveau 48")
        assert seen[0].payload == {"on": True}
    finally:
        daemon.stop()


def test_shutdown_button(client) -> None:
    assert client.post("/shutdown").status_code == 503  # pas de serveur réel dans les tests
    stopped = []
    client.app.state.shutdown = lambda: stopped.append(True)
    assert client.post("/shutdown").json() == {"stopping": True} and stopped == [True]


def test_glossary_api(client, tmp_path, monkeypatch) -> None:
    import core.api

    monkeypatch.setattr(core.api, "SCANTRAD_DIR", tmp_path / "scantrad")
    saved = client.put("/scantrad/glossary/Ma Série", json={"characters": {"ユキ": "Yuki"}, "terms": {"海": "mer"},
                                                             "tone": "familier"}).json()
    assert saved["characters"] == {"ユキ": "Yuki"} and saved["tone"] == "familier"
    assert client.get("/scantrad/glossary/Ma Série").json()["terms"] == {"海": "mer"}
    assert (tmp_path / "scantrad" / "glossaires" / "ma-serie.json").is_file()
    assert client.put("/scantrad/glossary/x", json={"terms": ["pas", "un", "dict"]}).status_code == 400
    assert client.get("/scantrad/glossary/ユキ").status_code == 400


@pytest.mark.parametrize("path", ["/scantrad/files/autre/a.png", "/scantrad/files/sorties/..%2F..%2Fx.png",
                                  "/scantrad/files/sorties/a.exe", "/scantrad/files/sorties/absente.png"])
def test_scantrad_files_are_confined(client, path) -> None:
    assert client.get(path).status_code == 404


def test_scantrad_upload_rejects_non_images(client) -> None:
    assert client.post("/scantrad/translate", content=b"MZ", headers={"Content-Type": "application/x-msdownload"}
                       ).status_code == 415


def test_studio_upload_and_confined_files(client, tmp_path, monkeypatch) -> None:
    import core.api

    monkeypatch.setattr(core.api, "MANGASTUDIO_DIR", tmp_path / "studio")
    png = (tmp_path.parent / "x.png")
    import cv2
    import numpy as np

    cv2.imwrite(str(png), np.zeros((8, 8, 3), np.uint8))
    up = client.post("/mangastudio/upload", content=png.read_bytes(), headers={"Content-Type": "image/png"}).json()
    assert up["url"].startswith("/mangastudio/files/entrees/") and client.get(up["url"]).status_code == 200
    assert client.post("/mangastudio/segment", json={"image": "../../secret.png"}).status_code == 404
    assert client.post("/mangastudio/segment", json={"image": "absente.png"}).status_code == 404
    assert client.get("/mangastudio/files/sorties/..%2Fentrees.png").status_code == 404
    status = client.get("/mangastudio/status").json()
    assert set(status["models"]) == {"hand", "foot"}


def test_hub_journal_keeps_events_but_not_game_state(tmp_path) -> None:
    from core.daemon import setup_journal
    from core.module_api import Event
    from tests.core.test_daemon import wait_for

    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    path = tmp_path / "logs" / "hub.log"
    logger = setup_journal(daemon, path)
    daemon.start()
    try:
        daemon.bus.publish(Event("module.gaming_hud.state", {"context": "Personnage secret, 123456 po"}))
        daemon.bus.publish(Event("module.scantrad.error", {"error": "image illisible"}))
        assert wait_for(lambda: path.is_file() and "image illisible" in path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8")
        assert "WARNING module.scantrad.error" in text and "hub.started" in text
        assert "Personnage secret" not in text  # les états des modules ne sont pas journalisés
    finally:
        daemon.stop()
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


@pytest.mark.parametrize("headers, expected", [
    ({}, 200),                                                    # le client de test du Hub
    ({"Origin": "http://127.0.0.1:5750"}, 200),                   # le tableau de bord lui-même
    ({"Origin": "http://localhost:5750"}, 200),
    ({"Origin": "https://site-malveillant.example"}, 403),        # formulaire envoyé par un autre site
    ({"Origin": "null"}, 403),                                    # page locale ou bac à sable
    ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Host": "attaquant.example:5750"}, 403),                    # nom de domaine qui pointe sur 127.0.0.1
])
def test_writes_from_other_sites_are_refused(client, headers, expected) -> None:
    stopped = []
    client.app.state.shutdown = lambda: stopped.append(True)
    assert client.post("/shutdown", headers=headers).status_code == expected
    assert bool(stopped) is (expected == 200)


def test_reads_check_the_host_too(client) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/health", headers={"Host": "127.0.0.1:5750"}).status_code == 200
    assert client.get("/health", headers={"Host": "rebind.example"}).status_code == 403


def test_port_in_use_detects_free_port() -> None:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        assert port_in_use(sock.getsockname()[1]) is True
