"""Module du Hub : voix locale (synthèse Piper / Windows, écoute Whisper, profils, effets, VB-Cable, MCP).

Commandes (`POST /modules/voice/command/<commande>`, ou bus `module.voice.cmd.<commande>`) :

    status          {}                                     moteurs, voix installées, réglages
    voices          {}                                     voix Piper et Windows installées
    profiles        {}  ·  profile_save {"profile"}  ·  profile_delete {"id"}
    settings        {"default"?, "mic"?, "speak_replies"?} profils par défaut, lecture des réponses
    speak           {"text", "profile"?, "profile_data"?, "speed"?, "effects"?, "play"?, "file"?}
                    WAV en base64 (ou fichier d'échange si "file") ; "play" : lu sur les haut-parleurs du PC
    silence         {}                                     coupe la lecture sur le PC (« stop » arrête le module)
    transcribe      {"audio": "<base64>" | "file": "<échange>", "language"?}
    effects         {"audio": "<base64 WAV>", "effects"}   applique des effets à un enregistrement
    install         {"voices"?}                            Piper et voix françaises (sources officielles)
    vbcable         {}                                     VB-Cable installé ? (+ lien officiel)
    hermes {}  ·  hermes_register {}                       serveur MCP `aethertwin_voice` chez Hermes Agent

Conversion de voix (kNN-VC, `convert.py`) — seulement des voix enregistrées dans le studio avec consentement :

    vc_status   {}                                         poids, voix de la banque, mémoire
    vc_install  {}                                         poids depuis les publications de kNN-VC (1,3 Go)
    vc_create   {"id", "label", "name", "attest": true}    nouvelle voix (attend sa phrase de consentement)
    vc_prompt   {"voice"}                                  prochain texte à lire (d'abord le consentement)
    vc_voice    {"voice"}                                  détail d'une voix (prises)
    vc_take     {"voice", "prompt", "file"|"audio"}        prise lue en direct, vérifiée par Whisper
    vc_take_delete {"voice", "take"}  ·  vc_delete {"voice"}  ·  vc_unload {}
    vc_convert  {"voice", "file"|"audio", "effects"?}      enregistrement → même phrase avec ce timbre
    tools  {}  ·  tool {"name", "arguments"}               outils des agents (`agent.py`)

Configuration (section `voice` de `config/local.yaml`), facultative :

    data_dir: "data/voice"
    whisper_model: "small"        # tiny, base, small, medium, large-v3, large-v3-turbo
    whisper_device: "cpu"         # ou "cuda" (prend de la VRAM)
    vc_device: "cpu"              # conversion de voix ; "cuda" plus rapide (≈ 1,5 Go de VRAM)
"""
from __future__ import annotations

import base64
import binascii
import time
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.voice import agent, convert, effects, stt
from modules.voice.service import DATA_DIR, REPO_ROOT, VoiceService, vbcable_status

MCP_NAME = "aethertwin_voice"
MCP_SCRIPT = REPO_ROOT / "modules" / "voice" / "mcp_server.py"
INLINE_MAX = 3_000_000  # au-delà, le WAV passe par un fichier d'échange (le bus porte 8 Mo au plus)


def b64(data: Any, limit: int = stt.MAX_AUDIO) -> bytes:
    text = str(data or "").split(",")[-1]
    if len(text) > limit * 4 // 3 + 4:
        raise ValueError("audio trop gros")
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("audio illisible (base64 attendu)") from None


