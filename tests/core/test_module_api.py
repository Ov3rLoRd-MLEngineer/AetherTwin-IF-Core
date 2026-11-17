"""Contrat de module : validation du manifeste, découverte, événements."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import module_api as api

VALID = {
    "name": "demo_module", "version": "0.1.0", "description": "Module de démonstration",
    "entry": "modules.demo_module.main:DemoModule", "vram_min_gb": 2, "vram_comfort_gb": 4.5,
    "python_deps": ["PyYAML"], "optional_deps": ["torch"],
    "triggers": {"processes": ["obs64.exe"], "windows": ["OBS"], "ports": [5757]},
    "network": [], "experimental": True,
}


def write_module(root: Path, folder: str, manifest: object) -> None:
    (root / folder).mkdir(parents=True)
    text = manifest if isinstance(manifest, str) else json.dumps(manifest)
    (root / folder / api.MANIFEST_NAME).write_text(text, encoding="utf-8")


def test_valid_manifest() -> None:
    manifest = api.parse_manifest(VALID)
    assert manifest.name == "demo_module" and manifest.vram_min_gb == 2.0 and manifest.vram_comfort_gb == 4.5
    assert manifest.triggers.processes == ("obs64.exe",) and manifest.triggers.ports == (5757,)
    assert manifest.experimental and manifest.to_dict()["triggers"]["windows"] == ("OBS",)


def test_minimal_manifest_has_safe_defaults() -> None:
    manifest = api.parse_manifest({k: VALID[k] for k in ("name", "version", "description", "entry")})
    assert manifest.vram_min_gb == 0 and manifest.network == () and manifest.triggers == api.Triggers()


@pytest.mark.parametrize(("change", "expected"), [
    ({"name": ""}, "name"),
    ({"name": "Nom Invalide"}, "nom de module invalide"),
    ({"entry": "sans_classe"}, "entry"),
    ({"vram_min_gb": -1}, "vram_min_gb"),
    ({"vram_min_gb": "beaucoup"}, "vram_min_gb"),
    ({"vram_min_gb": 8, "vram_comfort_gb": 4}, "vram_comfort_gb"),
    ({"python_deps": "torch"}, "python_deps"),
    ({"triggers": {"ports": [70000]}}, "ports"),
    ({"triggers": []}, "triggers"),
    ({"app": {"module": "modules.x; del C:\\"}}, "app"),  # jamais une commande libre
    ({"app": {"module": "../evil"}}, "app"),
    ({"app": "notepad.exe"}, "app"),
])
def test_invalid_manifests_are_rejected_with_a_precise_message(change: dict, expected: str) -> None:
    with pytest.raises(api.ManifestError, match=expected):
        api.parse_manifest({**VALID, **change})


def test_manifest_app_is_a_python_module() -> None:
    manifest = api.parse_manifest({**VALID, "app": {"label": "WoW Assistant", "module": "modules.gaming_hud"}})
    assert manifest.app == ("WoW Assistant", "modules.gaming_hud")
    assert api.parse_manifest(VALID).app is None


def test_manifest_must_be_an_object() -> None:
    with pytest.raises(api.ManifestError):
        api.parse_manifest(["pas", "un", "objet"])


def test_discover_keeps_going_past_broken_modules(tmp_path: Path) -> None:
    write_module(tmp_path, "bon", VALID)
    write_module(tmp_path, "casse", "{ pas du json")
    write_module(tmp_path, "doublon", VALID)
    write_module(tmp_path, "invalide", {**VALID, "name": "autre", "vram_min_gb": -3})
    (tmp_path / "sans_manifeste").mkdir()
    found, errors = api.discover_manifests(tmp_path)
    assert list(found) == ["demo_module"]
    assert set(errors) == {"casse", "doublon", "invalide"}
    assert "illisible" in errors["casse"] and "double" in errors["doublon"]


def test_discover_on_missing_folder() -> None:
    assert api.discover_manifests(Path("dossier/qui/n/existe/pas")) == ({}, {})


def test_load_manifest_missing_file(tmp_path: Path) -> None:
    with pytest.raises(api.ManifestError, match="absent"):
        api.load_manifest(tmp_path)


def test_event_roundtrip_and_topic_matching() -> None:
    event = api.Event("gpu.alert", {"gpu": 0}, source="fuma", ts=12.0)
    assert api.Event.from_dict(event.to_dict()) == event
    assert event.matches("gpu.*") and event.matches("gpu") and event.matches("*") and event.matches("gpu.alert")
    assert not event.matches("gpus") and not event.matches("process.*")


def test_module_base_lifecycle() -> None:
    class Demo(api.ModuleBase):
        started = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.started = False

        def health(self) -> api.Health:
            return api.Health(ok=self.started, degraded=True, detail="sans GPU")

    module = Demo(api.parse_manifest(VALID))
    assert module.name == "demo_module" and not module.health().ok
    module.start()
    assert module.health().to_dict() == {"ok": True, "degraded": True, "detail": "sans GPU"}
    module.handle_event(api.Event("x"))  # ignoré par défaut
    module.publish(api.Event("x"))  # sans bus : ne fait rien, ne lève rien
    assert module.widget_schema()["title"] == "Module de démonstration"
    with pytest.raises(TypeError):
        api.ModuleBase(api.parse_manifest(VALID))  # type: ignore[abstract]
