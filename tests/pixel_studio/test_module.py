"""pixel_studio : commandes du module, outils des agents, serveur MCP, sprites pour les jeux de la calculatrice,
fenêtre de bureau et page (aucune ressource externe, CSP du Hub respectée)."""
from __future__ import annotations

import base64
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from core.module_api import load_manifest
from modules.pixel_studio import agent, app, mcp_server, project
from modules.pixel_studio.module import PixelStudioModule
from modules.pixel_studio.studio import Studio

Image = pytest.importorskip("PIL.Image")

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "core" / "web"
HEART = [".cc.cc.", "ccccccc", "ccccccc", ".ccccc.", "..ccc..", "...c..."]


def make(tmp_path: Path) -> PixelStudioModule:
    module = PixelStudioModule(load_manifest(ROOT / "modules" / "pixel_studio"), {"data_dir": str(tmp_path / "data")})
    module.start()
    return module


def create_heart(module: PixelStudioModule, **extra) -> dict:
    return module.run("tool", {"name": "pixel_create_sprite", "arguments": {
        "name": "Cœur", "width": 7, "height": 6, "palette": "aether16",
        "frames": [{"rows": HEART}, {"rows": [r.replace("c", "b") for r in HEART], "duration": 200}], **extra}})


def test_agent_tools(tmp_path: Path) -> None:
    module = make(tmp_path)
    names = {spec["function"]["name"] for spec in module.run("tools", {})}
    assert names == {"pixel_list_projects", "pixel_palettes", "pixel_make_palette", "pixel_create_sprite",
                     "pixel_read_sprite", "pixel_export_for_game"}
    assert create_heart(module)["name"] == "coeur"
    again = create_heart(module)
    assert again["ok"] is False and "existe déjà" in again["error"]
    assert create_heart(module, overwrite=True)["ok"] is True
    read = module.run("tool", {"name": "pixel_read_sprite", "arguments": {"name": "coeur", "frame": 1}})
    assert read["rows"][1] == "bbbbbbb" and read["frames"] == 2
    assert module.run("tool", {"name": "pixel_read_sprite", "arguments": {"name": "coeur", "frame": 2}})["ok"] is False
    listed = module.run("tool", {"name": "pixel_list_projects", "arguments": {}})["projects"]
    assert listed == [{"name": "coeur", "width": 7, "height": 6, "frames": 2, "layers": 1, "map": False}]
    ramp = module.run("tool", {"name": "pixel_make_palette", "arguments": {"base_color": "#4caf50", "count": 4}})
    assert len(ramp["colors"]) == 4
    for bad in ({"name": "x", "width": 2, "height": 1, "palette": "console4", "rows": ["0z"]},
                {"name": "x", "width": 100, "height": 1, "palette": "console4", "rows": ["0"]},
                {"name": "", "width": 1, "height": 1, "palette": "console4", "rows": ["0"]}):
        result = module.run("tool", {"name": "pixel_create_sprite", "arguments": bad})
        assert result["ok"] is False and result["error"]
    assert module.run("tool", {"name": "rm_rf", "arguments": {}})["ok"] is False


def test_project_commands_and_exports(tmp_path: Path) -> None:
    module = make(tmp_path)
    create_heart(module)
    doc = module.run("project_load", {"name": "coeur"})
    doc["tilemap"] = {"cols": 3, "rows": 2, "ground": [0, 1, 0, 1, 0, 1], "solid": [1]}
    module.run("project_save", {"project": doc})
    assert module.run("projects", {})[0]["map"] is True
    for kind, filename in (("png", "coeur_1.png"), ("sheet", "coeur_planche.png"), ("gif", "coeur.gif"),
                           ("map", "coeur_carte.png")):
        result = module.run("export", {"project": doc, "kind": kind, "scale": 2})
        assert result["filename"] == filename
        assert base64.b64decode(result["data"]) == (tmp_path / "data" / "exports" / filename).read_bytes()
        if kind in ("sheet", "map"):
            assert json.loads((tmp_path / "data" / "exports" / result["meta_filename"]).read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="export inconnu"):
        module.run("export", {"project": doc, "kind": "svg"})
    assert len(module.run("palettes", {})) >= 6
    assert module.run("palette_ramp", {"base": "#7048e8", "count": 3})[1] == "#7048e8"
    buffer = io.BytesIO()
    Image.new("RGB", (2, 1), (10, 200, 30)).save(buffer, format="PNG")
    assert module.run("palette_from_image", {"data": base64.b64encode(buffer.getvalue()).decode()}) == ["#0ac81e"]
    with pytest.raises(ValueError, match="base64"):
        module.run("palette_from_image", {"data": "%%%"})
    assert module.run("project_delete", {"name": "coeur"}) is True
    with pytest.raises(ValueError, match="commande inconnue"):
        module.run("formater", {})
    assert module.health().ok


