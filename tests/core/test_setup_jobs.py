"""Dépendances du Hub : liste fermée de tâches, liens officiels, téléchargement sans fichier à moitié écrit."""
from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from core import setup_jobs


def test_dependencies_list_links_and_segnet_cards() -> None:
    deps = setup_jobs.dependencies()
    ids = {d["id"] for d in deps["externes"]}
    assert {"python", "git", "ollama", "claude_code", "windows_terminal", "hermes"} <= ids
    assert all(d["lien"].startswith("https://") for d in deps["externes"])
    assert {t["id"] for t in deps["taches"]} == set(setup_jobs.JOBS)
    for key in ("hand", "foot"):
        card = deps["segnet"][key]
        assert card["github"].startswith("https://github.com/Ov3rLoRd-MLEngineer/")
        assert card["huggingface"].startswith("https://huggingface.co/Ov3rLoRd-MLEngineer/")
        assert card["chiffres"] and card["limites"]


def test_unknown_job_is_refused() -> None:
    with pytest.raises(KeyError):
        setup_jobs.start("rm -rf")


def test_job_runs_once_at_a_time_and_reports(monkeypatch) -> None:
    monkeypatch.setattr(setup_jobs, "_state", {})
    gate = {"go": False}

    def runner(key, say):
        say("étape 1")
        while not gate["go"]:
            time.sleep(0.01)

    assert setup_jobs.start("voice", runner)["lance"] is True
    assert setup_jobs.start("voice", runner) == {"lance": False, "raison": "déjà en cours"}
    assert setup_jobs.job_state("voice")["etat"] == "en cours"
    gate["go"] = True
    for _ in range(200):
        if setup_jobs.job_state("voice")["etat"] != "en cours":
            break
        time.sleep(0.01)
    state = setup_jobs.job_state("voice")
    assert state["etat"] == "fait" and "étape 1" in state["journal"]


def test_failed_job_is_shown(monkeypatch) -> None:
    monkeypatch.setattr(setup_jobs, "_state", {})

    def runner(key, say):
        raise RuntimeError("réseau coupé")

    setup_jobs.start("weights_hand", runner)
    for _ in range(200):
        if setup_jobs.job_state("weights_hand")["etat"] != "en cours":
            break
        time.sleep(0.01)
    state = setup_jobs.job_state("weights_hand")
    assert state["etat"] == "échec" and "réseau coupé" in state["detail"]


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, length: int) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_writes_whole_file_or_nothing(tmp_path: Path) -> None:
    target = tmp_path / "poids.safetensors"
    lines: list[str] = []
    setup_jobs.download("https://exemple", target, lines.append,
                        opener=lambda url, timeout: FakeResponse(b"x" * 10, 10))
    assert target.read_bytes() == b"x" * 10 and not list(tmp_path.glob("*.part"))

    broken = tmp_path / "coupé.safetensors"
    with pytest.raises(RuntimeError, match="incomplet"):
        setup_jobs.download("https://exemple", broken, lines.append,
                            opener=lambda url, timeout: FakeResponse(b"x" * 4, 10))
    assert not broken.exists() and not list(tmp_path.glob("*.part"))


@pytest.fixture
def client(tmp_path):
    from tests.core.test_dashboard import client as make_client

    return make_client.__wrapped__(tmp_path)


def test_api_routes(client) -> None:
    deps = client.get("/setup/dependencies").json()
    assert "externes" in deps and "segnet" in deps
    assert client.post("/setup/run", json={"tache": "inconnue"}).status_code == 400
    evil = {"origin": "http://evil.example"}
    assert client.post("/setup/run", json={"tache": "gpu"}, headers=evil).status_code == 403


def test_asus_tools_have_official_download_pages() -> None:
    from core.hardware import system_info

    for tool in system_info.tools_state():
        assert tool["telecharger"].startswith("https://"), tool["id"]


def test_dashboard_pages_after_regrouping(client) -> None:
    page = client.get("/").text
    assert "/static/deps.js" in page and "/static/segnet.css" in page
    assert 'data-tab="studio">Studio image<' in page and "AetherTwin I&amp;F Hommage" in page
    studio = page.split('data-panel="studio"', 1)[1].split('<div class="panel', 1)[0]
    assert 'data-sub="HandSegNet"' in studio and 'data-sub="FootSegNet"' in studio and 'id="seg-deps"' in studio
    assert "mémoire d'Inoue et de Fuma" in page
    assert 'data-sub="Dépendances"' in page and 'id="dev-deps"' in page
    for name in ("deps.js", "segnet.css"):
        assert client.get(f"/static/{name}").status_code == 200
