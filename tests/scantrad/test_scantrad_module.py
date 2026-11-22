"""Le module scantrad dans son vrai processus, piloté par le démon (sans modèle : détection et effacement)."""
from __future__ import annotations

from pathlib import Path

from core.daemon import REPO_ROOT, Daemon
from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
from core.llm_router import LlmRouter
from tests.core.test_daemon import ollama_stopped, wait_for

PAGE = Path(__file__).resolve().parents[1] / "data" / "scantrad" / "page_test.png"


def test_scantrad_module_translates_on_command(tmp_path: Path) -> None:
    daemon = Daemon(REPO_ROOT / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    daemon.start()
    try:
        assert daemon.activate("scantrad").verdict.value == "accordé"
        assert wait_for(lambda: daemon.modules["scantrad"].last_health.get("ok") is True)
        out = tmp_path / "sortie.png"
        reply = daemon.command("scantrad", "page", {"input": str(PAGE), "output": str(out), "no_llm": True},
                               timeout_s=60)
        assert reply["ok"] is True, reply
        assert reply["result"]["metrics"]["bubbles"] == 5 and out.is_file()
        missing = daemon.command("scantrad", "page", {"input": str(tmp_path / "absente.png")}, timeout_s=30)
        assert missing["ok"] is False and "introuvable" in missing["error"]
    finally:
        daemon.stop()


def test_dashboard_upload_translates_through_the_module(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import core.api
    from core.api import create_app

    monkeypatch.setattr(core.api, "SCANTRAD_DIR", tmp_path / "scantrad")
    daemon = Daemon(REPO_ROOT / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    daemon.start()
    try:
        client = TestClient(create_app(daemon))
        reply = client.post("/scantrad/translate?no_llm=true", content=PAGE.read_bytes(),
                            headers={"Content-Type": "image/png"}).json()
        assert reply["ok"] is True, reply  # le module est lancé à la demande
        assert reply["result"]["metrics"]["bubbles"] == 5
        image = client.get(reply["output_url"])
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert client.get(reply["input_url"]).content == PAGE.read_bytes()
        # correction à la main, réincrustée sur la page nettoyée (sans OCR ni modèle)
        name = reply["output_url"].rsplit("/", 1)[-1]
        before = image.content
        fixed = client.post("/scantrad/retypeset", json={"output": name, "translations": {"1": "Salut !"}}).json()
        assert fixed["ok"] is True, fixed
        assert [b["translation"] for b in fixed["result"]["bubbles"]][0] == "Salut !"
        assert client.get(fixed["output_url"]).content != before
        too_long = client.post("/scantrad/retypeset", json={"output": name, "translations": {"1": "x" * 401}}).json()
        assert too_long["ok"] is False and "400" in too_long["error"]
        assert client.post("/scantrad/retypeset", json={"output": "../../x_fr.png"}).status_code == 404
    finally:
        daemon.stop()


def test_manual_mode_through_the_dashboard(tmp_path: Path, monkeypatch) -> None:
    """Mode manuel par l'API : envoi, zones proposées, effacement, page gommée, réincrustation, correction."""
    from fastapi.testclient import TestClient

    import core.api
    from core.api import create_app

    monkeypatch.setattr(core.api, "SCANTRAD_DIR", tmp_path / "scantrad")
    daemon = Daemon(REPO_ROOT / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    daemon.start()
    try:
        client = TestClient(create_app(daemon))
        up = client.post("/scantrad/upload", content=PAGE.read_bytes(), headers={"Content-Type": "image/png"}).json()
        image = up["image"]
        boxes = client.post("/scantrad/manual/suggest", json={"image": image}).json()["result"]["boxes"]
        assert len(boxes) == 5
        erased = client.post("/scantrad/manual/erase", json={"image": image, "boxes": boxes}).json()
        assert erased["ok"] is True, erased
        cleaned = client.get(erased["cleaned_url"]).content
        assert cleaned.startswith(b"\x89PNG")
        # la page gommée dans le navigateur remplace la page effacée automatiquement
        assert client.post(f"/scantrad/manual/cleaned?image={image}", content=cleaned,
                           headers={"Content-Type": "image/png"}).status_code == 200
        assert client.post(f"/scantrad/manual/cleaned?image={image}", content=b"pas un png",
                           headers={"Content-Type": "image/png"}).status_code == 400
        bubbles = [{"box": box, "source": "", "translation": f"Bulle {i}"} for i, box in enumerate(boxes, 1)]
        made = client.post("/scantrad/manual/compose", json={"image": image, "bubbles": bubbles}).json()
        assert made["ok"] is True, made
        assert [b["translation"] for b in made["result"]["bubbles"]] == [f"Bulle {i}" for i in range(1, 6)]
        assert client.get(made["output_url"]).status_code == 200
        name = made["output_url"].rsplit("/", 1)[-1]  # la correction ligne à ligne marche aussi
        fixed = client.post("/scantrad/retypeset", json={"output": name, "translations": {"2": "Salut"}}).json()
        assert fixed["ok"] is True and fixed["result"]["bubbles"][1]["translation"] == "Salut"
        nothing = client.post("/scantrad/manual/translate", json={"texts": ["", "  "]}).json()
        assert nothing["ok"] is True and nothing["result"]["translations"] == ["", ""]  # sans appel au modèle
        assert client.post("/scantrad/manual/read", json={"image": "../x.png", "boxes": boxes}).status_code == 404
        assert client.post("/scantrad/manual/autre", json={"image": image}).status_code == 404
        bad = client.post("/scantrad/manual/compose", json={"image": image, "bubbles": [{"box": [0, 0, 2, 2]}]}).json()
        assert bad["ok"] is False and "petite" in bad["error"]
    finally:
        daemon.stop()
