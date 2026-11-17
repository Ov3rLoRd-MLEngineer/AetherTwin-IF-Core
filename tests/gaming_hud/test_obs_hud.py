"""Overlay OBS : serveur local, page sans dépendance externe, logo, absence de données privées, rendu réel."""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.module_api import load_manifest
from modules.gaming_hud import PACKAGE_DIR
from modules.gaming_hud.adapters.privacy import leaks
from modules.gaming_hud.module import GamingHudModule
from modules.gaming_hud.obs_server import WEB_DIR, ObsServer, overlay_view
from tests.gaming_hud.test_adapters import ACCOUNT, API_KEY, EMAIL, GOLD_COPPER, GUILD, NAME, REALM, SAVED_VARIABLES

ASSETS = PACKAGE_DIR.parents[1] / "assets"
PRIVATE = [ACCOUNT, EMAIL, API_KEY, "ProfilCanari", NAME, REALM, GUILD, str(GOLD_COPPER)]
DEMO = {
    "showcase": True, "ts": 0,
    "character": {"name": "Aventurier", "level": 48, "class": "Druidesse", "spec": "Farouche",
                  "zone": "Hurlevent - Quartier commerçant", "ilvl": 17.5, "money": 1_000_000},
    "quests": {"count": 6, "titles": ["Le défi du héros", "Des nouvelles du front", "Un mal ancien"]},
    "gpus": [{"index": 0, "name": "NVIDIA GeForce RTX 5080", "util": 37.0, "vram_used": 12800, "vram_total": 16303,
              "temp": 61.0, "power": 182.4},
             {"index": 1, "name": "NVIDIA GeForce RTX 5060 Ti", "util": 92.0, "vram_used": 15100, "vram_total": 16311,
              "temp": 68.0, "power": 141.0}],
}