def test_game_export_and_jeu_sprites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pygame = pytest.importorskip("pygame")
    from modules.calc_cas import games

    module = make(tmp_path)
    create_heart(module)
    doc = module.run("project_load", {"name": "coeur"})
    doc["tilemap"] = {"cols": 2, "rows": 1, "ground": [0, 1], "solid": [0, 1]}
    module.run("project_save", {"project": doc})
    result = module.run("game_export", {"name": "coeur"})
    assert result["map"] is True and 'jeu.carte("coeur"' in result["usage"]
    sprites = tmp_path / "data" / "sprites"
    info = json.loads((sprites / "coeur.json").read_text(encoding="utf-8"))
    assert info["frames"] == 2 and info["map"]["solid"] == [0, 1]

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        game = games.Game(pygame, sprites)
        jeu = game.module()
        jeu.fenetre(120, 80)
        jeu.effacer("noir")
        jeu.carte("coeur", 0, 0, echelle=2)
        jeu.sprite("coeur", 40, 40, echelle=2, image=3)  # image 3 → 3 % 2 = 1
        assert game.screen.get_at((2 * 1 + 1, 1))[:3] == (214, 69, 93)  # tuile 0 : rouge #d6455d
        assert game.screen.get_at((40 + 2, 40 + 2))[:3] == (122, 31, 53)  # image 1 : bordeaux #7a1f35
        assert jeu.bloque("coeur", 15, 3, 0, 0, 2) is True and jeu.bloque("coeur", 3, 3, 0, 0, 2) is False
        assert jeu.bloque("coeur", 500, 3) is False
        for bad in ("../coeur", "absent"):
            with pytest.raises(ValueError):
                jeu.sprite(bad, 0, 0)
    finally:
        pygame.quit()


def test_games_get_the_studio_sprites_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import config
    from modules.calc_cas import module as calc_module

    monkeypatch.setattr(config, "section",
                        lambda name, path=None: {"data_dir": "D:/x/pixel"} if name == "pixel_studio" else {})
    assert calc_module.pixel_sprites_dir() == Path("D:/x/pixel/sprites")
    monkeypatch.setattr(config, "section", lambda name, path=None: {})
    assert calc_module.pixel_sprites_dir().parts[-3:] == ("data", "pixel_studio", "sprites")


def test_mcp_in_process_and_subprocess(tmp_path: Path) -> None:
    studio = Studio(tmp_path)
    init = mcp_server.handle(studio, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "aethertwin-pixel-studio"
    tools = mcp_server.handle(studio, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert len(tools) == len(agent.TOOL_SPECS) and all("inputSchema" in t for t in tools)
    call = mcp_server.handle(studio, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "pixel_create_sprite", "arguments": {"name": "point", "width": 1, "height": 1, "palette": "gris8",
                                                     "rows": ["7"]}}})
    assert call["result"]["isError"] is False and (tmp_path / "projects" / "point.aether-pixel").is_file()
    assert mcp_server.handle(studio, {"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]["code"] == -32601
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "pixel_palettes", "arguments": {}}}]
    stdin = "".join(json.dumps(r) + "\n" for r in requests)
    proc = subprocess.run([sys.executable, "-I", str(ROOT / "modules" / "pixel_studio" / "mcp_server.py")],
                          input=stdin.encode("utf-8"), capture_output=True, cwd=tmp_path, timeout=60, check=False)
    lines = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    assert [m["id"] for m in lines] == [1, 2], proc.stderr.decode("utf-8", "replace")
    assert lines[1]["result"]["structuredContent"]["palettes"][0]["id"] == "aether16"


def test_hermes_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.genesis_lab import sources

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(sources, "hermes_exe", lambda: "")
    module = make(tmp_path)
    assert module.run("hermes", {}) == {"installe": False, "branche": False, "nom": "aethertwin_pixel"}
    (tmp_path / "config.yaml").write_text("mcp_servers:\n  aethertwin_pixel:\n    command: py\n", encoding="utf-8")
    monkeypatch.setattr(sources, "hermes_exe", lambda: "hermes.exe")
    assert module.run("hermes", {})["branche"] is True


def test_window_and_page(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = load_manifest(ROOT / "modules" / "pixel_studio")
    assert manifest.app == ("Studio pixel Æther", "modules.pixel_studio.app")
    from core import config

    monkeypatch.setattr(config, "section", lambda name, path=None: {"port": 5761} if name == "daemon" else {})
    assert app.page_url() == "http://127.0.0.1:5761/static/pixel_app.html"
    opened: list[str] = []
    monkeypatch.setattr(app, "find_browser", lambda: None)
    monkeypatch.setattr(app.webbrowser, "open", opened.append)
    assert app.main() == 0 and opened[0].endswith("/static/pixel_app.html")
    from modules.calc_cas.app import browser_args

    assert "--window-size=1320,860" in browser_args("edge.exe", "u", Path("p"), app.WINDOW_SIZE)

    page = (WEB / "pixel_app.html").read_text(encoding="utf-8")
    script = (WEB / "pixel_app.js").read_text(encoding="utf-8")
    style = (WEB / "pixel_app.css").read_text(encoding="utf-8")
    assert "/static/pixel_app.js" in page and "/static/pixel_app.css" in page
    assert " style=" not in page  # la CSP du Hub refuse les styles en ligne
    for text in (page, script, style):
        assert not re.search(r"https?://(?!127\.0\.0\.1)", text)
    ids = set(re.findall(r'\$\("([\w-]+)"\)', script))
    missing = sorted(i for i in ids if f'id="{i}"' not in page)
    assert ids and not missing, f"identifiants absents de la page : {missing}"
    assert "data:image" not in script.replace('toDataURL("image/png")', "")  # img-src : 'self' et blob: seulement

    dashboard = (WEB / "dashboard.html").read_text(encoding="utf-8")
    tool = (WEB / "pixel_tool.js").read_text(encoding="utf-8")
    assert '<section data-sub="Studio pixel"' in dashboard and "/static/pixel_tool.js" in dashboard
    ids = set(re.findall(r'\$\("([\w-]+)"\)', tool))
    assert ids and not sorted(i for i in ids if f'id="{i}"' not in dashboard)


def test_new_project_helper() -> None:
    doc = project.new_project("vide", 4, 3, ["#000000"], frames=2)
    assert len(doc["frames"]) == 2 and doc["frames"][0]["cels"] == [None]
