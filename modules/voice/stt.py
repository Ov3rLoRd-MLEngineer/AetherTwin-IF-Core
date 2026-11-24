"""Reconnaissance vocale locale (faster-whisper, MIT ; modèles Whisper, MIT), un seul modèle chargé pour tout le Hub.

Par défaut sur le processeur en int8 : la VRAM reste aux modèles de langue. Tout format lisible par PyAV est
accepté (WAV, WebM/Opus du navigateur, MP3, OGG…).
"""
from __future__ import annotations

import io
import threading
import time
from typing import Any

MODELS = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")
MAX_AUDIO = 5_500_000  # octets (le bus du Hub transporte 8 Mo au plus, base64 compris)


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


class Transcriber:
    def __init__(self, model: str = "small", device: str = "cpu", compute_type: str = "int8") -> None:
        if model not in MODELS:
            raise ValueError(f"modèle Whisper inconnu : {model} ({', '.join(MODELS)})")
        self.model_name, self.device, self.compute_type = model, device, compute_type
        self._model: Any = None
        self._lock = threading.Lock()

    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio: bytes, language: str | None = "fr") -> dict[str, Any]:
        if not audio:
            raise ValueError("enregistrement vide")
        if len(audio) > MAX_AUDIO:
            raise ValueError("enregistrement trop long (5 Mo au plus, environ 3 min en WAV)")
        if not available():
            raise RuntimeError("faster-whisper absent : scripts\\setup.ps1 -Voice")
        started = time.monotonic()
        with self._lock:
            segments, info = self._load().transcribe(io.BytesIO(audio), language=language or None,
                                                     vad_filter=True, beam_size=5)
            text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": info.language, "duration": round(float(info.duration), 2),
                "seconds": round(time.monotonic() - started, 2), "model": self.model_name}
