"""Construit l'archive installable d'AetherTwin à partir d'un commit Git, et peut la vérifier à neuf.

    python scripts/build_release.py                  # dist/AetherTwin-IF-Core-<version>-<commit>.zip (+ .sha256)
    python scripts/build_release.py --verify         # + décompression dans dist/verify, setup.ps1, pytest
    python scripts/build_release.py --ref v0.1.0-concours

L'archive ne contient que ce qui est **commité** (`git archive`) : ni `.venv`, ni `config/local.yaml`, ni
données, ni poids de modèles, ni le prompt de mission privé. Les modifications non commitées sont signalées
et laissées de côté. Avant d'écrire l'archive, le script cherche les secrets et les chemins personnels avec
les motifs du garde-fou `tests/test_repo_hygiene.py`, et refuse de continuer s'il en trouve.

Après un ajout au projet : commiter, puis relancer la même commande. L'archive est refaite.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_repo_hygiene import SECRET_PATTERNS, TEXT_SUFFIXES  # noqa: E402

PRODUCT = "AetherTwin-IF-Core"
# Fichiers qui ne doivent jamais partir dans l'archive, même s'ils avaient été commités par erreur.
FORBIDDEN_NAMES = {"PROMPT_MAITRE_AetherTwin.md", "local.yaml", ".env", "settings.json", "chat_history.json"}
FORBIDDEN_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".gguf", ".key", ".pem", ".sqlite"}


class ReleaseError(RuntimeError):
    """Construction ou vérification impossible ; le message dit pourquoi."""


def git(*args: str, cwd: Path = ROOT) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} : {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def release_name(version: str, short_sha: str) -> str:
    return f"{PRODUCT}-{version}-{short_sha}"


def scan_archive(zf: zipfile.ZipFile) -> list[str]:
    """Secrets, chemins personnels et fichiers interdits trouvés dans l'archive (liste vide : propre)."""
    findings: list[str] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = Path(info.filename)
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"{info.filename} — fichier interdit dans l'archive")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = zf.read(info).decode("utf-8", errors="replace")
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{info.filename}:{line} — {label}")
    return findings


def release_notes(name: str, version: str, sha: str, commit_date: str, ref: str) -> str:
    built = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        f"{PRODUCT} {version}\n"
        f"Commit : {sha} ({commit_date}), référence demandée : {ref}\n"
        f"Archive construite le {built} par scripts/build_release.py\n"
        "\n"
        "Installation (Windows 10 ou 11, Python 3.11) :\n"
        "  1. Décompresser l'archive dans un dossier de votre choix.\n"
        "  2. Double-clic sur « Installer AetherTwin.bat » (options : -Gpu -Weights -Voice -Shortcut).\n"
        "  3. Double-clic sur « Lancer AetherTwin.bat » : le Hub s'ouvre sur http://127.0.0.1:5750/.\n"
        "Modèles conseillés (Ollama) : qwen3-27b, qwen2.5vl:7b, nomic-embed-text.\n"
        "Tests : .venv\\Scripts\\python.exe -m pytest\n"
        "Détails : README.md, docs/RELEASE.md.\n"
    )


def build(ref: str = "HEAD", out_dir: Path | None = None, version: str | None = None,
          log=print) -> Path:
    """Construit l'archive et son empreinte SHA-256 ; renvoie le chemin de l'archive."""
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        raise ReleaseError("il faut Git et le dépôt cloné (le dossier .git) pour construire l'archive")
    sha = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    short = sha[:7]
    commit_date = git("show", "-s", "--format=%cs", sha)
    version = version or project_version()
    name = release_name(version, short)
    out_dir = Path(out_dir or ROOT / "dist")
    out_dir.mkdir(parents=True, exist_ok=True)

    if ref == "HEAD":
        dirty = [line for line in git("status", "--porcelain", "--untracked-files=no").splitlines() if line]
        if dirty:
            log(f"Attention : {len(dirty)} fichier(s) modifié(s) non commité(s), laissé(s) hors de l'archive :")
            for line in dirty[:10]:
                log(f"  {line}")

    raw = subprocess.run(["git", "archive", "--format=zip", f"--prefix={name}/", sha], cwd=ROOT,
                         capture_output=True)
    if raw.returncode != 0:
        raise ReleaseError("git archive : " + raw.stderr.decode("utf-8", errors="replace").strip())

    with zipfile.ZipFile(io.BytesIO(raw.stdout)) as zf:
        findings = scan_archive(zf)
        if findings:
            raise ReleaseError("archive refusée, à corriger d'abord :\n  " + "\n  ".join(findings))
        count = sum(1 for i in zf.infolist() if not i.is_dir())

    target = out_dir / f"{name}.zip"
    target.write_bytes(raw.stdout)
    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}/RELEASE.txt", release_notes(name, version, sha, commit_date, ref))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (out_dir / f"{name}.zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    log(f"Archive : {target} ({target.stat().st_size / 1_048_576:.1f} Mo, {count + 1} fichiers)")
    log(f"Commit  : {sha} ({commit_date})")
    log(f"SHA-256 : {digest}")
    return target


def verify(archive: Path, setup_args: list[str], log=print) -> None:
    """Installe l'archive à neuf dans dist/verify (setup.ps1), puis lance toute la suite de tests dedans."""
    if sys.platform != "win32":
        raise ReleaseError("--verify passe par setup.ps1 : Windows seulement")
    base = archive.parent / "verify"
    folder = base / archive.stem
    if folder.exists():
        shutil.rmtree(folder)
    base.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(base)
    if not folder.is_dir():
        raise ReleaseError(f"dossier attendu absent après décompression : {folder}")
    log(f"Installation à neuf dans {folder}")

    start = time.monotonic()
    setup = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(folder / "scripts" / "setup.ps1"), *setup_args], cwd=folder,
                           stdin=subprocess.DEVNULL)
    if setup.returncode != 0:
        raise ReleaseError(f"setup.ps1 a échoué (code {setup.returncode})")
    log(f"setup.ps1 : terminé en {time.monotonic() - start:.0f} s")

    python = folder / ".venv" / "Scripts" / "python.exe"
    start = time.monotonic()
    tests = subprocess.run([str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=folder,
                           stdin=subprocess.DEVNULL)
    if tests.returncode != 0:
        raise ReleaseError(f"des tests échouent dans la copie installée (code {tests.returncode})")
    log(f"pytest : suite verte dans la copie installée, en {time.monotonic() - start:.0f} s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construit l'archive installable d'AetherTwin.")
    parser.add_argument("--ref", default="HEAD", help="commit, branche ou tag à empaqueter (défaut : HEAD)")
    parser.add_argument("--out", type=Path, default=None, help="dossier de sortie (défaut : dist/)")
    parser.add_argument("--version", default=None, help="numéro de version (défaut : celui de pyproject.toml)")
    parser.add_argument("--verify", action="store_true",
                        help="installer l'archive à neuf dans dist/verify et y lancer toute la suite de tests")
    parser.add_argument("--setup-args", default="",
                        help="options passées à setup.ps1 pendant --verify, par exemple \"-Gpu\"")
    args = parser.parse_args(argv)
    try:
        archive = build(args.ref, args.out, args.version)
        if args.verify:
            verify(archive, args.setup_args.split())
    except ReleaseError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
