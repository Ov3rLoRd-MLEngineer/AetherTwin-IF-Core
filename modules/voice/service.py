"""Service vocal partagé par le module du Hub et le serveur MCP : profils, synthèse, écoute, lecture sur le PC.

    data/voice/profiles.json          profils et choix par défaut
    data/voice/piper/                 Piper et ses voix (installer.py)
    data/voice/tmp/                   échanges de fichiers audio avec l'API du Hub (effacés après usage)
"""
from __future__ import annotations

import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from modules.voice import convert, effects, engines, installer, stt
from modules.voice.profiles import ProfileStore, validate

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "voice"
TMP_NAME = re.compile(r"[0-9a-f]{32}\.(wav|webm|ogg|mp3|m4a|flac|bin)")
TMP_MAX_AGE = 600  # s
VBCABLE_URL = "https://vb-audio.com/Cable/"


def vbcable_status() -> dict[str, Any]:
    """VB-Cable (VB-Audio, gratuit, à installer soi-même) : présent si un périphérique audio « VB-Audio » existe."""
    found: list[str] = []
    if sys.platform == "win32":
        import subprocess

        try:
            proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",  # noqa: S607
                                   "Get-CimInstance Win32_SoundDevice | ForEach-Object { $_.Name }"],
                                  capture_output=True, timeout=20, creationflags=engines.NO_WINDOW, check=False)
            names = proc.stdout.decode("utf-8", "replace").splitlines()
            found = [n.strip() for n in names if "vb-audio" in n.lower()]
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {"installed": bool(found), "devices": found, "url": VBCABLE_URL,
            "hint": "Après l'installation, la sortie « CABLE Input » apparaît : choisis-la dans le modulateur, puis "
                    "« CABLE Output » comme micro dans Discord ou le jeu."}


class VoiceService:
    def __init__(self, data_dir: Path = DATA_DIR, whisper_model: str = "small", whisper_device: str = "cpu",
                 vc_device: str = "cpu") -> None:
        self.data_dir = Path(data_dir)
        self.profiles = ProfileStore(self.data_dir / "profiles.json")
        self.piper = engines.PiperEngine(self.data_dir / "piper")
        self.sapi = engines.SapiEngine()
        self.transcriber = stt.Transcriber(whisper_model, whisper_device,
                                           "int8" if whisper_device == "cpu" else "float16")
        self.tmp = self.data_dir / "tmp"
        self.bank = convert.VoiceBank(self.data_dir / "bank")
        self.converter = convert.Converter(self.data_dir / "knnvc", self.bank, vc_device)
        self._play_lock = threading.Lock()
        self._playing = False

    # ---------- état ----------
    def status(self) -> dict[str, Any]:
        install = installer.status(self.piper.folder)
        return {"piper": self.piper.exe.is_file(), "piper_voices": [k for k, v in install["voices"].items() if v],
                "sapi": self.sapi.available(), "whisper": stt.available(), "whisper_model": self.transcriber.model_name,
                "whisper_loaded": self.transcriber.loaded(), "catalog": install["catalog"],
                "playing": self._playing, "conversion": self.converter.status(),
                **{k: v for k, v in self.profiles.all().items() if k != "profiles"}}

    def voices(self) -> list[dict[str, Any]]:
        return self.piper.voices() + self.sapi.voices()

    # ---------- synthèse ----------
    def _engine_for(self, profile: dict[str, Any]) -> tuple[Any, str, str]:
        """Moteur, voix et note ; repli sur la voix de Windows si Piper ou la voix manquent."""
        if profile.get("engine") == "piper":
            if self.piper.exe.is_file() and (self.piper.folder / "voices" / f"{profile.get('voice')}.onnx").is_file():
                return self.piper, str(profile["voice"]), ""
            if self.sapi.available():
                return self.sapi, "", "Piper ou la voix manque : voix de Windows en attendant (Voix → Installer)"
            raise RuntimeError("Piper n'est pas installé (Voix → Installer)")
        return self.sapi, str(profile.get("voice", "")), ""

    def synthesize(self, text: str, profile: str | None = None, speed: float | None = None,
                   effects_override: Any = None, inline: Any = None) -> dict[str, Any]:
        """`inline` : profil complet non enregistré (essai depuis le studio), validé comme les autres."""
        if not engines.clean_text(text):
            raise ValueError("rien à dire (texte vide)")
        p = validate(inline) if isinstance(inline, dict) else self.profiles.get(profile)
        if p["kind"] != "synthese":
            raise ValueError(f"« {p['id']} » est un profil de micro, pas de synthèse")
        engine, voice, note = self._engine_for(p)
        started = time.monotonic()
        wav = engine.synthesize(text, voice, float(speed or p.get("speed", 1.0)), int(p.get("speaker", 0)))
        if p.get("convert"):  # timbre d'une voix de la banque (enregistrée avec consentement)
            wav = self.converter.convert_wav(wav, p["convert"])
        settings = dict(p.get("effects") or {})
        if isinstance(effects_override, dict):
            settings.update(effects_override)
        wav = effects.apply_wav(wav, settings, level=True)  # même volume pour toutes les voix
        out = {"wav": wav, "profile": p["id"], "engine": engine.name, "voice": voice,
               "seconds": round(time.monotonic() - started, 2)}
        if note:
            out["note"] = note
        return out

    # ---------- lecture sur le PC ----------
    def play(self, wav: bytes) -> None:
        if sys.platform != "win32":
            raise RuntimeError("lecture directe disponible sous Windows seulement")
        import winsound

        def run() -> None:
            with self._play_lock:
                self._playing = True
                try:
                    winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
                finally:
                    self._playing = False
        threading.Thread(target=run, name="voice-play", daemon=True).start()

    def stop(self) -> bool:
        was = self._playing
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        return was

    # ---------- écoute ----------
    def transcribe(self, audio: bytes, language: str | None = "fr") -> dict[str, Any]:
        return self.transcriber.transcribe(audio, language)

    # ---------- fichiers d'échange avec l'API ----------
    def tmp_path(self, name: str) -> Path:
        if not TMP_NAME.fullmatch(str(name)):
            raise ValueError("fichier d'échange invalide")
        return self.tmp / name

    def tmp_write(self, data: bytes, suffix: str = "wav") -> str:
        self.tmp.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for old in self.tmp.iterdir():  # ménage : rien ne traîne plus de 10 min
            try:
                if now - old.stat().st_mtime > TMP_MAX_AGE:
                    old.unlink()
            except OSError:
                pass
        name = f"{uuid.uuid4().hex}.{suffix}"
        (self.tmp / name).write_bytes(data)
        return name

    def install(self, voices: list[str] | None = None) -> dict[str, Any]:
        return installer.install(self.piper.folder, voices)
