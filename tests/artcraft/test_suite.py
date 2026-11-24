"""Intégration ArtCraft : catalogue, garde-fous d'installation (adresses, empreinte, archive), MCP — sans réseau."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from modules.artcraft import suite as S
from modules.artcraft.module import ArtCraftModule


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fake_net(monkeypatch, routes: dict[str, bytes]) -> list[str]:
    seen: list[str] = []

    def urlopen(request, timeout=0):
        url = request.full_url
        seen.append(url)
        if url not in routes:
            raise OSError(f"404 {url}")
        return FakeResponse(routes[url])

    monkeypatch.setattr(S.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(S.os, "environ", {})   # pas d'installation .msi trouvée ailleurs sur la machine de test
    return seen


def release(app: str, zip_bytes: bytes, sums: str | None = None, name: str | None = None) -> dict[str, bytes]:
    name = name or f"{app}-0.1.0-windows-x64-portable.zip"
    base = f"https://github.com/storytold/{app}/releases/download/v0.1.0/"
    assets = [{"name": name, "size": len(zip_bytes), "browser_download_url": base + name}]
    routes = {base + name: zip_bytes}
    if sums is not None:
        assets.append({"name": "SHA256SUMS.txt", "size": len(sums), "browser_download_url": base + "SHA256SUMS.txt"})
        routes[base + "SHA256SUMS.txt"] = sums.encode()
    routes[f"https://api.github.com/repos/storytold/{app}/releases/latest"] = json.dumps(
        {"tag_name": "v0.1.0", "assets": assets}).encode()
    return routes


def run_install(suite: S.Suite, app: str) -> dict:
    job = {"running": True, "step": "", "done": 0, "total": 0, "error": ""}
    suite._install(app, job)
    return job


def test_catalog_lists_the_ten_apps(tmp_path):
    suite = S.Suite(tmp_path)
    apps = suite.catalog()
    assert [a["app"] for a in apps] == list(S.CATALOG)
    assert len(apps) == 10 and not any(a["installed"] for a in apps)
    assert {a["family"] for a in apps} == {"Création (Adobe)", "Bureautique (Microsoft Office)"}
    with pytest.raises(ValueError):
        S.check_app("../photocraft")


def test_fetch_refuses_foreign_urls():
    for url in ("https://example.com/x.zip", "https://github.com/autre/photocraft/releases/download/v1/x.zip",
                "http://github.com/storytold/photocraft"):
        with pytest.raises(ValueError):
            S.fetch(url)


def test_pick_asset_prefers_portable_zip():
    assets = [{"name": "a-1-windows-x64.msi"}, {"name": "a-1-linux-x64.tar.gz"},
              {"name": "a-1-windows-x64-portable.zip"}]
    assert S.pick_asset(assets)["name"].endswith("portable.zip")
    assert S.pick_asset(assets[:2])["name"].endswith(".msi")
    assert S.pick_asset(assets[1:2]) is None


def test_install_portable_verified(monkeypatch, tmp_path):
    data = make_zip({"gridcraft/gridcraft.exe": b"MZ", "gridcraft/gridcraft-cli.exe": b"MZ"})
    name = "gridcraft-0.1.0-windows-x64-portable.zip"
    sums = f"{hashlib.sha256(data).hexdigest()}  {name}\n{'0' * 64}  autre.msi\n"
    fake_net(monkeypatch, release("gridcraft", data, sums))
    suite = S.Suite(tmp_path)
    job = run_install(suite, "gridcraft")
    assert job["error"] == "" and not job["running"]
    entry = next(a for a in suite.catalog() if a["app"] == "gridcraft")
    assert entry["installed"] and entry["version"] == "v0.1.0" and entry["portable"]
    suite._help[entry["cli"]] = True   # version qui accepte les dossiers d'automatisation
    info = suite.mcp("gridcraft")
    assert info["command"].endswith("gridcraft-cli.exe")
    assert info["args"] == ["mcp", "--automation-read-root", info["folder"], "--automation-write-root", info["folder"]]
    assert Path(info["folder"]).is_dir() and Path(info["folder"]).name == "echange"
    assert info["claude_code"].startswith("claude mcp add gridcraft -- ")
    assert not list((tmp_path / "downloads").glob("*"))
    suite.uninstall("gridcraft")
    assert not suite.catalog()[8]["installed"]


def test_install_rejects_bad_hash(monkeypatch, tmp_path):
    data = make_zip({"photocraft.exe": b"MZ"})
    fake_net(monkeypatch, release("photocraft", data, f"{'a' * 64}  photocraft-0.1.0-windows-x64-portable.zip\n"))
    suite = S.Suite(tmp_path)
    job = run_install(suite, "photocraft")
    assert "SHA-256" in job["error"]
    assert not (tmp_path / "apps" / "photocraft").exists()
    assert not list((tmp_path / "downloads").glob("*"))


def test_install_requires_published_sums(monkeypatch, tmp_path):
    fake_net(monkeypatch, release("pdfcraft", make_zip({"pdfcraft.exe": b"MZ"}), sums=None))
    job = run_install(S.Suite(tmp_path), "pdfcraft")
    assert "SHA256SUMS" in job["error"]


def test_install_rejects_zip_traversal(monkeypatch, tmp_path):
    data = make_zip({"../evil.exe": b"MZ"})
    name = "wordcraft-0.1.0-windows-x64-portable.zip"
    fake_net(monkeypatch, release("wordcraft", data, f"{hashlib.sha256(data).hexdigest()}  {name}\n"))
    job = run_install(S.Suite(tmp_path), "wordcraft")
    assert "suspect" in job["error"]
    assert not (tmp_path / "apps" / "evil.exe").exists()


def test_install_rejects_unexpected_download_host(monkeypatch, tmp_path):
    routes = release("deckcraft", make_zip({"deckcraft.exe": b"MZ"}), "x")
    api = "https://api.github.com/repos/storytold/deckcraft/releases/latest"
    body = json.loads(routes[api])
    body["assets"][0]["browser_download_url"] = "https://example.com/deckcraft.zip"
    routes[api] = json.dumps(body).encode()
    fake_net(monkeypatch, routes)
    job = run_install(S.Suite(tmp_path), "deckcraft")
    assert "inattendue" in job["error"]


def test_no_windows_build(monkeypatch, tmp_path):
    fake_net(monkeypatch, {"https://api.github.com/repos/storytold/filmcraft/releases/latest":
                           json.dumps({"tag_name": "v0.0.1", "assets": [{"name": "filmcraft-linux.tar.gz"}]}).encode()})
    job = run_install(S.Suite(tmp_path), "filmcraft")
    assert "Windows" in job["error"]


def test_icons_are_downscaled_locally(monkeypatch, tmp_path):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (1024, 1024), (200, 40, 90, 255)).save(buf, "PNG")
    routes = {S.ICON.format(app=app): buf.getvalue() for app in S.CATALOG if app != "lightcraft"}
    fake_net(monkeypatch, routes)
    suite = S.Suite(tmp_path)
    result = suite.fetch_icons()
    assert len(result["icons"]) == 9 and result["failed"][0].startswith("lightcraft")
    with Image.open(io.BytesIO(suite.icon("photocraft"))) as img:
        assert img.size == (128, 128)
    with pytest.raises(ValueError):
        suite.icon("lightcraft")


def test_module_commands(tmp_path):
    module = ArtCraftModule.__new__(ArtCraftModule)
    module.suite = S.Suite(tmp_path)
    assert len(module.run("catalog", {})) == 10
    with pytest.raises(ValueError):
        module.run("mcp", {"app": "photocraft"})
    with pytest.raises(ValueError):
        module.run("nope", {})


def test_hermes_register_uses_external_command(monkeypatch, tmp_path):
    from modules.dev_launcher import hermes_link

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))   # jamais la vraie configuration d'Hermes
    calls = []

    class Done:
        returncode = 0
        stdout = stderr = ""

    def runner(cmd, **kw):
        calls.append(cmd)
        (tmp_path / "config.yaml").write_text("mcp_servers:\n  artcraft_gridcraft:\n    command: x\n", encoding="utf-8")
        return Done()

    hermes_link.register_server("hermes.exe", "artcraft_gridcraft", ["mcp"], runner=runner,
                                command="C:/x/gridcraft-cli.exe")
    assert calls[0][calls[0].index("--command") + 1] == "C:/x/gridcraft-cli.exe"
    assert calls[0][-1] == "mcp"


def test_manifest_and_ui_wired():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "modules/artcraft/manifest.json").read_text(encoding="utf-8"))
    assert manifest["entry"] == "modules.artcraft.module:ArtCraftModule"
    html = (root / "core/web/dashboard.html").read_text(encoding="utf-8")
    assert 'data-sub="ArtCraft"' in html and "artcraft_tool.js" in html and "Intégration externe" in html
