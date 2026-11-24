"""La voix comme outil des agents locaux (Hermes Agent, modèles du Hub) : parler sur le PC, choisir ou créer une voix.

Même forme que les autres outils (`TOOL_SPECS`, schémas « function calling ») : bus du Hub
(`module.voice.cmd.tool`) et serveur MCP stdio (`mcp_server.py`, nom `aethertwin_voice` chez Hermes).
Les outils ne lèvent jamais : erreur → `{"ok": False, "error": …}`.

Pas d'outil qui lit un fichier audio donné par chemin : la transcription passe par l'API du Hub
(`/v1/audio/transcriptions`) ou le micro de la page, jamais par un chemin choisi par un modèle.
"""
from __future__ import annotations

import io
import wave
from typing import Any

from modules.voice import effects
from modules.voice.service import VoiceService

EFFECTS_SCHEMA = {"type": "object", "description": "Effets (absents = neutres) : pitch (demi-tons, -12…12), bass et "
                  "treble (dB, -15…15), robot, radio, echo, reverb, tremolo (0…1), gain (dB, -24…12).",
                  "properties": {k: {"type": "number"} for k in effects.LIMITS}}

TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "voice_speak",
        "description": "Dit un texte à voix haute sur les haut-parleurs du PC, avec un profil de voix d'AetherTwin "
                       "(par défaut celui des réponses). Rend tout de suite ; la lecture continue en fond.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string",
                     "description": "Texte à dire (4 000 caractères au plus ; Markdown ignoré)."},
            "profile": {"type": "string", "description": "Id d'un profil de synthèse (voice_profiles)."},
            "speed": {"type": "number", "description": "Vitesse, 0,5 à 2 (celle du profil sinon)."},
            "effects": EFFECTS_SCHEMA},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "voice_stop",
        "description": "Arrête la voix en cours de lecture sur le PC.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "voice_profiles",
        "description": "Profils de voix (synthèse pour les réponses, micro pour le modulateur), voix installées et "
                       "profils choisis par défaut.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "voice_set_default",
        "description": "Choisit le profil de synthèse qui lit les réponses du Hub et des outils.",
        "parameters": {"type": "object", "properties": {"profile": {"type": "string"}}, "required": ["profile"]}}},
    {"type": "function", "function": {
        "name": "voice_save_profile",
        "description": "Crée ou modifie un profil de voix personnel. Synthèse : engine (piper ou sapi), voice (id "
                       "d'une voix installée), speaker (voix multiples), speed. Micro : effets seulement.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "Minuscules, chiffres, « _ », « - »."},
            "label": {"type": "string"}, "kind": {"type": "string", "enum": ["synthese", "micro"]},
            "engine": {"type": "string", "enum": ["piper", "sapi"]}, "voice": {"type": "string"},
            "speaker": {"type": "integer"}, "speed": {"type": "number"}, "effects": EFFECTS_SCHEMA},
            "required": ["id"]}}},
]
TOOL_NAMES = {spec["function"]["name"] for spec in TOOL_SPECS}


def duration(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return round(w.getnframes() / w.getframerate(), 2)


def call_tool(service: VoiceService, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Exécute un outil. Ne lève jamais : toute erreur devient `{"ok": False, "error": …}`."""
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if name not in TOOL_NAMES:
            raise ValueError(f"outil inconnu : {name!r} (outils : {', '.join(sorted(TOOL_NAMES))})")
        if name == "voice_speak":
            spoken = service.synthesize(str(args.get("text", "")), args.get("profile") or None,
                                        args.get("speed"), args.get("effects"))
            service.play(spoken["wav"])
            result: dict[str, Any] = {"ok": True, "profile": spoken["profile"], "engine": spoken["engine"],
                                      "seconds_of_audio": duration(spoken["wav"])}
            if "note" in spoken:
                result["note"] = spoken["note"]
        elif name == "voice_stop":
            result = {"ok": True, "was_playing": service.stop()}
        elif name == "voice_profiles":
            state = service.profiles.all()
            result = {"ok": True, **state, "voices": [{k: v[k] for k in ("engine", "id", "language", "speakers")}
                                                      for v in service.voices()]}
        elif name == "voice_set_default":
            state = service.profiles.settings({"default": str(args.get("profile", ""))})
            result = {"ok": True, "default": state["default"]}
        else:
            result = {"ok": True, "profile": service.profiles.save(args)}
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        result = {"ok": False, "error": str(exc) or type(exc).__name__}
    return result
