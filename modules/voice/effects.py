"""Effets de voix appliqués à un enregistrement (NumPy seul) : mêmes réglages que le modulateur en direct de la page.

    apply(samples, rate, {"pitch": 4, "robot": 0.5, "echo": 0.3})

Réglages (absents = neutres) :
    pitch     demi-tons, -12 … +12 (hauteur sans changer la durée)
    bass      dB, -15 … +15 (graves, sous 250 Hz)     treble   dB, -15 … +15 (aigus, au-dessus de 3 kHz)
    robot     0 … 1 (modulation en anneau à 70 Hz)     radio    0 … 1 (bande 300–3 400 Hz, saturation douce)
    echo      0 … 1 (retard 260 ms, réinjecté)         reverb   0 … 1 (salle)
    tremolo   0 … 1 (5 Hz)                              gain     dB, -24 … +12
"""
from __future__ import annotations

import io
import wave
from typing import Any

import numpy as np

LIMITS = {"pitch": (-12.0, 12.0), "bass": (-15.0, 15.0), "treble": (-15.0, 15.0), "robot": (0.0, 1.0),
          "radio": (0.0, 1.0), "echo": (0.0, 1.0), "reverb": (0.0, 1.0), "tremolo": (0.0, 1.0),
          "gain": (-24.0, 12.0)}
NEUTRAL = {key: 0.0 for key in LIMITS}


def clean(settings: Any) -> dict[str, float]:
    """Réglages bornés ; les clés inconnues sont ignorées."""
    out = dict(NEUTRAL)
    if isinstance(settings, dict):
        for key, (low, high) in LIMITS.items():
            try:
                out[key] = max(low, min(high, float(settings.get(key, 0.0))))
            except (TypeError, ValueError):
                raise ValueError(f"réglage « {key} » : nombre attendu") from None
    return out


# ---------- WAV ----------
def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """WAV PCM 16 bits (mono ou stéréo) → échantillons float32 mono dans [-1, 1], fréquence."""
    with wave.open(io.BytesIO(data)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("WAV 16 bits attendu")
        rate, channels = w.getframerate(), w.getnchannels()
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        raw = raw.reshape(-1, channels).mean(axis=1)
    return raw, rate


def write_wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return buffer.getvalue()


# ---------- briques ----------
def resample(x: np.ndarray, factor: float) -> np.ndarray:
    """Lecture `factor` fois plus rapide (interpolation linéaire) : plus court et plus aigu si factor > 1."""
    if len(x) < 2 or abs(factor - 1.0) < 1e-6:
        return x
    positions = np.arange(0, len(x) - 1, factor)
    return np.interp(positions, np.arange(len(x)), x).astype(np.float32)


def stretch(x: np.ndarray, factor: float, rate: int) -> np.ndarray:
    """Durée multipliée par `factor` sans changer la hauteur (recouvrement-addition, fenêtres de Hann de 40 ms)."""
    if len(x) < 2 or abs(factor - 1.0) < 1e-6:
        return x
    size = max(64, int(rate * 0.04))
    hop_out = size // 4
    hop_in = hop_out / factor
    window = np.hanning(size).astype(np.float32)
    count = max(1, int((len(x) - size) / hop_in) + 1) if len(x) > size else 1
    out = np.zeros(count * hop_out + size, dtype=np.float32)
    norm = np.zeros_like(out)
    padded = np.concatenate([x, np.zeros(size, dtype=np.float32)])
    for i in range(count):
        start = int(i * hop_in)
        out[i * hop_out:i * hop_out + size] += padded[start:start + size] * window
        norm[i * hop_out:i * hop_out + size] += window
    return out / np.maximum(norm, 1e-3)


def pitch_shift(x: np.ndarray, semitones: float, rate: int) -> np.ndarray:
    if abs(semitones) < 0.01:
        return x
    factor = 2 ** (semitones / 12)
    return resample(stretch(x, factor, rate), factor)


def shelf_eq(x: np.ndarray, rate: int, bass_db: float, treble_db: float, band: tuple[float, float] | None = None
             ) -> np.ndarray:
    """Égaliseur dans le domaine des fréquences (traitement hors temps réel) ; `band` = passe-bande."""
    if not bass_db and not treble_db and band is None:
        return x
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / rate)
    gain = np.ones_like(freqs)
    if bass_db:
        gain *= 1 + (10 ** (bass_db / 20) - 1) / (1 + (freqs / 250.0) ** 2)
    if treble_db:
        gain *= 1 + (10 ** (treble_db / 20) - 1) / (1 + (3000.0 / np.maximum(freqs, 1.0)) ** 2)
    if band is not None:
        low, high = band
        gain *= 1 / np.sqrt(1 + (low / np.maximum(freqs, 1.0)) ** 4) / np.sqrt(1 + (freqs / high) ** 4)
    return np.fft.irfft(spectrum * gain, n=len(x)).astype(np.float32)


