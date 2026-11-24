"""calc_cas, émulateurs externes : détection, dossier des ROM fermé, commande sans shell. Rien n'est fourni."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.calc_cas import emulators


def test_every_emulator_targets_known_systems() -> None:
    for spec in emulators.EMULATORS.values():
        assert set(spec["systems"]) <= set(emulators.SYSTEMS)
    assert {"gc", "3ds", "ps2"} <= set(emulators.SYSTEMS)  # au niveau d'un téléphone type S10+, et au-delà


def test_detect_uses_path_and_configuration(tmp_path: Path) -> None:
    exe = tmp_path / "mon-mgba.exe"
    exe.write_bytes(b"")
    found = emulators.detect({"mgba": str(exe), "pcsx2": str(tmp_path / "absent.exe")},
                             which=lambda name: r"C:\bin\retroarch.exe" if name == "retroarch.exe" else None)
    assert found["mgba"]["path"] == str(exe)
    assert found["retroarch"]["path"] == r"C:\bin\retroarch.exe"
    assert found["pcsx2"]["path"] is None


def test_roms_stay_inside_their_folder(tmp_path: Path) -> None:
    roms = tmp_path / "roms"
    (roms / "gba").mkdir(parents=True)
    (roms / "gba" / "demo.gba").write_bytes(b"x" * 10)
    (roms / "notes.txt").write_text("pas une rom", encoding="utf-8")
    (tmp_path / "dehors.gba").write_bytes(b"x")
    assert [r["file"] for r in emulators.list_roms(roms)] == ["gba/demo.gba"]
    assert emulators.rom_path(roms, "gba/demo.gba").name == "demo.gba"
    for bad in ("../dehors.gba", str(tmp_path / "dehors.gba"), "notes.txt", "absent.gba"):
        with pytest.raises(ValueError):
            emulators.rom_path(roms, bad)
    assert emulators.list_roms(tmp_path / "absent") == []


def test_command_checks_install_and_system(tmp_path: Path) -> None:
    rom = tmp_path / "jeu.gba"
    found = {"mgba": {"path": r"C:\mGBA\mGBA.exe"}, "dolphin": {"path": r"C:\Dolphin\Dolphin.exe"},
             "pcsx2": {"path": None}}
    assert emulators.command("mgba", rom, found) == [r"C:\mGBA\mGBA.exe", str(rom)]
    assert emulators.command("dolphin", tmp_path / "x.rvz", found)[1] == "-e"
    with pytest.raises(ValueError, match="ne lit pas"):
        emulators.command("dolphin", rom, found)
    with pytest.raises(ValueError, match="pas installé"):
        emulators.command("pcsx2", tmp_path / "x.iso", found)
    with pytest.raises(ValueError, match="inconnu"):
        emulators.command("autre", rom, found)


def test_launch_is_a_plain_argument_list() -> None:
    seen = {}

    def popen(args, **kw):
        seen.update(args=args, **kw)
        return SimpleNamespace(pid=42)

    assert emulators.launch([r"C:\mGBA\mGBA.exe", r"D:\roms\a.gba"], popen=popen) == 42
    assert seen["args"] == [r"C:\mGBA\mGBA.exe", r"D:\roms\a.gba"] and "shell" not in seen


def test_catalog_shape(tmp_path: Path) -> None:
    cat = emulators.catalog(tmp_path)
    assert {s["id"] for s in cat["systems"]} == set(emulators.SYSTEMS)
    assert {e["id"] for e in cat["emulators"]} == set(emulators.EMULATORS) and cat["roms"] == []
