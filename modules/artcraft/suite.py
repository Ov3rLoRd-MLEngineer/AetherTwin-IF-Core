"""Suite ArtCraft : catalogue, installation depuis les publications GitHub officielles, lancement, MCP.

Intégration **externe** : ces logiciels libres (MIT ou Apache 2.0, au choix) sont écrits et publiés par l'équipe
ArtCraft (`github.com/storytold`) ; ils ne sont ni fournis avec AetherTwin ni affiliés au projet, à Adobe ou à
Microsoft. Rien n'est téléchargé sans un clic. Garde-fous :

- adresses fixes : API GitHub de `storytold/<appli>` et ses fichiers de publication, rien d'autre ;
- version Windows **portable** (zip, sans droits administrateur) de préférence, sinon l'installateur `.msi` officiel,
  ouvert pour que l'utilisateur l'accepte lui-même ;
- empreinte SHA-256 comparée à `SHA256SUMS.txt` de la même publication : sans empreinte publiée, refus ;
- archive extraite sans sortir de son dossier (`data/artcraft/apps/<appli>/`).

Les icônes viennent du kit presse officiel (getartcraft.com/press-kit) et restent sur ce PC (`data/artcraft/icons`) :
le nom et les logos ArtCraft sont des marques de l'équipe ArtCraft, hors licence libre, rien n'est versé au dépôt.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path("data") / "artcraft"
OWNER = "storytold"
API = f"https://api.github.com/repos/{OWNER}/"
DOWNLOAD = f"https://github.com/{OWNER}/"
ICON = f"https://raw.githubusercontent.com/{OWNER}/{{app}}/main/assets/app-icon/{{app}}-1024.png"
USER_AGENT = "AetherTwin-ArtCraft-integration"
MAX_DOWNLOAD = 1_500_000_000
FLAGS = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) \
    if sys.platform == "win32" else 0

# appli → (nom, rôle, alternative à, famille)
CATALOG: dict[str, tuple[str, str, str, str]] = {
    "photocraft": ("PhotoCraft", "retouche photo et montage d'images", "Photoshop", "Création (Adobe)"),
    "vectorcraft": ("VectorCraft", "dessin et illustration vectorielle", "Illustrator", "Création (Adobe)"),
    "filmcraft": ("FilmCraft", "montage vidéo", "Premiere Pro", "Création (Adobe)"),
    "lightcraft": ("LightCraft", "catalogue photo et développement RAW", "Lightroom", "Création (Adobe)"),
    "effectcraft": ("EffectCraft", "effets visuels et animation", "After Effects", "Création (Adobe)"),
    "designcraft": ("DesignCraft", "mise en page et édition", "InDesign", "Création (Adobe)"),
    "pdfcraft": ("PdfCraft", "lire, fusionner, découper et sécuriser des PDF", "Acrobat Pro", "Création (Adobe)"),
    "wordcraft": ("WordCraft", "traitement de texte (.docx)", "Word", "Bureautique (Microsoft Office)"),
    "gridcraft": ("GridCraft", "feuilles de calcul (.xlsx)", "Excel", "Bureautique (Microsoft Office)"),
    "deckcraft": ("DeckCraft", "présentations (.pptx)", "PowerPoint", "Bureautique (Microsoft Office)"),
}


def check_app(app: Any) -> str:
    key = str(app or "").strip().lower()
    if key not in CATALOG:
        raise ValueError(f"application inconnue : {key!r}")
    return key


def fetch(url: str, limit: int = 20_000_000, timeout: float = 60) -> bytes:
    """GET limité aux adresses ArtCraft connues."""
    allowed = (API, DOWNLOAD, f"https://raw.githubusercontent.com/{OWNER}/")
    if not url.startswith(allowed):
        raise ValueError("adresse refusée (hors publications ArtCraft)")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — adresses fixes ci-dessus
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("réponse trop grosse")
    return data


def pick_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le zip portable Windows x64 d'abord, sinon l'installateur .msi x64."""
    for suffix in ("-windows-x64-portable.zip", "-windows-x64.msi"):
        for asset in assets:
            if str(asset.get("name", "")).endswith(suffix):
                return asset
    return None


def parse_sums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and len(parts[0]) == 64:
            sums[parts[-1].lstrip("*")] = parts[0].lower()
    return sums


def safe_extract(archive: Path, target: Path) -> None:
    """Extrait un zip sans laisser un nom de fichier sortir de `target`."""
    root = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            dest = (root / info.filename).resolve()
            if dest != root and root not in dest.parents:
                raise ValueError(f"archive refusée : chemin suspect {info.filename!r}")
        zf.extractall(root)