class VoiceModule(ModuleBase):
    def start(self) -> None:
        model = str(self.config.get("whisper_model") or "small")
        device = str(self.config.get("whisper_device") or "cpu")
        self.service = VoiceService(REPO_ROOT / str(self.config.get("data_dir") or DATA_DIR), model, device,
                                    str(self.config.get("vc_device") or "cpu"))

    def stop(self) -> None:
        try:
            self.service.stop()
        except (OSError, RuntimeError):
            pass

    def health(self) -> Health:
        s = self.service
        piper = s.piper.exe.is_file() and any((s.piper.folder / "voices").glob("*.onnx"))
        if not piper and not s.sapi.available():
            return Health(ok=True, degraded=True, detail="aucune voix : Voix → Installer")
        detail = "Piper" if piper else "voix de Windows seulement (Piper à installer)"
        return Health(ok=True, degraded=not stt.available(),
                      detail=detail + ("" if stt.available() else ", écoute indisponible (faster-whisper absent)"))

    def hermes(self, register: bool = False) -> dict[str, Any]:
        """État du branchement MCP chez Hermes Agent ; `register` le déclare (config.yaml sauvegardée avant)."""
        from modules.dev_launcher import hermes_link
        from modules.genesis_lab.sources import hermes_exe

        exe = hermes_exe()
        result: dict[str, Any] = {}
        if register:
            result = hermes_link.register_server(exe, MCP_NAME, ["-I", str(MCP_SCRIPT)])
        config = hermes_link.hermes_home() / "config.yaml"
        text = config.read_text(encoding="utf-8", errors="replace") if config.is_file() else ""
        return {**result, "installe": bool(exe), "branche": hermes_link.registered(text, MCP_NAME), "nom": MCP_NAME}

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        try:
            reply = {"ok": True, "result": self.run(command, payload)}
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            reply = {"ok": False, "error": str(exc) or type(exc).__name__}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def _audio(self, payload: dict[str, Any]) -> bytes:
        if payload.get("file"):
            path = self.service.tmp_path(str(payload["file"]))
            try:
                return path.read_bytes()
            finally:
                path.unlink(missing_ok=True)
        return b64(payload.get("audio"))

    def _wav_reply(self, wav: bytes, payload: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        out = {**extra, "duration": agent.duration(wav)}
        if payload.get("file") or len(wav) > INLINE_MAX:
            out["file"] = self.service.tmp_write(wav)
        else:
            out["audio"] = base64.b64encode(wav).decode("ascii")
        return out

    def conversion(self, command: str, payload: dict[str, Any]) -> Any:
        s = self.service
        bank, conv = s.bank, s.converter
        vid = str(payload.get("voice", ""))
        if command == "vc_status":
            return {**conv.status(), "voices": bank.all(), "prompts": len(convert.PROMPTS),
                    "ready_seconds": convert.READY_SECONDS}
        if command == "vc_install":
            return convert.install(conv.weights)
        if command == "vc_create":
            return bank.create(str(payload.get("id", "")), str(payload.get("label", "")), str(payload.get("name", "")),
                               payload.get("attest") is True)
        if command == "vc_prompt":
            return bank.next_prompt(vid)
        if command == "vc_voice":
            return bank.get(vid)
        if command == "vc_take":
            return bank.add_take(vid, self._audio(payload), int(payload.get("prompt", -1)),
                                 lambda wav: s.transcribe(wav)["text"])
        if command == "vc_take_delete":
            return {"deleted": bank.delete_take(vid, int(payload.get("take", -1)))}
        if command == "vc_delete":
            return {"deleted": bank.delete(vid)}
        if command == "vc_unload":
            return {"unloaded": conv.unload()}
        if command == "vc_convert":
            started = time.monotonic()
            wav = conv.convert_wav(self._audio(payload), vid)
            if isinstance(payload.get("effects"), dict):
                wav = effects.apply_wav(wav, payload["effects"])
            return self._wav_reply(wav, payload, {"voice": vid, "seconds": round(time.monotonic() - started, 2)})
        raise ValueError(f"commande inconnue : {command!r}")

    def run(self, command: str, payload: dict[str, Any]) -> Any:
        """Exécute une commande (aussi appelée directement par les tests)."""
        s = self.service
        if command == "status":
            return s.status()
        if command == "voices":
            return s.voices()
        if command == "profiles":
            return s.profiles.all()
        if command == "profile_save":
            return s.profiles.save(payload.get("profile"))
        if command == "profile_delete":
            return {"deleted": s.profiles.delete(str(payload.get("id", "")))}
        if command == "settings":
            return s.profiles.settings({k: payload[k] for k in ("default", "mic", "speak_replies") if k in payload})
        if command == "speak":
            spoken = s.synthesize(str(payload.get("text", "")), payload.get("profile") or None,
                                  payload.get("speed"), payload.get("effects"), payload.get("profile_data"))
            wav = spoken.pop("wav")
            if payload.get("play"):
                s.play(wav)
            spoken["duration"] = agent.duration(wav)
            if payload.get("file") or len(wav) > INLINE_MAX:
                spoken["file"] = s.tmp_write(wav)
            else:
                spoken["audio"] = base64.b64encode(wav).decode("ascii")
            return spoken
        if command == "silence":
            return {"was_playing": s.stop()}
        if command == "transcribe":
            return s.transcribe(self._audio(payload), payload.get("language", "fr") or None)
        if command == "effects":
            wav = effects.apply_wav(b64(payload.get("audio")), payload.get("effects"))
            return {"audio": base64.b64encode(wav).decode("ascii")}
        if command == "install":
            voices = payload.get("voices")
            return s.install(list(voices) if isinstance(voices, list) else None)
        if command == "vbcable":
            return vbcable_status()
        if command.startswith("vc_"):
            return self.conversion(command, payload)
        if command in ("hermes", "hermes_register"):
            return self.hermes(register=command == "hermes_register")
        if command == "tools":
            return agent.TOOL_SPECS
        if command == "tool":
            return agent.call_tool(s, str(payload.get("name", "")), payload.get("arguments"))
        raise ValueError(f"commande inconnue : {command!r}")
