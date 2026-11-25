"""Garde-fou : aucun secret ni chemin personnel dans les fichiers versionnés.

Le règlement du concours interdit de soumettre des clés API, mots de passe ou credentials.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "cache", "data"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".lua", ".toc", ".ps1", ".bat",
                 ".cmd", ".cfg", ".ini", ".html", ".css", ".js", ".svg", ""}

SECRET_PATTERNS = {
    "clé Anthropic": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "clé de type OpenAI": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "jeton GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "jeton HuggingFace": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "clé AWS": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "clé privée": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "dossier utilisateur Windows": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b)[\w.-]+", re.IGNORECASE),
    "adresse e-mail personnelle": re.compile(r"[\w.+-]+@(gmail|outlook|hotmail|yahoo|proton)\.[a-z]{2,}", re.I),
}


def tracked_files() -> list[Path]:
    """Fichiers suivis ou à suivre selon Git ; à défaut (pas de dépôt), parcours du dossier."""
    if shutil.which("git") and (ROOT / ".git").exists():
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
        return [ROOT / line for line in out.splitlines() if line]
    return [p for p in ROOT.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def test_no_secret_or_personal_path_in_tracked_files() -> None:
    findings = []
    for path in tracked_files():
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line} — {label}")
    assert not findings, "Secrets ou chemins personnels détectés :\n" + "\n".join(findings)


@pytest.mark.parametrize("name", ["config/local.yaml", ".env", "PROMPT_MAITRE_AetherTwin.md"])
def test_sensitive_files_are_ignored_by_git(name: str) -> None:
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("pas de dépôt Git")
    proc = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT)
    assert proc.returncode == 0, f"{name} doit être ignoré par Git"


def test_example_config_exists_and_holds_no_key() -> None:
    text = (ROOT / "config" / "local.example.yaml").read_text(encoding="utf-8")
    assert "api_key" not in text.lower()


def test_no_control_character_in_scripts_and_pages() -> None:
    """Un caractère de contrôle glissé dans un chemin (« \a » devenu BEL, 25/11) casse un script sans erreur visible.

    Le fichier tiers xterm.js (minifié) en contient volontairement : il est exclu."""
    import re

    control = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
    suffixes = {".ps1", ".bat", ".py", ".js", ".css", ".html", ".md", ".yaml", ".json"}
    bad = []
    for path in tracked_files():
        if path.suffix not in suffixes or path.name.startswith("xterm"):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        if control.search(text):
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, bad
