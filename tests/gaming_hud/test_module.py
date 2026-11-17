"""Module gaming_hud : publication de l'état, bascule Showcase, intégration réelle dans le démon."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.daemon import Daemon
from core.guardians.inoue import Verdict
from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
from core.module_api import Event, load_manifest
from modules.gaming_hud import PACKAGE_DIR
from modules.gaming_hud.adapters.privacy import leaks
from modules.gaming_hud.module import GamingHudModule, build_adapter, compact
from tests.gaming_hud.test_adapters import ACCOUNT, API_KEY, EMAIL, GOLD_COPPER, GUILD, NAME, REALM, SAVED_VARIABLES

REPO_MODULES = PACKAGE_DIR.parent
PRIVATE = [ACCOUNT, EMAIL, API_KEY, "ProfilCanari", NAME, REALM, GUILD, str(GOLD_COPPER)]


@pytest.fixture
def game_dir(tmp_path: Path) -> Path:
    saved = tmp_path / "_retail_" / "WTF" / "Account" / ACCOUNT / "SavedVariables"
    saved.mkdir(parents=True)
    (saved / "HermesAssistant.lua").write_text(SAVED_VARIABLES, encoding="utf-8")
    return tmp_path / "_retail_"


def make_module(config: dict) -> tuple[GamingHudModule, list[Event]]:
    module = GamingHudModule(load_manifest(PACKAGE_DIR), {"poll_seconds": 3600, "showcase_processes": ["diffusion.exe"],
                                                          "obs_hud_port": 0, **config})  # port 0 = port libre
    events: list[Event] = []
    module.publish = events.append
    return module, events


def wait_for(predicate, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_manifest_is_valid_and_declares_no_vram_need() -> None:
    manifest = load_manifest(PACKAGE_DIR)
    assert manifest.name == "gaming_hud" and manifest.vram_min_gb == 0 and manifest.network == ()
    assert "obs64.exe" in manifest.triggers.processes


def test_publishes_state_and_context(game_dir: Path) -> None:
    module, events = make_module({"game_path": str(game_dir), "autodetect": False})
    module.start()
    try:
        assert wait_for(lambda: any(e.topic == "module.gaming_hud.state" for e in events))
        payload = next(e.payload for e in events if e.topic == "module.gaming_hud.state")
        assert payload["adapter"] == "wow_retail" and payload["showcase"] is False
        assert payload["state"]["character"]["name"] == NAME and NAME in payload["context"]
        health = module.health()
        assert health.ok and not health.degraded and "wow_retail" in health.detail
        count = len(events)
        assert module.publish_state() is False and len(events) == count  # rien n'a changé : rien n'est republié
    finally:
        module.stop()


def test_streaming_software_switches_showcase_on_and_off(game_dir: Path) -> None:
    module, events = make_module({"game_path": str(game_dir), "autodetect": False, "hide_character_names": True})
    module.start()
    try:
        assert wait_for(lambda: any(e.topic == "module.gaming_hud.state" for e in events))
        events.clear()
        module.handle_event(Event("process.started", {"name": "Diffusion.EXE"}))
        assert module.showcase is True and [e.topic for e in events] == ["module.gaming_hud.showcase",
                                                                         "module.gaming_hud.state"]
        shown = events[-1].payload
        assert shown["showcase"] is True and leaks(shown, PRIVATE) == []  # état ET contexte de l'assistant
        assert shown["state"]["character"]["level"] == 48
        assert "SHOWCASE" in module.health().detail
        module.handle_event(Event("process.started", {"name": "autre.exe"}))
        assert module.showcase is True
        events.clear()
        module.handle_event(Event("process.stopped", {"name": "diffusion.exe"}))
        assert module.showcase is False and events[-1].payload["state"]["character"]["name"] == NAME
        module.handle_event(Event("module.gaming_hud.cmd.showcase", {"on": True}))
        assert module.showcase is True
    finally:
        module.stop()


def test_degraded_without_game_and_with_a_bad_configuration(tmp_path: Path) -> None:
    module, events = make_module({"game_path": str(tmp_path / "absent"), "autodetect": False})
    module.start()
    try:
        assert wait_for(lambda: bool(events))
        health = module.health()
        assert health.ok and health.degraded and "introuvable" in health.detail
        assert events[0].payload["state"]["_meta"]["has_data"] is False
    finally:
        module.stop()
    broken, events = make_module({"adapter": "log_tail"})  # rules_file manquant
    broken.start()
    try:
        assert wait_for(lambda: bool(events))
        assert broken.health().degraded and "rules_file" in broken.health().detail
        assert events[0].payload["adapter"] is None and "rules_file" in events[0].payload["error"]
    finally:
        broken.stop()


def test_build_adapter_variants(tmp_path: Path) -> None:
    rules = tmp_path / "regles.yaml"
    rules.write_text("path: jeu.log\nrules:\n  - {field: zone, pattern: 'Zone: (.+)'}\n", encoding="utf-8")
    assert build_adapter({"adapter": "log_tail", "rules_file": str(rules)}).id == "log_tail"
    assert build_adapter({"adapter": "screen_ocr", "screen_ocr": {"fields": [{"name": "hp"}]}}).id == "screen_ocr"
    with pytest.raises(ValueError, match="inconnu"):
        build_adapter({"adapter": "telepathie"})


def test_heavy_sections_are_not_put_on_the_bus() -> None:
    state = {"character": {"name": "x"}, "mounts": {"list": ["m" * 50] * 1000}, "_meta": {"a": "b" * 30_000}}
    kept, omitted = compact(state)
    assert set(kept) == {"character", "_meta"} and omitted == ["mounts"]


def test_runs_inside_the_real_daemon_and_showcase_hides_private_data(game_dir: Path, tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Bout en bout : démon réel, module dans son processus, logiciel de diffusion simulé par un faux processus."""
    config = tmp_path / "local.yaml"
    config.write_text(json.dumps({"gaming_hud": {
        "game_path": str(game_dir), "autodetect": False, "poll_seconds": 0.3, "hide_character_names": True,
        "obs_hud_port": 0,
        "showcase_processes": ["diffusion-de-test.exe"]}}), encoding="utf-8")  # du JSON est du YAML valide
    monkeypatch.setenv("AETHERTWIN_CONFIG", str(config))
    processes = {"explorer.exe"}
    daemon = Daemon(REPO_MODULES, monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(processes))
    seen: list[Event] = []
    daemon.bus.subscribe("module.gaming_hud", seen.append)
    daemon.start()
    try:
        assert "gaming_hud" in daemon.modules, daemon.manifest_errors
        assert daemon.activate("gaming_hud").verdict is Verdict.GRANTED

        def states() -> list[dict]:
            return [e.payload for e in seen if e.topic == "module.gaming_hud.state"]

        assert wait_for(lambda: bool(states())), "le module n'a publié aucun état"
        assert states()[0]["state"]["character"]["name"] == NAME and states()[0]["showcase"] is False
        assert daemon.modules["gaming_hud"].running()

        processes.add("diffusion-de-test.exe")  # « OBS » démarre
        daemon.tick()
        assert wait_for(lambda: any(s["showcase"] for s in states())), "le mode Showcase ne s'est pas activé"
        after = [e for e in seen[[e.topic for e in seen].index("module.gaming_hud.showcase"):]]
        assert leaks([e.payload for e in after], PRIVATE) == [], "une donnée privée a été publiée en mode Showcase"

        processes.discard("diffusion-de-test.exe")  # « OBS » s'arrête
        daemon.tick()
        assert wait_for(lambda: states()[-1]["showcase"] is False)
    finally:
        daemon.stop()
    assert not daemon.modules["gaming_hud"].running()
