"""Moteurs de synthèse vocale, tous locaux, chacun dans son propre processus :

- **Piper** (MIT, rhasspy/piper 2023.11.14-2) : `piper.exe` et des voix `.onnx` installées par `installer.py` dans
  `data/voice/piper` ; rapide sur le processeur (≈ 15× le temps réel).
- **Voix de Windows** (SAPI, System.Speech) : rien à installer ; sert de secours.

Chaque moteur rend un WAV 16 bits mono. La vitesse se règle au moteur (`speed`, 0,5 à 2) ; la hauteur et les
effets s'appliquent ensuite (`effects.py`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_CHARS = 4000


PRONUNCIATION = ((re.compile(r"\bAetherTwin\b", re.I), "Éther Twinne"), (re.compile(r"(?:Æ|\bAe)ther\b"), "Éther"),
                 (re.compile(r"\bIF-Core\b"), "I F Core"))


def clean_text(text: str) -> str:
    """Texte prononçable : sans blocs de code, liens ni balises Markdown ; noms propres du projet respellés."""
    text = re.sub(r"```.*?```", " ", str(text), flags=re.S)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_`#>|~]+", " ", text)
    for pattern, spoken in PRONUNCIATION:
        text = pattern.sub(spoken, text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_CHARS]


def sentences(text: str) -> list[str]:
    """Découpe en phrases (pour commencer à parler avant la fin d'une longue réponse)."""
    parts = re.split(r"(?<=[.!?…:;])\s+", clean_text(text))
    return [p for p in parts if re.search(r"\w", p)]


class PiperEngine:
    name = "piper"

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    @property
    def exe(self) -> Path:
        return self.folder / "piper" / "piper.exe"

    def available(self) -> bool:
        return self.exe.is_file() and bool(self.voices())

    def voices(self) -> list[dict[str, Any]]:
        out = []
        for model in sorted((self.folder / "voices").glob("*.onnx")):
            meta_path = model.with_suffix(".onnx.json")
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            speakers = meta.get("speaker_id_map") or {}
            label = model.stem.replace("fr_FR-", "").replace("-", " ")
            out.append({"engine": "piper", "id": model.stem, "label": label,
                        "language": meta.get("language", {}).get("code", ""), "speakers": len(speakers) or 1,
                        "speaker_names": sorted(speakers, key=speakers.get)[:200] if speakers else []})
        return out

    def synthesize(self, text: str, voice: str, speed: float = 1.0, speaker: int = 0, timeout: float = 120) -> bytes:
        model = self.folder / "voices" / f"{voice}.onnx"
        if not re.fullmatch(r"[\w.-]{1,80}", voice) or not model.is_file():
            raise ValueError(f"voix Piper inconnue : {voice}")
        if not self.exe.is_file():
            raise RuntimeError("Piper n'est pas installé (Voix → Installer)")
        fd, out = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        args = [str(self.exe), "--model", str(model), "--output_file", out,
                "--length_scale", f"{1 / max(0.5, min(2.0, speed)):.3f}", "--sentence_silence", "0.15"]
        if speaker:
            args += ["--speaker", str(int(speaker))]
        try:
            proc = subprocess.run(args, input=clean_text(text).encode("utf-8"), capture_output=True,  # noqa: S603
                                  timeout=timeout, cwd=str(self.exe.parent), creationflags=NO_WINDOW, check=False)
            data = Path(out).read_bytes() if Path(out).is_file() else b""
            if proc.returncode != 0 or len(data) <= 44:
                detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["sortie vide"]
                raise RuntimeError(f"Piper a échoué : {detail[0][:200]}")
            return data
        finally:
            try:
                os.remove(out)
            except OSError:
                pass


class SapiEngine:
    """Voix de Windows. Le texte passe par l'entrée standard (jamais dans la ligne de commande)."""
    name = "sapi"

    def available(self) -> bool:
        return sys.platform == "win32"

    def _ps(self, script: str, stdin: bytes = b"", timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
                              input=stdin, capture_output=True, timeout=timeout, creationflags=NO_WINDOW, check=False)

    def voices(self) -> list[dict[str, Any]]:
        if not self.available():
            return []
        script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$s.GetInstalledVoices() | Where-Object Enabled | ForEach-Object { $_.VoiceInfo.Name + '|' + "
                  "$_.VoiceInfo.Culture.Name }")
        try:
            proc = self._ps(script, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return []
        out = []
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            if "|" in line:
                name, culture = line.strip().split("|", 1)
                out.append({"engine": "sapi", "id": name, "label": name.replace("Microsoft ", ""), "language": culture,
                            "speakers": 1, "speaker_names": []})
        return out

    def synthesize(self, text: str, voice: str, speed: float = 1.0, speaker: int = 0, timeout: float = 120) -> bytes:
        if not self.available():
            raise RuntimeError("la voix de Windows n'existe que sous Windows")
        rate = max(-10, min(10, round((speed - 1.0) * 10)))
        fd, out = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        payload = json.dumps({"text": clean_text(text), "voice": str(voice)[:120], "out": out}).encode("utf-8")
        script = ("[Console]::InputEncoding = [System.Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "
                  "$p = [Console]::In.ReadToEnd() | ConvertFrom-Json; "
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "if ($p.voice) { try { $s.SelectVoice($p.voice) } catch {} }; "
                  f"$s.Rate = {rate}; $s.SetOutputToWaveFile($p.out); $s.Speak($p.text); $s.Dispose()")
        try:
            proc = self._ps(script, payload, timeout)
            data = Path(out).read_bytes() if Path(out).is_file() else b""
            if len(data) <= 44:
                detail = proc.stderr.decode("utf-8", "replace").strip()[:200] or "sortie vide"
                raise RuntimeError(f"voix de Windows : {detail}")
            return data
        finally:
            try:
                os.remove(out)
            except OSError:
                pass
