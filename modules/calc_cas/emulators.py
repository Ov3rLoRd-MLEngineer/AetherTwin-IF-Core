"""Lanceur d'émulateurs externes pour l'application Programmes.

Aucun émulateur, aucune ROM, aucun BIOS n'est fourni : la calculatrice **détecte** les émulateurs open source déjà
installés sur le PC et lance celui choisi sur un fichier que l'utilisateur a placé lui-même dans le dossier des ROM
(`data/calc_cas/roms`, par défaut). À l'utilisateur de n'y mettre que des fichiers qu'il a le droit d'utiliser
(jeux « homebrew » libres, sauvegardes de ses propres cartouches et disques).

Les systèmes vont jusqu'à ce qu'un téléphone haut de gamme de 2019 (type Galaxy S10+) émule correctement, et
au-delà : Game Boy, NES, Super Nintendo, Mega Drive, GBA, N64, DS, PlayStation, PSP, Dreamcast, GameCube / Wii,
3DS, PlayStation 2. Un PC de bureau récent fait mieux qu'un S10+ sur tous ces systèmes.

Lancement : une liste d'arguments fixe (jamais de shell), un exécutable trouvé à un emplacement connu, dans le PATH
ou indiqué dans la configuration (`calc_cas.emulators: {id: chemin}`), et un fichier pris dans le dossier des ROM.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# système -> (nom affiché, extensions, niveau de puissance indicatif sur téléphone)
SYSTEMS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "gb": ("Game Boy / Color", (".gb", ".gbc"), "léger"),
    "nes": ("NES", (".nes",), "léger"),
    "snes": ("Super Nintendo", (".sfc", ".smc"), "léger"),
    "md": ("Mega Drive / Genesis", (".md", ".gen", ".smd"), "léger"),
    "gba": ("Game Boy Advance", (".gba",), "léger"),
    "n64": ("Nintendo 64", (".n64", ".z64", ".v64"), "moyen"),
    "nds": ("Nintendo DS", (".nds",), "moyen"),
    "ps1": ("PlayStation", (".cue", ".chd", ".pbp", ".m3u"), "moyen"),
    "psp": ("PSP", (".iso", ".cso"), "moyen"),
    "dc": ("Dreamcast", (".gdi", ".cdi"), "moyen"),
    "gc": ("GameCube / Wii", (".gcm", ".rvz", ".wbfs", ".ciso", ".gcz", ".wad", ".dol", ".elf"), "élevé (niveau S10+)"),
    "3ds": ("Nintendo 3DS", (".3ds", ".cci", ".cxi", ".3dsx"), "élevé (niveau S10+)"),
    "ps2": ("PlayStation 2", (".iso", ".chd", ".bin"), "très élevé (au-delà d'un S10+)"),
}

PF, PF86, LAD = "%ProgramFiles%", "%ProgramFiles(x86)%", "%LocalAppData%"
# id -> nom, systèmes, exécutables candidats (chemins Windows connus ou nom dans le PATH), arguments avant le fichier
EMULATORS: dict[str, dict[str, Any]] = {
    "mgba": {"label": "mGBA", "systems": ("gb", "gba"),
             "exe": (rf"{PF}\mGBA\mGBA.exe", rf"{PF86}\mGBA\mGBA.exe", "mgba.exe", "mGBA.exe"), "args": ()},
    "mesen": {"label": "Mesen", "systems": ("nes", "snes", "gb", "gba"),
              "exe": (rf"{PF}\Mesen\Mesen.exe", rf"{LAD}\Mesen\Mesen.exe", "Mesen.exe"), "args": ()},
    "snes9x": {"label": "Snes9x", "systems": ("snes",),
               "exe": (rf"{PF}\Snes9x\snes9x-x64.exe", "snes9x-x64.exe", "snes9x.exe"), "args": ()},
    "blastem": {"label": "BlastEm", "systems": ("md",), "exe": ("blastem.exe",), "args": ()},
    "simple64": {"label": "simple64", "systems": ("n64",),
                 "exe": (rf"{LAD}\simple64\simple64-gui.exe", rf"{PF}\simple64\simple64-gui.exe", "simple64-gui.exe"),
                 "args": ()},
    "melonds": {"label": "melonDS", "systems": ("nds",),
                "exe": (rf"{PF}\melonDS\melonDS.exe", rf"{LAD}\melonDS\melonDS.exe", "melonDS.exe"), "args": ()},
    "duckstation": {"label": "DuckStation", "systems": ("ps1",),
                    "exe": (rf"{LAD}\Programs\DuckStation\duckstation-qt-x64-ReleaseLTCG.exe",
                            rf"{PF}\DuckStation\duckstation-qt-x64-ReleaseLTCG.exe",
                            "duckstation-qt-x64-ReleaseLTCG.exe"),
                    "args": ()},
    "ppsspp": {"label": "PPSSPP", "systems": ("psp",),
               "exe": (rf"{PF}\PPSSPP\PPSSPPWindows64.exe", rf"{PF86}\PPSSPP\PPSSPPWindows64.exe",
                       "PPSSPPWindows64.exe"),
               "args": ()},
    "flycast": {"label": "Flycast", "systems": ("dc",), "exe": (rf"{PF}\flycast\flycast.exe", "flycast.exe"),
                "args": ()},
    "dolphin": {"label": "Dolphin", "systems": ("gc",),
                "exe": (rf"{PF}\Dolphin\Dolphin.exe", rf"{PF}\Dolphin-x64\Dolphin.exe", "Dolphin.exe"),
                "args": ("-e",)},
    "azahar": {"label": "Azahar / Lime3DS", "systems": ("3ds",),
               "exe": (rf"{LAD}\Azahar\azahar.exe", rf"{PF}\Azahar\azahar.exe", rf"{LAD}\Lime3DS\lime3ds.exe",
                       "azahar.exe", "lime3ds.exe", "lime3ds-gui.exe"), "args": ()},
    "pcsx2": {"label": "PCSX2", "systems": ("ps2",), "exe": (rf"{PF}\PCSX2\pcsx2-qt.exe", "pcsx2-qt.exe"), "args": ()},
    "retroarch": {"label": "RetroArch (cœur choisi par RetroArch)", "systems": tuple(SYSTEMS),
                  "exe": (r"C:\RetroArch-Win64\retroarch.exe", rf"{PF}\RetroArch\retroarch.exe", "retroarch.exe"),
                  "args": ()},
}
MAX_ROMS = 500


def _expand(path: str) -> Path | None:
    expanded = os.path.expandvars(path)
    return None if "%" in expanded else Path(expanded)


def find_exe(candidates: tuple[str, ...], which: Callable[[str], str | None] = shutil.which) -> str | None:
    for raw in candidates:
        if "\\" in raw or "/" in raw:
            path = _expand(raw)
            if path is not None and path.is_file():
                return str(path)
        else:
            found = which(raw)
            if found:
                return found
    return None


def detect(configured: dict[str, Any] | None = None,
           which: Callable[[str], str | None] = shutil.which) -> dict[str, dict[str, Any]]:
    """Émulateurs connus et leur exécutable (None s'il n'est pas installé). La configuration est prioritaire."""
    out: dict[str, dict[str, Any]] = {}
    for key, spec in EMULATORS.items():
        path = None
        custom = (configured or {}).get(key)
        if custom and Path(str(custom)).is_file() and str(custom).lower().endswith(".exe"):
            path = str(custom)
        out[key] = {"label": spec["label"], "systems": list(spec["systems"]),
                    "path": path or find_exe(spec["exe"], which)}
    return out


def system_of(name: str) -> list[str]:
    suffix = Path(name).suffix.lower()
    return [key for key, (_label, exts, _tier) in SYSTEMS.items() if suffix in exts]


def list_roms(folder: Path) -> list[dict[str, Any]]:
    if not folder.is_dir():
        return []
    roms = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and system_of(path.name):
            roms.append({"file": path.relative_to(folder).as_posix(), "systems": system_of(path.name),
                         "size_mb": round(path.stat().st_size / 1e6, 1)})
            if len(roms) >= MAX_ROMS:
                break
    return roms


def rom_path(folder: Path, name: str) -> Path:
    """Fichier du dossier des ROM ; refuse tout chemin qui en sortirait."""
    base = folder.resolve()
    path = (base / str(name)).resolve()
    if base not in path.parents or not path.is_file():
        raise ValueError("fichier introuvable dans le dossier des ROM")
    if not system_of(path.name):
        raise ValueError(f"type de fichier non reconnu : {path.suffix}")
    return path


def command(emulator: str, rom: Path, found: dict[str, dict[str, Any]]) -> list[str]:
    if emulator not in EMULATORS:
        raise ValueError(f"émulateur inconnu : {emulator}")
    info = found.get(emulator) or {}
    if not info.get("path"):
        raise ValueError(f"{EMULATORS[emulator]['label']} n'est pas installé sur ce PC")
    if not set(system_of(rom.name)) & set(EMULATORS[emulator]["systems"]):
        raise ValueError(f"{EMULATORS[emulator]['label']} ne lit pas les fichiers {rom.suffix}")
    return [str(info["path"]), *EMULATORS[emulator]["args"], str(rom)]


def launch(args: list[str], popen: Callable[..., Any] = subprocess.Popen) -> int:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) if sys.platform == "win32" else 0
    proc = popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 cwd=str(Path(args[0]).parent), creationflags=flags)
    return int(proc.pid)


def catalog(folder: Path, configured: dict[str, Any] | None = None) -> dict[str, Any]:
    found = detect(configured)
    return {"systems": [{"id": k, "label": v[0], "extensions": list(v[1]), "tier": v[2]} for k, v in SYSTEMS.items()],
            "emulators": [{"id": k, **v} for k, v in found.items()], "roms": list_roms(folder), "folder": str(folder)}
