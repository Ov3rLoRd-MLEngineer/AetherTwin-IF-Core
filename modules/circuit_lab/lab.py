"""Programmes de l'atelier circuits : exemples fournis (`examples/*.asm`) et programmes de l'utilisateur
(`data/circuit_lab/programs/*.asm`). L'assemblage et l'émulation se font dans la page (JavaScript)."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path("data") / "circuit_lab"
EXAMPLES = Path(__file__).resolve().parent / "examples"
MAX_SOURCE = 1_000_000
EXAMPLE_TITLES = {"etoiles": "Fuma et les étoiles", "lune16": "Fuma au clair de lune (console 16 bits)"}


def clean_name(name: Any) -> str:
    """Nom de fichier sûr : lettres, chiffres, tiret, soulignement, point (sans « .. » ni séparateur)."""
    text = re.sub(r"[^\w.-]+", "_", str(name or "").strip(), flags=re.UNICODE).strip("._")
    text = re.sub(r"\.asm$", "", text, flags=re.IGNORECASE)[:64]
    if not text:
        raise ValueError("nom de programme vide")
    return text


class Lab:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir
        self.programs = data_dir / "programs"

    # ---------- exemples ----------
    @staticmethod
    def examples() -> list[dict[str, str]]:
        return [{"name": p.stem, "title": EXAMPLE_TITLES.get(p.stem, p.stem)} for p in sorted(EXAMPLES.glob("*.asm"))]

    @staticmethod
    def example(name: Any) -> dict[str, str]:
        key = clean_name(name)
        path = EXAMPLES / f"{key}.asm"
        if not path.is_file():
            raise ValueError(f"exemple inconnu : {key}")
        return {"name": key, "title": EXAMPLE_TITLES.get(key, key), "source": path.read_text(encoding="utf-8")}

    # ---------- programmes de l'utilisateur ----------
    def list(self) -> list[dict[str, Any]]:
        if not self.programs.is_dir():
            return []
        items = [{"name": p.stem, "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)),
                  "size": p.stat().st_size} for p in self.programs.glob("*.asm")]
        return sorted(items, key=lambda item: item["modified"], reverse=True)

    def load(self, name: Any) -> dict[str, str]:
        key = clean_name(name)
        path = self.programs / f"{key}.asm"
        if not path.is_file():
            raise ValueError(f"programme introuvable : {key}")
        return {"name": key, "source": path.read_text(encoding="utf-8")}

    def save(self, name: Any, source: Any) -> dict[str, Any]:
        key = clean_name(name)
        text = str(source or "")
        if len(text) > MAX_SOURCE:
            raise ValueError("programme de plus d'un million de caractères")
        self.programs.mkdir(parents=True, exist_ok=True)
        path = self.programs / f"{key}.asm"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)
        return {"name": key, "size": len(text.encode("utf-8"))}

    def delete(self, name: Any) -> dict[str, str]:
        key = clean_name(name)
        path = self.programs / f"{key}.asm"
        if not path.is_file():
            raise ValueError(f"programme introuvable : {key}")
        path.unlink()
        return {"name": key}
