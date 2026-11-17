"""
Module vocal : micro (appuyer pour parler ou activation vocale), reconnaissance (STT) et synthèse (TTS).

- Capture : sounddevice (pip install sounddevice) en 16 kHz mono ; sans lui, le reste de l'appli fonctionne.
- Appuyer pour parler : la touche est lue directement (GetAsyncKeyState), même quand WoW a le focus.
- Activation vocale : détection d'énergie (seuil réglable) avec un court pré-enregistrement.
- STT : serveur compatible OpenAI (/v1/audio/transcriptions : Open WebUI, faster-whisper-server...), programme local
  (whisper.cpp...) ou la bibliothèque faster-whisper.
- TTS : voix de Windows (SAPI, sans installation), Piper (programme + modèle), ou désactivé.
"""
import array
import io
import json
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections import deque

from hotkeys import IS_WINDOWS, parse_hotkey
from llm import _split_args

RATE = 16000
BLOCK = 800                      # 50 ms
THRESHOLDS = {1: 1500, 2: 1000, 3: 600, 4: 400, 5: 250}     # niveau RMS (16 bits) selon la sensibilité 1..5
MOUSE_KEYS = {"mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06}
_MOD_VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}
MIN_SPEECH_SECONDS = 0.4
MAX_SPEECH_BLOCKS = 400          # 20 s
FASTER_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")     # tailles proposées dans les Paramètres


def faster_whisper_model(choice, legacy=""):
    """Nom du modèle faster-whisper à charger.

    `choice` = réglage voice.stt.fw_model. `legacy` = ancien champ partagé avec l'API (voice.stt.model) : on ne le
    reprend que s'il désigne un dossier de modèle ou un dépôt (« org/modele ») — jamais un nom d'API comme
    « whisper-1 », que faster-whisper refuse.
    """
    choice = str(choice or "").strip()
    if choice:
        return choice
    legacy = str(legacy or "").strip()
    if legacy and (os.path.isdir(legacy) or "/" in legacy):
        return legacy
    return "small"


# ===========================================================================
#  Touches (appuyer pour parler)
# ===========================================================================
def ptt_keys(text):
    """'F8', 'Ctrl+Space', 'Mouse4' -> liste de codes de touches virtuelles qui doivent toutes être enfoncées."""
    codes = []
    for part in [p.strip().lower() for p in str(text or "").split("+") if p.strip()]:
        if part in MOUSE_KEYS:
            codes.append(MOUSE_KEYS[part])
        elif part in _MOD_VK:
            codes.append(_MOD_VK[part])
        else:
            parsed = parse_hotkey(part)
            if not parsed:
                return []
            codes.append(parsed[1])
    return codes


def default_key_state(vk):
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


