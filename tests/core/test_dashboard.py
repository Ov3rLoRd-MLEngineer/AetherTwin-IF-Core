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
    for name, kind in (("dashboard.css", "text/css"), ("dashboard.js", "javascript"), ("logo.svg", "svg")):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200 and kind in response.headers["content-type"]
    assert "http" not in client.get("/static/dashboard.js").text.replace("http://127.0.0.1", "")  # rien d'externe


@pytest.mark.parametrize("path", ["/static/..%2Fapi.py", "/static/api.py", "/static/inconnu.css",
                                  "/static/..%2F..%2Fconfig%2Flocal.example.yaml"])
def test_static_refuses_other_files(client, path: str) -> None:
    assert client.get(path).status_code == 404


def test_port_in_use_detects_free_port() -> None:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        assert port_in_use(sock.getsockname()[1]) is True
