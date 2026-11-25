"""Dépendances d'AetherTwin : liste, présence sur ce PC, liens officiels, et installations lancées depuis le Hub.

Deux familles :
- les logiciels externes (Ollama, Claude Code, Git…) : le Hub donne seulement le lien officiel et dit s'ils sont
  trouvés ; il ne les installe jamais lui-même ;
- les pièces d'AetherTwin (dépendances Python facultatives, poids HandSegNet et FootSegNet) : le Hub peut les
  installer, sur demande, par une liste FERMÉE de tâches (aucune commande ni adresse ne vient de la page).

Les liens ont été vérifiés le 25/11/2026 (sauf GPU-Z, dont le site refuse les robots).
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models" / "mangastudio"
HF = "https://huggingface.co/Ov3rLoRd-MLEngineer"

# Fiches des modèles de Jérémy (d'après les fiches Hugging Face et les dépôts GitHub, lues le 25/11/2026).
SEGNET = {
    "hand": {
        "nom": "HandSegNet", "sujet": "mains",
        "resume": "SAM ViT-B affiné pour segmenter les mains sur des illustrations anime. Seul le décodeur de "
                  "masque est entraîné ; les encodeurs d'image et de boîte restent ceux de Meta.",
        "github": "https://github.com/Ov3rLoRd-MLEngineer/handsegnet-anime-sdxl",
        "huggingface": f"{HF}/handsegnet-anime-sdxl",
        "chiffres": [["IoU, boîte exacte", "0,888"], ["IoU, boîte trouvée automatiquement", "0,722"],
                     ["Images annotées à la main", "320"], ["Paramètres entraînés", "≈ 4,1 M sur 93,7 M"]],
        "donnees": "320 illustrations anime (1024 × 1280, rendus SDXL fabricatedXL), masques tracés à la main ; "
                   "32 images gardées pour la validation.",
        "limites": "Une boîte par main ; deux mains proches peuvent fusionner, des doigts écartés peuvent manquer. "
                   "Entraîné uniquement sur des images SDXL de style anime.",
        "fichier": "handsegnet_vit_b_best.safetensors",
    },
    "foot": {
        "nom": "FootSegNet", "sujet": "pieds et chaussures",
        "resume": "SAM ViT-B affiné pour segmenter les pieds et les chaussures sur des illustrations anime. Seul "
                  "le décodeur de masque est entraîné.",
        "github": "https://github.com/Ov3rLoRd-MLEngineer/footsegnet-anime-sdxl",
        "huggingface": f"{HF}/footsegnet-anime-sdxl",
        "chiffres": [["IoU, boîte exacte", "0,928"], ["Images annotées à la main", "300"],
                     ["Paramètres entraînés", "≈ 4 M sur 93,7 M"], ["Base", "SAM ViT-B (Meta)"]],
        "donnees": "300 illustrations anime (1024 × 1536, rendus SDXL fabricatedXL), masques tracés à la main ; "
                   "30 images gardées pour la validation.",
        "limites": "Une boîte par pied ; des pieds qui se chevauchent donnent un seul masque. Entraîné uniquement "
                   "sur des images SDXL de style anime : le score de validation est optimiste hors de ce domaine.",
        "fichier": "footsegnet_vit_b_best.safetensors",
    },
}
LICENCE_POIDS = "Apache 2.0 (poids)"


def _which(*names: str) -> bool:
    return any(shutil.which(n) for n in names)


def _windows_terminal() -> bool:
    from modules.dev_launcher.launch import windows_terminal
    return bool(windows_terminal())


def _hermes() -> bool:
    from modules.genesis_lab.sources import hermes_exe
    return bool(hermes_exe())


def _module(*names: str) -> bool:
    return all(importlib.util.find_spec(n) is not None for n in names)


# id, groupe, nom, rôle, lien officiel, test de présence (None : non vérifiable)
EXTERNAL: list[tuple[str, str, str, str, str, Callable[[], bool] | None]] = [
    ("python", "base", "Python 3.11", "fait tourner le Hub et ses modules",
     "https://www.python.org/downloads/windows/", lambda: _which("py", "python")),
    ("git", "base", "Git pour Windows", "dépôt, et dépendances GPU (segment-anything s'installe depuis Git)",
     "https://git-scm.com/downloads/win", lambda: _which("git")),
    ("ollama", "ia", "Ollama", "modèles de langage locaux (Assistant, Professeur, Scantrad, jeu)",
     "https://ollama.com/download/windows", lambda: _which("ollama")),
    ("claude_code", "dev", "Claude Code", "agent de développement (onglet Développement)",
     "https://code.claude.com/docs/en/setup", lambda: _which("claude")),
    ("windows_terminal", "dev", "Windows Terminal", "ouvre Claude Code dans un vrai terminal",
     "https://aka.ms/terminal", _windows_terminal),
    ("hermes", "dev", "Hermes Agent (Nous Research)", "agent relié au Hub par le pont MCP",
     "https://github.com/NousResearch/hermes-agent", _hermes),
    ("omniroute", "dev", "OmniRoute (facultatif)", "routeur de modèles ; Ollama suffit sans lui",
     "https://github.com/diegosouzapw/OmniRoute", lambda: _which("omniroute")),
    ("comfyui", "image", "ComfyUI (facultatif)", "accueille les nœuds HandSegNet et FootSegNet d'AetherTwin",
     "https://github.com/comfyanonymous/ComfyUI", None),
]

# Tâches que le Hub sait lancer. Rien d'autre n'est accepté.
JOBS: dict[str, dict[str, Any]] = {
    "gpu": {"nom": "Dépendances de la segmentation (PyTorch CUDA, segment-anything, safetensors)",
            "taille": "≈ 3 Go", "groupe": "image",
            "present": lambda: _module("torch", "segment_anything", "safetensors")},
    "voice": {"nom": "Reconnaissance vocale locale (faster-whisper)", "taille": "≈ 100 Mo + modèle au 1er usage",
              "groupe": "ia", "present": lambda: _module("faster_whisper")},
    "weights_hand": {"nom": "Poids HandSegNet (Hugging Face)", "taille": "375 Mo", "groupe": "image",
                     "present": lambda: (MODELS_DIR / SEGNET["hand"]["fichier"]).is_file()},
    "weights_foot": {"nom": "Poids FootSegNet (Hugging Face)", "taille": "375 Mo", "groupe": "image",
                     "present": lambda: (MODELS_DIR / SEGNET["foot"]["fichier"]).is_file()},
}

_state: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def dependencies() -> dict[str, Any]:
    """Tout ce que les pages affichent : logiciels externes (lien), tâches installables (état), fiches SegNet."""
    external = []
    for key, group, name, role, link, test in EXTERNAL:
        try:
            present = test() if test else None
        except Exception:
            present = None
        external.append({"id": key, "groupe": group, "nom": name, "role": role, "lien": link, "present": present})
    return {"externes": external, "taches": [job_state(key) for key in JOBS], "segnet": SEGNET,
            "licence_poids": LICENCE_POIDS}


def job_state(key: str) -> dict[str, Any]:
    job = JOBS[key]
    with _lock:
        state = dict(_state.get(key, {}))
    log = list(state.pop("log", []))
    try:
        present = bool(job["present"]())
    except Exception:
        present = False
    return {"id": key, "nom": job["nom"], "taille": job["taille"], "groupe": job["groupe"], "present": present,
            "etat": state.get("etat", "fait" if present else "absent"), "detail": state.get("detail", ""),
            "journal": log[-12:]}


def start(key: str, runner: Callable[[str, Callable[[str], None]], None] | None = None) -> dict[str, Any]:
    """Lance la tâche `key` dans un fil ; une seule fois à la fois. KeyError si la tâche est inconnue."""
    if key not in JOBS:
        raise KeyError(key)
    with _lock:
        if _state.get(key, {}).get("etat") == "en cours":
            return {"lance": False, "raison": "déjà en cours"}
        _state[key] = {"etat": "en cours", "detail": "démarrage…", "log": deque(maxlen=200), "debut": time.time()}

    def say(line: str) -> None:
        with _lock:
            _state[key]["detail"] = line
            _state[key]["log"].append(line)

    def work() -> None:
        try:
            (runner or _run)(key, say)
            with _lock:
                _state[key]["etat"] = "fait"
            say("Terminé.")
        except Exception as error:  # l'échec est montré dans la page, pas avalé
            with _lock:
                _state[key]["etat"] = "échec"
            say(f"Échec : {error}")

    threading.Thread(target=work, daemon=True, name=f"setup-{key}").start()
    return {"lance": True}


def _run(key: str, say: Callable[[str], None]) -> None:
    if key in ("gpu", "voice"):
        requirements = REPO_ROOT / ("requirements-gpu.txt" if key == "gpu" else "requirements-voice.txt")
        _pip(requirements, say)
    elif key in ("weights_hand", "weights_foot"):
        card = SEGNET[key.split("_")[1]]
        url = f"{card['huggingface']}/resolve/main/{card['fichier']}"
        download(url, MODELS_DIR / card["fichier"], say)


def _pip(requirements: Path, say: Callable[[str], None]) -> None:
    say(f"pip install -r {requirements.name} (le Python du Hub)")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r",
                             str(requirements)], cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=flags)
    for line in proc.stdout or []:
        line = line.strip()
        if line:
            say(line[:200])
    if proc.wait() != 0:
        raise RuntimeError(f"pip a échoué (code {proc.returncode}) ; Git est-il installé ?")


def download(url: str, target: Path, say: Callable[[str], None], opener=urllib.request.urlopen) -> None:
    """Téléchargement par morceaux dans un .part, renommé à la fin : jamais de fichier de poids à moitié écrit."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    say(f"Téléchargement de {target.name}…")
    try:
        with opener(url, timeout=60) as response, part.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done, last = 0, 0.0
            while chunk := response.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if time.monotonic() - last > 1:
                    last = time.monotonic()
                    size = f"{done / 2**20:.0f} Mo" + (f" sur {total / 2**20:.0f} Mo" if total else "")
                    say(f"{target.name} : {size}")
        if total and done != total:
            raise RuntimeError(f"téléchargement incomplet ({done} octets sur {total})")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
