"""circuit_lab : commandes du module, fenêtre de bureau, page de l'atelier (CSP du Hub respectée) et vérifications
de la console en JavaScript (processeur, assembleur, carte mère, jeu d'exemple) quand Node.js est installé."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.module_api import load_manifest
from modules.circuit_lab import app, lab
from modules.circuit_lab.module import CircuitLabModule

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "core" / "web"
HERE = Path(__file__).resolve().parent
PAGES = ("circuit_app", "crt")
SCRIPTS = ("nes_cpu.js", "asm6502.js", "nes_ppu.js", "nes_machine.js", "crt.js", "crt_tv.js", "circuit_audio.js")


def make(tmp_path: Path) -> CircuitLabModule:
    module = CircuitLabModule(load_manifest(ROOT / "modules" / "circuit_lab"), {"data_dir": str(tmp_path / "data")})
    module.start()
    return module


def test_examples_and_programs(tmp_path: Path) -> None:
    module = make(tmp_path)
    assert {"name": "etoiles", "title": "Fuma et les étoiles"} in module.run("examples", {})
    example = module.run("example", {"name": "etoiles"})
    assert ".vectors" in example["source"]
    with pytest.raises(ValueError):
        module.run("example", {"name": "../module"})
    assert module.run("projects", {}) == []
    saved = module.run("project_save", {"name": "Mon jeu!", "source": "\t.org $C000\n"})
    assert saved["name"] == "Mon_jeu"
    assert module.run("project_load", {"name": "Mon_jeu"})["source"] == "\t.org $C000\n"
    assert [p["name"] for p in module.run("projects", {})] == ["Mon_jeu"]
    module.run("project_delete", {"name": "Mon_jeu"})
    assert module.run("projects", {}) == []
    with pytest.raises(ValueError):
        module.run("project_load", {"name": "Mon_jeu"})
    with pytest.raises(ValueError):
        module.run("inconnue", {})
    assert module.health().ok


def test_clean_name_keeps_files_in_the_folder() -> None:
    assert lab.clean_name("../../etc/passwd") == "etc_passwd"
    assert lab.clean_name("jeu.asm") == "jeu"
    with pytest.raises(ValueError):
        lab.clean_name("...")


def test_window_and_page(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_manifest(ROOT / "modules" / "circuit_lab").app == ("Atelier circuits Æther", "modules.circuit_lab.app")
    from core import config

    monkeypatch.setattr(config, "section", lambda name, path=None: {"port": 5761} if name == "daemon" else {})
    assert app.page_url() == "http://127.0.0.1:5761/static/circuit_app.html"
    opened: list[str] = []
    monkeypatch.setattr(app, "find_browser", lambda: None)
    monkeypatch.setattr(app.webbrowser, "open", opened.append)
    assert app.main() == 0 and opened[0].endswith("/static/circuit_app.html")

    for name in PAGES:
        page = (WEB / f"{name}.html").read_text(encoding="utf-8")
        script = (WEB / ("circuit_app.js" if name == "circuit_app" else "crt_tv.js")).read_text(encoding="utf-8")
        assert " style=" not in page  # la CSP du Hub refuse les styles en ligne
        assert "<script>" not in page
        ids = set(re.findall(r'\$\("([\w-]+)"\)', script))
        missing = sorted(i for i in ids if f'id="{i}"' not in page)
        assert ids and not missing, f"{name} : identifiants absents de la page : {missing}"
        for src in re.findall(r'src="/static/([\w.]+)"', page):
            assert (WEB / src).is_file(), src
    for name in (*SCRIPTS, "circuit_app.js", "circuit_app.css", "crt.css", "circuit_app.html", "crt.html"):
        text = (WEB / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!127\.0\.0\.1)", text.replace("http://www.w3.org/2000/svg", "")), name
        assert 'setAttribute("style"' not in text and "style:" not in text.replace("font-style:", ""), name


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js absent : vérifications JavaScript de la console non lancées")
@pytest.mark.parametrize(("script", "expected"), [
    ("asm_check.js", "assembleur : ok"),
    ("machine_check.js", "carte mère : ok"),
    ("demo_check.js", "jeu d'exemple : ok"),
])
def test_console_in_javascript(script: str, expected: str) -> None:
    done = subprocess.run([NODE, str(HERE / script)], capture_output=True, text=True, encoding="utf-8",  # noqa: S603
                          timeout=120, check=False)
    assert done.returncode == 0, done.stderr or done.stdout
    assert expected in done.stdout