def get(url: str, timeout: float = 10.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 — serveur de test local
        return response.status, dict(response.headers), response.read()


def first_sse_events(url: str, count: int, timeout: float = 15.0) -> list[dict]:
    events = []
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        while len(events) < count:
            line = response.readline().decode("utf-8")
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


@pytest.fixture
def server():
    state = {"data": dict(DEMO)}
    obs = ObsServer(lambda: state["data"], port=0, interval_s=0.05)
    obs.start()
    obs.state = state  # type: ignore[attr-defined]
    yield obs
    obs.stop()


# --------------------------------------------------------------------------- serveur
def test_overlay_only_listens_on_loopback() -> None:
    with pytest.raises(ValueError, match="boucle locale"):
        ObsServer(lambda: {}, host="0.0.0.0")  # noqa: S104 — c'est justement ce qui doit être refusé
    obs = ObsServer(lambda: {}, port=0)
    obs.start()
    try:
        assert obs._server.server_address[0] == "127.0.0.1" and obs.url.startswith("http://127.0.0.1:")
    finally:
        obs.stop()


def test_page_and_its_files_are_served_with_a_strict_policy(server: ObsServer) -> None:
    status, headers, body = get(server.url)
    assert status == 200 and headers["Content-Type"].startswith("text/html") and b'id="hud"' in body
    assert "default-src 'none'" in headers["Content-Security-Policy"] and headers["Cache-Control"] == "no-store"
    for path, kind in (("/style.css", "text/css"), ("/app.js", "text/javascript"), ("/logo.svg", "image/svg+xml")):
        status, headers, body = get(server.url + path)
        assert status == 200 and headers["Content-Type"].startswith(kind) and body
    assert json.loads(get(server.url + "/state")[2]) == DEMO


@pytest.mark.parametrize("path", ["/", "/obs-hud/../module.py", "/obs-hud/%2e%2e/module.py", "/obs-hud/secret.txt",
                                  "/obs-hud/app.js/../../manifest.json", "/settings.json"])
def test_nothing_else_can_be_fetched(server: ObsServer, path: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as error:
        get(f"http://127.0.0.1:{server.port}{path}")
    assert error.value.code == 404


def test_sse_pushes_the_state_and_every_change(server: ObsServer) -> None:
    import threading

    def change() -> None:
        server.state["data"] = {**DEMO, "character": {**DEMO["character"], "level": 49}}

    threading.Timer(0.4, change).start()
    events = first_sse_events(server.url + "/events", 2)
    assert events[0]["character"]["level"] == 48 and events[1]["character"]["level"] == 49


def test_a_failing_snapshot_does_not_break_the_overlay() -> None:
    def broken() -> dict:
        raise RuntimeError("lecture impossible : " + EMAIL)

    obs = ObsServer(broken, port=0)
    obs.start()
    try:
        assert json.loads(get(obs.url + "/state")[2]) == {"error": "RuntimeError"}  # le message d'erreur ne sort pas
    finally:
        obs.stop()


# --------------------------------------------------------------------------- page et logo
def test_web_files_have_no_external_dependency() -> None:
    for name in ("obs_hud.html", "obs_hud.css", "obs_hud.js"):
        text = (WEB_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://|//cdn|@import|url\(", text), f"{name} référence une ressource externe"
    script = (WEB_DIR / "obs_hud.js").read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert forbidden not in script, f"le script utilise {forbidden} : les données doivent passer par textContent"
    html = (WEB_DIR / "obs_hud.html").read_text(encoding="utf-8")
    assert "<script src=\"/obs-hud/app.js\">" in html and "style=" not in html and "onclick" not in html


@pytest.mark.parametrize("name", ["logo_if_core.svg", "logo_if_core_mono.svg"])
def test_logo_is_a_small_valid_svg_without_embedded_content(name: str) -> None:
    path = ASSETS / name
    root = ET.parse(path).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg" and root.get("viewBox") == "0 0 100 100"
    tags = {element.tag.split("}")[1] for element in root.iter()}
    assert not tags & {"image", "script", "foreignObject", "use"} and path.stat().st_size < 4000
    if "mono" in name:
        colors = set(re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]{3,8})"', path.read_text(encoding="utf-8")))
        assert len(colors) == 1, f"la variante monochrome utilise {len(colors)} couleurs"


def test_overlay_view_only_keeps_known_fields() -> None:
    visible = {"character": {"name": "A", "level": 3, "zone": "Z", "subzone": "S", "secret": EMAIL, "money": 20_000},
               "quests": {"count": 9, "list": [{"title": f"q{i}", "secret": API_KEY} for i in range(9)]},
               "log": [{"text": EMAIL}], "_meta": {"source_file": "x"}}
    gpus = [{"index": 0, "name": "G", "vram_used_mib": 1, "vram_total_mib": 2, "secret": 1}]
    view = overlay_view(visible, gpus, True)
    assert view["character"] == {"name": "A", "level": 3, "class": None, "spec": None, "zone": "Z - S", "ilvl": None,
                                 "money": 20_000}
    assert view["quests"] == {"count": 9, "titles": ["q0", "q1", "q2", "q3"]}
    assert leaks(view, [EMAIL, API_KEY, "secret", "source_file"]) == [] and "log" not in view


# --------------------------------------------------------------------------- dans le module
@pytest.fixture
def game_dir(tmp_path: Path) -> Path:
    saved = tmp_path / "_retail_" / "WTF" / "Account" / ACCOUNT / "SavedVariables"
    saved.mkdir(parents=True)
    (saved / "HermesAssistant.lua").write_text(SAVED_VARIABLES, encoding="utf-8")
    return tmp_path / "_retail_"


def test_overlay_never_leaks_private_data_even_when_showcase_is_off(game_dir: Path) -> None:
    module = GamingHudModule(load_manifest(PACKAGE_DIR), {
        "game_path": str(game_dir), "autodetect": False, "poll_seconds": 3600, "obs_hud_port": 0,
        "showcase_processes": ["diffusion.exe"], "hide_character_names": True})
    module.publish = lambda event: None
    module.start()
    try:
        assert module.showcase is False and module.obs is not None  # le module n'est PAS en mode Showcase…
        assert "overlay http://127.0.0.1:" in module.health().detail
        url = module.obs.url
        state = json.loads(get(url + "/state")[2])
        stream = first_sse_events(url + "/events", 1)
        page = b"".join(get(url + path)[2] for path in ("", "/app.js", "/style.css", "/logo.svg")).decode("utf-8")
        assert leaks([state, stream, page], PRIVATE) == []  # …et pourtant rien de privé ne sort de la page
        assert state["character"]["level"] == 48 and state["character"]["name"] == "Aventurier"
        assert state["character"]["money"] == 1_000_000 and state["quests"]["count"] == 1  # or arrondi
        assert state["showcase"] is True and isinstance(state["gpus"], list)
    finally:
        module.stop()
    with pytest.raises(OSError):
        get(url, timeout=2)  # le serveur s'arrête avec le module


def test_busy_port_degrades_the_overlay_not_the_module(game_dir: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        module = GamingHudModule(load_manifest(PACKAGE_DIR), {
            "game_path": str(game_dir), "autodetect": False, "poll_seconds": 3600,
            "obs_hud_port": busy.getsockname()[1], "showcase_processes": ["diffusion.exe"]})
        events = []
        module.publish = events.append
        module.start()
        try:
            assert module.obs is None and "overlay OBS indisponible" in module.health().detail
            assert module.health().ok and module.read()["state"]["character"]["level"] == 48
        finally:
            module.stop()


def test_overlay_can_be_disabled(game_dir: Path) -> None:
    module = GamingHudModule(load_manifest(PACKAGE_DIR), {"game_path": str(game_dir), "autodetect": False,
                                                          "poll_seconds": 3600, "obs_hud": False})
    module.publish = lambda event: None
    module.start()
    try:
        assert module.obs is None and "overlay" not in module.health().detail
    finally:
        module.stop()


# --------------------------------------------------------------------------- rendu réel dans un navigateur
def test_page_renders_in_a_real_browser(server: ObsServer, tmp_path: Path) -> None:
    """Capture de rendu avec Playwright (Edge installé, sinon Chromium). Ignoré si aucun navigateur n'est pilotable."""
    sync_api = pytest.importorskip("playwright.sync_api")
    folder = Path(os.environ.get("AETHERTWIN_SHOTS") or tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    with sync_api.sync_playwright() as playwright:
        browser = None
        for options in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                browser = playwright.chromium.launch(**options)
                break
            except Exception:  # noqa: BLE001, S112 — ce navigateur n'est pas installé : on essaie le suivant
                continue
        if browser is None:
            pytest.skip("aucun navigateur pilotable (Edge, Chrome ou Chromium de Playwright)")
        try:
            page = browser.new_page(viewport={"width": 420, "height": 560})
            errors: list[str] = []
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(server.url)
            page.wait_for_selector("#gpus:not([hidden]) .gpu", timeout=10_000)
            assert page.inner_text("#char-name") == "Aventurier"
            assert page.inner_text("#char-line") == "Niveau 48 · Druidesse · Farouche"
            assert "Hurlevent" in page.inner_text("#char-zone") and "100 po" in page.inner_text("#char-extra")
            assert page.inner_text("#quests-title").upper() == "QUÊTES · 6"
            assert page.locator("#quests-list li").count() == 3
            assert page.locator(".gpu").count() == 2 and "RTX 5080" in page.inner_text("#gpu-list")
            assert "12.5 / 16 Go" in page.inner_text("#gpu-list") and "61 °C" in page.inner_text("#gpu-list")
            assert "hot" in (page.locator(".gpu").nth(1).locator(".fill").first.get_attribute("class") or "")
            background = page.evaluate("getComputedStyle(document.body).backgroundColor")
            assert background in ("rgba(0, 0, 0, 0)", "transparent")  # fond transparent : indispensable dans OBS
            assert page.evaluate("document.querySelector('.logo').naturalWidth") > 0  # le logo s'est chargé
            # texte hostile dans les données : affiché tel quel, jamais interprété
            # (la politique de sécurité de la page interdit l'évaluation de code : on attend avec des localisateurs)
            hostile = "<img src=x onerror=alert(1)>"
            server.state["data"] = {**DEMO, "character": {**DEMO["character"], "name": hostile}}
            sync_api.expect(page.locator("#char-name")).to_have_text(hostile, timeout=10_000)
            assert page.locator("#char-name img").count() == 0
            server.state["data"] = dict(DEMO)
            sync_api.expect(page.locator("#char-name")).to_have_text("Aventurier", timeout=10_000)
            page.screenshot(path=str(folder / "obs_hud.png"), omit_background=True)
            assert errors == [], f"erreurs dans la page : {errors}"
        finally:
            browser.close()
    assert (folder / "obs_hud.png").stat().st_size > 5000