class Suite:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir
        self.apps_dir = data_dir / "apps"
        self.icons_dir = data_dir / "icons"
        self.downloads = data_dir / "downloads"
        self.state_file = data_dir / "state.json"
        self.jobs: dict[str, dict[str, Any]] = {}
        self._help: dict[str, bool] = {}   # outil → accepte les dossiers d'automatisation
        self._lock = threading.Lock()

    # ---------- état ----------
    def _state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    def find_exe(self, app: str) -> tuple[str, str]:
        """(programme, outil en ligne de commande) : version portable d'abord, puis installation .msi."""
        places = [self.apps_dir / app]
        name = CATALOG[app][0]
        for env in ("ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                places += [Path(base) / name, Path(base) / "Programs" / name, Path(base) / "ArtCraft" / name]
        for place in places:
            if not place.is_dir():
                continue
            exe = next(iter(sorted(place.rglob(f"{app}.exe"))), None)
            cli = next(iter(sorted(place.rglob(f"{app}-cli.exe"))), None)
            if exe or cli:
                return str(exe or ""), str(cli or "")
        return "", ""

    def catalog(self) -> list[dict[str, Any]]:
        state = self._state()
        out = []
        for app, (name, role, alt, family) in CATALOG.items():
            exe, cli = self.find_exe(app)
            out.append({"app": app, "name": name, "role": role, "alternative": alt, "family": family,
                        "installed": bool(exe or cli), "exe": exe, "cli": cli,
                        "portable": (self.apps_dir / app).is_dir(),
                        "version": state.get(app, {}).get("version", ""),
                        "icon": (self.icons_dir / f"{app}.png").is_file(),
                        "job": self.jobs.get(app), "page": f"https://getartcraft.com/apps/{app}",
                        "repo": f"{DOWNLOAD}{app}"})
        return out

    # ---------- icônes ----------
    def fetch_icons(self) -> dict[str, Any]:
        """Télécharge les icônes officielles (kit presse) et les réduit à 128 px pour l'interface."""
        from PIL import Image

        self.icons_dir.mkdir(parents=True, exist_ok=True)
        got, failed = [], []
        for app in CATALOG:
            try:
                raw = fetch(ICON.format(app=app), limit=8_000_000)
                with Image.open(io.BytesIO(raw)) as img:
                    small = img.convert("RGBA").resize((128, 128), Image.LANCZOS)
                    small.save(self.icons_dir / f"{app}.png")
                got.append(app)
            except (OSError, ValueError) as exc:
                failed.append(f"{app} : {exc}")
        return {"icons": got, "failed": failed}

    def icon(self, app: Any) -> bytes:
        path = self.icons_dir / f"{check_app(app)}.png"
        if not path.is_file():
            raise ValueError("icône pas encore téléchargée")
        return path.read_bytes()

    # ---------- installation ----------
    def install_async(self, app: Any) -> dict[str, Any]:
        key = check_app(app)
        with self._lock:
            job = self.jobs.get(key)
            if job and job.get("running"):
                return job
            job = {"running": True, "step": "recherche de la dernière version…", "done": 0, "total": 0, "error": ""}
            self.jobs[key] = job
        threading.Thread(target=self._install, args=(key, job), daemon=True, name=f"artcraft-{key}").start()
        return job

    def _install(self, app: str, job: dict[str, Any]) -> None:
        try:
            release = json.loads(fetch(f"{API}{app}/releases/latest"))
            tag = str(release.get("tag_name", ""))
            assets = release.get("assets") or []
            asset = pick_asset(assets)
            if asset is None:
                raise ValueError(f"pas de version Windows x64 dans la publication {tag}")
            sums_asset = next((a for a in assets if a.get("name") == "SHA256SUMS.txt"), None)
            if sums_asset is None:
                raise ValueError("pas d'empreintes publiées (SHA256SUMS.txt) : installation refusée")
            prefix = f"{DOWNLOAD}{app}/releases/download/"
            for a in (asset, sums_asset):
                if not str(a.get("browser_download_url", "")).startswith(prefix):
                    raise ValueError("adresse de téléchargement inattendue")
            sums = fetch(sums_asset["browser_download_url"]).decode("utf-8", "replace")
            expected = parse_sums(sums).get(asset["name"])
            if not expected:
                raise ValueError(f"{asset['name']} absent de SHA256SUMS.txt : installation refusée")
            self.downloads.mkdir(parents=True, exist_ok=True)
            target = self.downloads / asset["name"]
            job.update(step=f"téléchargement de {asset['name']}", total=int(asset.get("size") or 0))
            self._download(asset["browser_download_url"], target, expected, job)
            state = self._state()
            if target.suffix == ".zip":
                job.update(step="extraction…")
                folder = self.apps_dir / app
                shutil.rmtree(folder, ignore_errors=True)
                folder.mkdir(parents=True)
                safe_extract(target, folder)
                target.unlink(missing_ok=True)
                state[app] = {"version": tag, "kind": "portable", "date": time.strftime("%Y-%m-%d %H:%M")}
                job.update(step=f"{CATALOG[app][0]} {tag} installé")
            else:
                state[app] = {"version": tag, "kind": "msi", "date": time.strftime("%Y-%m-%d %H:%M")}
                job.update(step="installateur Windows ouvert : termine l'installation dans sa fenêtre")
                if sys.platform == "win32":
                    os.startfile(target)  # noqa: S606 — fichier officiel vérifié par son empreinte
            self._save(state)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            job["error"] = str(exc) or type(exc).__name__
        finally:
            job["running"] = False

    def _download(self, url: str, target: Path, sha256: str, job: dict[str, Any]) -> None:
        part = target.with_suffix(target.suffix + ".part")
        digest = hashlib.sha256()
        got = 0
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:  # noqa: S310
            while chunk := response.read(1 << 20):
                got += len(chunk)
                if got > MAX_DOWNLOAD:
                    raise ValueError("fichier plus gros que prévu")
                digest.update(chunk)
                out.write(chunk)
                job["done"] = got
        if digest.hexdigest() != sha256:
            part.unlink(missing_ok=True)
            raise ValueError("empreinte SHA-256 différente de celle publiée : fichier rejeté")
        part.replace(target)

    def uninstall(self, app: Any) -> dict[str, Any]:
        key = check_app(app)
        folder = self.apps_dir / key
        if not folder.is_dir():
            raise ValueError("seule la version portable installée ici se retire depuis le Hub "
                             "(un .msi se désinstalle par les paramètres de Windows)")
        shutil.rmtree(folder)
        state = self._state()
        state.pop(key, None)
        self._save(state)
        return {"app": key, "removed": True}

    # ---------- lancement et MCP ----------
    def launch(self, app: Any) -> dict[str, Any]:
        key = check_app(app)
        exe, _cli = self.find_exe(key)
        if not exe:
            raise ValueError(f"{CATALOG[key][0]} n'est pas installé")
        subprocess.Popen([exe], cwd=str(Path(exe).parent), creationflags=FLAGS,  # noqa: S603 — programme installé
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"app": key, "exe": exe}

    def mcp(self, app: Any) -> dict[str, Any]:
        """Commandes pour brancher le serveur MCP de l'appli (stdio : `<appli>-cli mcp`)."""
        key = check_app(app)
        _exe, cli = self.find_exe(key)
        if not cli:
            raise ValueError(f"outil en ligne de commande {key}-cli introuvable : installe {CATALOG[key][0]} d'abord")
        # Sans dossier accordé, le serveur sans interface ne peut lire ni écrire aucun fichier : on lui donne le
        # dossier d'échange (lecture et écriture), et seulement lui, si sa version connaît ces options.
        work = (self.root / "echange").resolve()
        args = ["mcp"]
        if self.supports_roots(cli):
            work.mkdir(parents=True, exist_ok=True)
            args += ["--automation-read-root", str(work), "--automation-write-root", str(work)]
        line = " ".join(f'"{a}"' if " " in a or "\\" in a else a for a in [cli, *args])
        return {"app": key, "name": f"artcraft_{key}", "command": cli, "args": args, "folder": str(work),
                "claude_code": f"claude mcp add {key} -- {line}"}

    def supports_roots(self, cli: str) -> bool:
        if cli not in self._help:
            try:
                out = subprocess.run([cli, "mcp", "--help"], capture_output=True, text=True, timeout=20,  # noqa: S603
                                     encoding="utf-8", errors="replace",
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._help[cli] = "--automation-write-root" in (out.stdout or "") + (out.stderr or "")
            except (OSError, subprocess.SubprocessError):
                self._help[cli] = False
        return self._help[cli]

    def hermes(self, app: Any, register: bool = False) -> dict[str, Any]:
        from modules.dev_launcher import hermes_link
        from modules.genesis_lab.sources import hermes_exe

        info = self.mcp(app)
        exe = hermes_exe()
        result: dict[str, Any] = {}
        if register:
            result = hermes_link.register_server(exe, info["name"], info["args"], command=info["command"])
        config = hermes_link.hermes_home() / "config.yaml"
        text = config.read_text(encoding="utf-8", errors="replace") if config.is_file() else ""
        return {**info, **result, "installe": bool(exe), "branche": hermes_link.registered(text, info["name"])}
