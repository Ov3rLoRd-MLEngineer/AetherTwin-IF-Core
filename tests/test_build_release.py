"""scripts/build_release.py : archive construite depuis Git, notes de version, refus des secrets."""
from __future__ import annotations

import io
import shutil
import zipfile

import pytest

from scripts import build_release as br

needs_git = pytest.mark.skipif(shutil.which("git") is None or not (br.ROOT / ".git").exists(),
                               reason="pas de dépôt Git (copie installée depuis l'archive)")


def make_zip(files: dict[str, str]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


def test_scan_accepts_clean_files() -> None:
    zf = make_zip({"p/README.md": "Bonjour", "p/config/local.example.yaml": "port: 5750\n"})
    assert br.scan_archive(zf) == []


def test_scan_refuses_secret_private_prompt_and_weights() -> None:
    fake_key = "sk-ant-" + "a" * 30
    zf = make_zip({"p/core/x.py": f"KEY = '{fake_key}'\n", "p/PROMPT_MAITRE_AetherTwin.md": "privé",
                   "p/models/m.safetensors": "", "p/config/local.yaml": "x: 1"})
    findings = "\n".join(br.scan_archive(zf))
    assert "p/core/x.py:1 — clé Anthropic" in findings
    assert "PROMPT_MAITRE_AetherTwin.md" in findings
    assert "m.safetensors" in findings
    assert "config/local.yaml" in findings


def test_release_name_and_notes() -> None:
    assert br.release_name("0.1.0", "abc1234") == "AetherTwin-IF-Core-0.1.0-abc1234"
    notes = br.release_notes("n", "0.1.0", "abc1234" * 5, "2026-11-25", "HEAD")
    assert "Installer AetherTwin.bat" in notes and "abc1234" in notes


@needs_git
def test_build_from_head(tmp_path) -> None:
    archive = br.build("HEAD", tmp_path, log=lambda *_: None)
    assert archive.exists() and (tmp_path / f"{archive.name}.sha256").exists()
    prefix = archive.stem + "/"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert prefix + "RELEASE.txt" in names
    assert prefix + "Installer AetherTwin.bat" in names
    assert prefix + "scripts/setup.ps1" in names
    assert not any("PROMPT_MAITRE" in n or "/.venv/" in n for n in names)


@needs_git
def test_unknown_ref_is_a_clear_error(tmp_path) -> None:
    with pytest.raises(br.ReleaseError):
        br.build("ce-tag-n-existe-pas", tmp_path, log=lambda *_: None)