# ===========================================================================
#  Audio
# ===========================================================================
def rms(block):
    samples = array.array("h")
    samples.frombytes(block[: len(block) - (len(block) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def wav_bytes(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buffer.getvalue()


def _multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for name, value in fields.items():
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    for name, (filename, content, ctype) in files.items():
        body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f'Content-Type: {ctype}\r\n\r\n').encode("utf-8"))
        body.write(content)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


# ===========================================================================
#  Reconnaissance vocale (STT)
# ===========================================================================
class Transcriber:
    def __init__(self, settings):
        self.settings = settings
        self._model = None
        self._model_name = None

    def _cfg(self, key):
        return self.settings.get(f"voice.stt.{key}", "")

    def is_configured(self):
        backend = self._cfg("backend")
        if backend == "api":
            return bool(self._cfg("endpoint"))
        if backend == "exe":
            return bool(self._cfg("exe"))
        return backend == "faster-whisper"

    def transcribe(self, wav):
        backend = self._cfg("backend")
        if backend == "api":
            return self._api(wav)
        if backend == "exe":
            return self._exe(wav)
        if backend == "faster-whisper":
            return self._faster(wav)
        raise RuntimeError("Reconnaissance vocale non configurée (Paramètres > Voix).")

    def _url(self):
        base = self._cfg("endpoint").strip().rstrip("/")
        if base.endswith("/audio/transcriptions"):
            return base
        if base.endswith("/v1") or base.endswith("/api/v1"):
            return base + "/audio/transcriptions"
        return base + "/v1/audio/transcriptions"

    def _api(self, wav):
        if not self._cfg("endpoint"):
            raise RuntimeError("Endpoint de reconnaissance vocale non défini.")
        fields = {"model": self._cfg("model") or "whisper-1", "response_format": "json"}
        if self._cfg("language"):
            fields["language"] = self._cfg("language")
        body, content_type = _multipart(fields, {"file": ("audio.wav", wav, "audio/wav")})
        headers = {"Content-Type": content_type, "User-Agent": "WoWAssistant/1.7"}
        if self._cfg("api_key"):
            headers["Authorization"] = "Bearer " + self._cfg("api_key")
        request = urllib.request.Request(self._url(), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Erreur HTTP {e.code} : {e.read().decode('utf-8', 'ignore')[:200]}")
        return str(data.get("text", "")).strip()

    def _exe(self, wav):
        exe = self._cfg("exe").strip().strip('"')
        if not exe:
            raise RuntimeError("Programme de reconnaissance non défini.")
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav)
            tokens = [t.strip('"') for t in _split_args(self._cfg("args") or "{audio}")]
            args = [exe] + [t.replace("{audio}", path) for t in tokens]
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0 and not result.stdout.strip():
                raise RuntimeError((result.stderr or f"Code de sortie {result.returncode}").strip()[:300])
            lines = [re.sub(r"^\s*\[[^\]]*\]\s*", "", line).strip() for line in result.stdout.splitlines()]
            return " ".join(line for line in lines if line)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _faster(self, wav):
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            # le « pip » nu peut viser un autre Python que celui qui fait tourner l'appli : on donne la commande exacte
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            raise RuntimeError(f"faster-whisper absent de ce Python ({version}) : py -{version} -m pip install faster-whisper")
        name = faster_whisper_model(self._cfg("fw_model"), self._cfg("model"))
        if self._model is None or self._model_name != name:
            self._model, self._model_name = WhisperModel(name, compute_type="int8"), name
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav)
            segments, _ = self._model.transcribe(path, language=self._cfg("language") or None)
            return " ".join(seg.text.strip() for seg in segments).strip()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


# ===========================================================================
#  Synthèse vocale (TTS)
# ===========================================================================
def clean_for_speech(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_`#>|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class Speaker:
    def __init__(self, settings):
        self.settings = settings
        self._proc = None
        self.busy = False
        self.error = ""

    def _cfg(self, key, default=""):
        return self.settings.get(f"voice.tts.{key}", default)

    def speak(self, text):
        backend = self._cfg("backend", "sapi")
        text = clean_for_speech(text)[: int(self._cfg("max_chars", 700))]
        if backend == "off" or not text:
            return
        self.stop()
        threading.Thread(target=self._run, args=(backend, text), daemon=True).start()

    def stop(self):
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        if IS_WINDOWS:
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def _run(self, backend, text):
        self.busy, self.error = True, ""
        try:
            if backend == "piper":
                self._piper(text)
            else:
                self._sapi(text)
        except Exception as e:
            self.error = str(e)[:200]
        finally:
            self.busy = False

    def _sapi(self, text):
        if not IS_WINDOWS:
            raise RuntimeError("La voix Windows (SAPI) n'est disponible que sous Windows.")
        rate = int(self._cfg("rate", 0))
        script = ("[Console]::InputEncoding = [System.Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "
                  f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = {rate}; "
                  "$s.Speak([Console]::In.ReadToEnd())")
        self._proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._proc.communicate(text.encode("utf-8"))

    def _piper(self, text):
        exe, model = self._cfg("piper_exe", "piper").strip().strip('"'), self._cfg("piper_model").strip().strip('"')
        if not model:
            raise RuntimeError("Modèle Piper non défini (Paramètres > Voix).")
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            self._proc = subprocess.Popen([exe, "--model", model, "--output_file", path], stdin=subprocess.PIPE,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._proc.communicate(text.encode("utf-8"))
            if os.path.getsize(path) > 44:
                self._play_wav(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _play_wav(self, path):
        if IS_WINDOWS:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
            return
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        channel = pygame.mixer.Sound(path).play()
        while channel and channel.get_busy():
            time.sleep(0.05)


# ===========================================================================
#  Gestionnaire
# ===========================================================================
class VoiceManager:
    def __init__(self, settings, key_state=None, transcriber=None, speaker=None):
        self.settings = settings
        self.key_state = key_state or default_key_state
        self.transcriber = transcriber or Transcriber(settings)
        self.speaker = speaker or Speaker(settings)
        self.events = queue.Queue()
        self.level = 0.0
        self.peak = 0.0
        self.notice = ""
        self.error = ""
        self._stream = None
        self._oneshot = False
        self._oneshot_at = 0.0
        self._transcribing = 0
        self._reset_capture()

    # ------------------------------------------------------------------ état
    @property
    def enabled(self):
        return bool(self.settings.get("voice.enabled", False))

    @property
    def mode(self):
        return self.settings.get("voice.mode", "ptt")

    @property
    def status(self):
        if self.error:
            return "error"
        if self.speaker.busy:
            return "speaking"
        if self._transcribing:
            return "transcribing"
        if self._recording:
            return "listening"
        if self._stream is not None and (self.enabled or self._oneshot):
            return "idle"
        return "off"

    STATUS_LABELS = {"off": "Micro désactivé", "idle": "Micro actif", "listening": "J'écoute…",
                     "transcribing": "Transcription…", "speaking": "Hermes parle…", "error": "Erreur micro"}

    def _reset_capture(self):
        self._preroll = deque(maxlen=6)
        self._buf = []
        self._recording = False
        self._speech = 0
        self._silence = 0

    # ------------------------------------------------------------------ flux audio
    # ------------------------------------------------------------------ périphériques
    @staticmethod
    def list_input_devices():
        """[(nom, par_défaut)] des micros disponibles (sans doublons). Lève ImportError/OSError si sounddevice manque."""
        import sounddevice as sd
        try:
            default_in = sd.default.device[0]
        except Exception:
            default_in = -1
        out, seen = [], set()
        for index, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) < 1:
                continue
            name = str(dev["name"]).strip()
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append((name, index == default_in))
        return out

    def _resolve_device(self, sd):
        """Index du micro choisi dans les réglages (ou None = micro par défaut de Windows)."""
        wanted = str(self.settings.get("voice.device", "") or "").strip().lower()
        devices = sd.query_devices()
        if wanted:
            for index, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0 and str(dev["name"]).strip().lower() == wanted:
                    return index
            for index, dev in enumerate(devices):              # nom tronqué par certains pilotes
                if dev.get("max_input_channels", 0) > 0 and wanted[:24] in str(dev["name"]).lower():
                    return index
            self.notice = f"Micro « {wanted} » introuvable : micro par défaut utilisé"
        try:
            if sd.default.device[0] is not None and sd.default.device[0] >= 0:
                return None
        except Exception:
            pass
        for index, dev in enumerate(devices):                  # pas de micro par défaut : on prend le premier
            if dev.get("max_input_channels", 0) > 0:
                return index
        return None

    def start(self):
        """Ouvre le micro. Retourne False (avec self.error) si impossible."""
        if self._stream is not None:
            return True
        try:
            import sounddevice as sd
        except ImportError:
            self.error = ("Module sounddevice absent de CE Python. Dans un terminal : "
                          f"\"{sys.executable}\" -m pip install sounddevice")
            return False
        except OSError as e:
            self.error = "PortAudio indisponible : " + str(e)[:100]
            return False
        try:
            self.notice = ""
            device = self._resolve_device(sd)
            self._stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK, device=device,
                                             callback=lambda data, frames, t, status: self.process_block(bytes(data), time.time()))
            self._stream.start()
            self.error = ""
            return True
        except Exception as e:
            self._stream = None
            self.error = f"Micro indisponible : {e}"[:160]
            return False

    def stop(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.error = ""          # une erreur d'ouverture ne reste pas affichée quand le micro est désactivé
        self.level = 0.0
        self._reset_capture()

    def restart(self):
        """Referme puis rouvre le micro (après un changement de périphérique)."""
        self.stop()
        if self.enabled or self._oneshot:
            self.start()

    def apply_settings(self):
        """À appeler quand les réglages changent : ouvre ou ferme le micro."""
        if self.enabled or self._oneshot:
            self.start()
        else:
            self.stop()

    # ------------------------------------------------------------------ cœur : détection de parole
    def _ptt_pressed(self):
        codes = ptt_keys(self.settings.get("voice.ptt_key", "F8"))
        return bool(codes) and all(self.key_state(vk) for vk in codes)

    def process_block(self, block, now=None):
        level = rms(block)
        self.level = min(1.0, level / 4000.0)
        self.peak = max(self.peak, self.level)
        if not (self.enabled or self._oneshot):
            return
        threshold = THRESHOLDS.get(int(self.settings.get("voice.sensitivity", 3)), 600)
        use_ptt = (self.mode == "ptt") and not self._oneshot
        if use_ptt:
            pressed = self._ptt_pressed()
            if pressed and not self._recording:
                self._begin()
            if self._recording:
                self._buf.append(block)
                if not pressed:
                    self._finish()
            else:
                self._preroll.append(block)
            return
        # activation vocale
        if not self._recording:
            self._preroll.append(block)
            self._speech = self._speech + 1 if level > threshold else 0
            if self._speech >= 3:
                self._begin()
        else:
            self._buf.append(block)
            self._silence = self._silence + 1 if level < threshold * 0.7 else 0
            if self._silence >= 16 or len(self._buf) > MAX_SPEECH_BLOCKS:
                self._finish()

    def _begin(self):
        self._recording = True
        self._pre_len = len(self._preroll)
        self._buf = list(self._preroll)
        self._preroll.clear()
        self._silence = 0

    def _finish(self):
        pcm = b"".join(self._buf)
        spoken_blocks = len(self._buf) - getattr(self, "_pre_len", 0)      # sans le pré-enregistrement
        oneshot = self._oneshot
        self._reset_capture()
        if spoken_blocks * BLOCK / RATE < MIN_SPEECH_SECONDS or len(pcm) / 2 / RATE < MIN_SPEECH_SECONDS:
            return
        if oneshot:
            self._oneshot = False
        self._transcribing += 1
        threading.Thread(target=self._transcribe, args=(pcm, oneshot), daemon=True).start()

    def _transcribe(self, pcm, oneshot):
        try:
            text = self.transcriber.transcribe(wav_bytes(pcm)).strip()
            self.events.put(("oneshot" if oneshot else "text", text) if text else ("error", "Aucune parole reconnue"))
        except Exception as e:
            self.events.put(("error", str(e)[:200] or e.__class__.__name__))
        finally:
            self._transcribing -= 1
            if oneshot and not self.enabled:
                self.stop()

    # ------------------------------------------------------------------ actions
    def record_once(self):
        """Enregistre une seule phrase (arrêt au silence) et la renvoie sous la forme d'un événement 'oneshot'."""
        self._oneshot = True
        self._oneshot_at = time.time()
        self.peak = 0.0
        self._reset_capture()
        if not self.start():
            self._oneshot = False
            return False
        return True

    def speak(self, text):
        self.speaker.speak(text)

    def stop_speaking(self):
        self.speaker.stop()

    ONESHOT_TIMEOUT = 8.0

    def poll(self):
        out = []
        if self._oneshot and not self._recording and not self._transcribing and \
                time.time() - self._oneshot_at > self.ONESHOT_TIMEOUT:
            self._oneshot = False
            peak = int(self.peak * 100)
            if not self.enabled:
                self.stop()
            hint = ("le micro ne capte rien : choisis un autre périphérique" if peak < 3
                    else "parle plus fort ou augmente la sensibilité")
            self.events.put(("error", f"Aucune voix détectée (niveau max {peak} %) : {hint}"))
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out
