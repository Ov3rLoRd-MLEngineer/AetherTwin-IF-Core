"""calc_cas, module du Hub : manifeste, commandes du bus, persistance de la session, mode dégradé, erreurs
qui ne plantent jamais le module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.module_api import Event, discover_manifests, load_manifest
from modules.calc_cas.module import CalcCasModule

ROOT = Path(__file__).resolve().parents[2]


def make(tmp_path: Path, **config) -> CalcCasModule:
    module = CalcCasModule(load_manifest(ROOT / "modules" / "calc_cas"),
                           {"session": str(tmp_path / "session.json"), "hub_api": "", "timeout_s": 20, **config})
    module.start()
    return module


@pytest.fixture
def module(tmp_path: Path):
    m = make(tmp_path)
    yield m
    m.stop()


def test_manifest_is_discovered_and_light() -> None:
    found, errors = discover_manifests(ROOT / "modules")
    assert "calc_cas" in found and "calc_cas" not in errors
    manifest = found["calc_cas"]
    assert manifest.vram_min_gb == 0 and manifest.network == ()


def test_bus_commands_and_replies(module: CalcCasModule) -> None:
    replies: list[Event] = []
    module.publish = replies.append
    module.handle_event(Event("module.calc_cas.cmd.eval", {"request_id": "r1", "text": "diff(x^3, x)"}))
    module.handle_event(Event("module.calc_cas.cmd.inconnue", {"request_id": "r2"}))
    module.handle_event(Event("module.autre.cmd.eval", {"request_id": "r3", "text": "1"}))  # pas pour nous
    assert [e.payload["request_id"] for e in replies] == ["r1", "r2"]
    first, second = (e.payload for e in replies)
    assert first["ok"] and first["result"]["exact"] == "3*x**2"
    assert not second["ok"] and "inconnue" in second["error"]


def test_session_survives_restart(tmp_path: Path) -> None:
    m = make(tmp_path)
    try:
        m.run("eval", {"text": "f(x) := x^2 + 1"})
        m.run("eval", {"text": "f(2)"})
        m.run("eval", {"text": "1/0"})
    finally:
        m.stop()
    saved = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert saved["definitions"] == {"f": "f(x) := x^2 + 1"} and len(saved["history"]) == 3
    m2 = make(tmp_path)
    try:
        assert m2.run("eval", {"text": "f(3)"})["exact"] == "10"
        assert [h["input"] for h in m2.run("history", {})][:2] == ["f(x) := x^2 + 1", "f(2)"]
        assert m2.run("vars", {})[0]["name"] == "f"
        assert m2.run("delete", {"name": "f"}) is True
        assert m2.run("reset", {}) is True and m2.run("history", {}) == []
    finally:
        m2.stop()


def test_corrupt_session_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "session.json").write_text("{pas du json", encoding="utf-8")
    m = make(tmp_path)
    try:
        assert "illisible" in m.health().detail
        assert m.run("eval", {"text": "1 + 1"})["exact"] == "2"
    finally:
        m.stop()


def test_degraded_without_model_and_ask_is_explained(module: CalcCasModule) -> None:
    health = module.health()
    assert health.ok and health.degraded and "sans modèle" in health.detail
    with pytest.raises(RuntimeError, match="aucun modèle"):
        module.run("ask", {"question": "2+2 ?"})


def test_degraded_when_sympy_is_missing(tmp_path: Path) -> None:
    """Sans SymPy, le module démarre quand même et répond par une erreur lisible."""
    m = make(tmp_path)
    try:
        m.runner.broken = "ModuleNotFoundError: No module named 'sympy'"
        health = m.health()
        assert health.ok and health.degraded and "indisponible" in health.detail
        replies: list[Event] = []
        m.publish = replies.append
        m.handle_event(Event("module.calc_cas.cmd.eval", {"request_id": "r", "text": "1+1"}))
        assert not replies[0].payload["ok"] and "indisponible" in replies[0].payload["error"]
    finally:
        m.stop()


def test_eval_rejects_non_text(module: CalcCasModule) -> None:
    with pytest.raises(ValueError, match="text"):
        module.run("eval", {"text": 3})


def test_examples_catalog(module: CalcCasModule) -> None:
    catalog = module.run("examples", {})
    assert len(catalog["examples"]) >= 10 and catalog["graphs"] and catalog["stats"]["x"]


def test_settings_and_programs_persist(tmp_path: Path) -> None:
    m = make(tmp_path)
    try:
        assert m.run("settings", {"angle": "deg"}) == {"angle": "deg"}
        assert m.run("eval", {"text": "sin(90)"})["exact"] == "1"
        with pytest.raises(ValueError, match="réglage invalide"):
            m.run("settings", {"angle": "grades"})
        assert m.run("program_save", {"name": "carres", "code": "for i in range(3):\n    print(i*i)"}) == ["carres"]
        with pytest.raises(ValueError, match="nom de programme"):
            m.run("program_save", {"name": "2 mots", "code": "print(1)"})
        listing = m.run("programs", {})
        assert listing["programs"]["carres"].startswith("for") and "suite_syracuse" in listing["examples"]
        run = m.run("program_run", {"code": listing["programs"]["carres"], "seed": 3})
        assert run["ok"] and run["output"] == "0\n1\n4\n"
        asks = m.run("program_run", {"code": "print(input('n ? '))"})
        assert asks["needs_input"] and asks["prompt"] == "n ? "
    finally:
        m.stop()
    m2 = make(tmp_path)
    try:
        assert m2.run("eval", {"text": "cos(180)"})["exact"] == "-1"  # mode degrés rejoué
        assert "carres" in m2.run("programs", {})["programs"]
        assert m2.run("program_delete", {"name": "carres"}) is True
    finally:
        m2.stop()


def test_table_command(module: CalcCasModule) -> None:
    table = module.run("table", {"expr": "x^2", "start": -1, "step": 1, "count": 3})
    assert table["rows"] == [[-1.0, 1.0], [0.0, 0.0], [1.0, 1.0]]
    with pytest.raises(ValueError):
        module.run("table", {"expr": "x^2", "start": 0, "step": 0, "count": 3})


def test_geometry_command(module: CalcCasModule) -> None:
    result = module.run("geometry", {"what": "angle", "points": [[1, 0], [0, 0], [0, 1]], "degrees": True})
    assert result["exact"] == "90"
    with pytest.raises(ValueError, match="alignés"):
        module.run("geometry", {"what": "circumcircle", "points": [[0, 0], [1, 1], [2, 2]]})


def test_results_carry_an_image_but_history_file_does_not(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    module = make(tmp_path)
    try:
        result = module.run("eval", {"text": "integrate(x^2, x)"})
        assert result["png"] and result["pretty"]
        saved = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
        assert all("png" not in h for h in saved["history"])
        images = module.run("render", {"latex": [r"\frac{1}{2}", r"\begin{cases} x \end{cases}"]})
        assert images[0] and images[1] is None
        with pytest.raises(ValueError):
            module.run("render", {"latex": "x"})
    finally:
        module.stop()


def test_geometry_figure_command(module: CalcCasModule) -> None:
    objects = [{"id": 1, "t": "pt", "x": 0, "y": 0}, {"id": 2, "t": "pt", "x": 1, "y": 1}]
    result = module.run("geometry", {"what": "figure", "objects": objects, "measure": {"m": "len", "refs": [1, 2]}})
    assert result["exact"] == "sqrt(2)"


def test_game_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pygame")
    import time

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    module = make(tmp_path)
    try:
        refused = module.run("game_run", {"code": "import os\n"})
        assert refused["ok"] is False and "os" in refused["error"]
        assert module.run("game_run", {"code": "import jeu\nprint('partie', 1 + 1)\n"})["ok"]
        deadline = time.monotonic() + 30
        while module.run("game_status", {})["running"] and time.monotonic() < deadline:
            time.sleep(0.2)
        status = module.run("game_status", {})
        assert status["exit_code"] == 0 and "partie 2" in status["output"]
        assert module.run("game_stop", {}) is False
        with pytest.raises(ValueError):
            module.run("game_run", {})
    finally:
        module.stop()


def test_programs_list_games(module: CalcCasModule) -> None:
    assert {"snake", "pong", "tetris", "labyrinthe_3d"} <= set(module.run("programs", {})["games"])


def test_emulator_commands(tmp_path: Path) -> None:
    module = make(tmp_path, roms_dir=str(tmp_path / "roms"))
    try:
        catalog = module.run("emulators", {})
        assert catalog["roms"] == [] and catalog["folder"] == str(tmp_path / "roms")
        with pytest.raises(ValueError, match="introuvable"):
            module.run("emulator_launch", {"emulator": "mgba", "rom": "../session.json"})
    finally:
        module.stop()


def test_hermes_state_and_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.dev_launcher import hermes_link
    from modules.genesis_lab import sources

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(sources, "hermes_exe", lambda: "")
    module = make(tmp_path)
    try:
        assert module.run("hermes", {}) == {"installe": False, "branche": False, "nom": "aethertwin_calc"}
        with pytest.raises(ValueError, match="introuvable"):
            module.run("hermes_register", {})
        (tmp_path / "config.yaml").write_text("mcp_servers:\n  aethertwin_calc:\n    command: py\n", encoding="utf-8")
        monkeypatch.setattr(sources, "hermes_exe", lambda: "hermes.exe")
        assert module.run("hermes", {})["branche"] is True
        seen: dict = {}

        def fake_register(exe: str, name: str, args: list[str]) -> dict:
            seen.update(name=name, args=args)
            return {}

        monkeypatch.setattr(hermes_link, "register_server", fake_register)
        module.run("hermes_register", {})
        assert seen["name"] == "aethertwin_calc" and seen["args"][-1].endswith("mcp_server.py")
    finally:
        module.stop()
