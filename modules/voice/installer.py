"""Installation de Piper et des voix françaises libres, depuis leurs sources officielles uniquement (adresses fixes).

    data/voice/piper/piper/piper.exe        rhasspy/piper 2023.11.14-2 (MIT ; espeak-ng inclus, GPL-3, programme séparé)
    data/voice/piper/voices/<voix>.onnx     rhasspy/piper-voices v1.0.0 (configuration compatible avec ce binaire)

Voix retenues (licence des données d'entraînement) : siwis (CC-BY 4.0), upmc (CC-BY-SA 4.0), gilles (CC0),
mls (CC-BY 4.0, 125 voix). « tom » est écartée (AGPL).
"""
from __future__ import annotations

import io
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

PIPER_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR"
VOICES: dict[str, dict[str, str]] = {
    "fr_FR-siwis-medium": {"path": "siwis/medium", "label": "Siwis (féminine)", "license": "CC-BY 4.0"},
    "fr_FR-upmc-medium": {"path": "upmc/medium", "label": "UPMC (Jessica, Pierre)", "license": "CC-BY-SA 4.0"},
    "fr_FR-gilles-low": {"path": "gilles/low", "label": "Gilles (masculine)", "license": "CC0"},
    "fr_FR-mls-medium": {"path": "mls/medium", "label": "MLS (125 voix)", "license": "CC-BY 4.0"},
}
ALLOWED_HOSTS = ("https://github.com/rhasspy/", "https://huggingface.co/rhasspy/")
MAX_DOWNLOAD = 200_000_000


def fetch(url: str, timeout: float = 120) -> bytes:
    if not url.startswith(ALLOWED_HOSTS):
        raise ValueError("source non autorisée")
    request = urllib.request.Request(url, headers={"User-Agent": "AetherTwin-voice/0.1"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — adresses fixes ci-dessus
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("fichier trop gros")
    return data


def extract_zip(data: bytes, target: Path) -> int:
    """Extrait sans jamais sortir de `target` (chemins absolus ou « .. » refusés)."""
    target = target.resolve()
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            path = (target / member.filename).resolve()
            if target not in path.parents and path != target:
                raise ValueError(f"chemin refusé dans l'archive : {member.filename}")
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count


def status(folder: Path) -> dict[str, Any]:
    folder = Path(folder)
    return {"piper": (folder / "piper" / "piper.exe").is_file(),
            "voices": {key: (folder / "voices" / f"{key}.onnx").is_file() for key in VOICES},
            "catalog": [{"id": k, **v} for k, v in VOICES.items()]}


def install(folder: Path, voices: list[str] | None = None, fetcher: Callable[[str], bytes] = fetch) -> dict[str, Any]:
    """Installe Piper (s'il manque) et les voix demandées (toutes par défaut) ; rend ce qui a été ajouté."""
    folder = Path(folder)
    wanted = list(VOICES) if voices is None else [v for v in voices if v in VOICES]
    added: list[str] = []
    if not (folder / "piper" / "piper.exe").is_file():
        extract_zip(fetcher(PIPER_URL), folder)
        if not (folder / "piper" / "piper.exe").is_file():
            raise RuntimeError("archive Piper inattendue (piper.exe absent)")
        added.append("piper")
    (folder / "voices").mkdir(parents=True, exist_ok=True)
    for key in wanted:
        model = folder / "voices" / f"{key}.onnx"
        if model.is_file():
            continue
        base = f"{VOICES_BASE}/{VOICES[key]['path']}/{key}"
        config = fetcher(base + ".onnx.json")
        onnx = fetcher(base + ".onnx")
        (folder / "voices" / f"{key}.onnx.json").write_bytes(config)
        tmp = model.with_suffix(".part")
        tmp.write_bytes(onnx)
        tmp.replace(model)
        added.append(key)
    return {"added": added, **status(folder)}