def delay_line(x: np.ndarray, rate: int, seconds: float, feedback: float, mix: float, tail: float = 1.0
               ) -> np.ndarray:
    d = max(1, int(rate * seconds))
    out = np.concatenate([x, np.zeros(int(rate * tail), dtype=np.float32)])
    wet = np.zeros_like(out)
    for k in range(1, 12):  # répétitions de plus en plus faibles
        g = feedback ** (k - 1)
        if g < 0.02 or k * d >= len(out):
            break
        wet[k * d:] += g * out[:len(out) - k * d]
    return out + mix * wet


def reverb(x: np.ndarray, rate: int, amount: float) -> np.ndarray:
    out = np.concatenate([x, np.zeros(int(rate * 1.2), dtype=np.float32)])
    wet = np.zeros_like(out)
    for ms, g in ((29.7, 0.77), (37.1, 0.74), (41.1, 0.71), (43.7, 0.68)):  # peignes en parallèle
        d = int(rate * ms / 1000)
        comb = out.copy()
        for start in range(d, len(out), d):
            end = min(len(out), start + d)
            comb[start:end] += g * comb[start - d:end - d]
        wet += comb
    wet /= np.max(np.abs(wet)) or 1.0
    return out + amount * 0.6 * wet


# ---------- chaîne ----------
def apply(x: np.ndarray, rate: int, settings: Any) -> np.ndarray:
    s = clean(settings)
    x = np.asarray(x, dtype=np.float32)
    if s["pitch"]:
        x = pitch_shift(x, s["pitch"], rate)
    if s["bass"] or s["treble"]:
        x = shelf_eq(x, rate, s["bass"], s["treble"])
    t = np.arange(len(x), dtype=np.float32) / rate
    if s["robot"]:
        x = (1 - s["robot"]) * x + s["robot"] * x * np.sin(2 * np.pi * 70 * t) * 1.6
    if s["radio"]:
        band = shelf_eq(x, rate, 0, 0, (300.0, 3400.0))
        drive = 1 + 6 * s["radio"]
        x = (1 - s["radio"]) * x + s["radio"] * np.tanh(band * drive) / np.tanh(drive)
    if s["tremolo"]:
        x = x * (1 - s["tremolo"] * 0.5 * (1 + np.sin(2 * np.pi * 5 * t)))
    if s["echo"]:
        x = delay_line(x, rate, 0.26, 0.35 + 0.3 * s["echo"], s["echo"] * 0.6, tail=0.8 + s["echo"])
    if s["reverb"]:
        x = reverb(x, rate, s["reverb"])
    if s["gain"]:
        x = x * 10 ** (s["gain"] / 20)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0.99:  # limiteur : jamais de saturation numérique
        x = x * (0.99 / peak)
    return x.astype(np.float32)


def normalize(x: np.ndarray, target_db: float = -23.0, peak: float = 0.7) -> np.ndarray:
    """Même volume perçu pour toutes les voix (moyenne quadratique visée), crêtes bornées : jamais assourdissant."""
    x = np.asarray(x, dtype=np.float32)
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    if rms < 1e-5:
        return x
    x = x * (10 ** (target_db / 20) / rms)
    top = float(np.max(np.abs(x)))
    return x * (peak / top) if top > peak else x


def apply_wav(data: bytes, settings: Any, level: bool = False) -> bytes:
    """Effets (et, avec `level`, volume égalisé) sur un WAV ; neutre sans égalisation = WAV rendu tel quel."""
    s = clean(settings)
    if s == NEUTRAL and not level:
        return data
    samples, rate = read_wav(data)
    out = apply(samples, rate, s) if s != NEUTRAL else samples
    return write_wav(normalize(out) if level else out, rate)
