"""Profils de voix : un moteur, une voix (et un locuteur pour les voix multiples), une vitesse et des effets.

Deux sortes :
- `synthese` : voix des réponses (Hub, WoW Assistant, Hermes…) ;
- `micro` : réglages du modulateur vocal en direct (ta voix), appliqués dans la page par Web Audio.

Gardés dans `data/voice/profiles.json` avec les choix par défaut (`default` pour les réponses, `mic` pour le micro).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from modules.voice import effects

PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
KINDS = ("synthese", "micro")
MAX_PROFILES = 64

BUILTIN: list[dict[str, Any]] = [
    {"id": "aether", "label": "Æther (claire)", "kind": "synthese", "engine": "piper", "voice": "fr_FR-siwis-medium",
     "speaker": 0, "speed": 1.0, "effects": {}},
    {"id": "narrateur", "label": "Narrateur", "kind": "synthese", "engine": "piper", "voice": "fr_FR-upmc-medium",
     "speaker": 1, "speed": 0.95, "effects": {"bass": 3, "reverb": 0.15}},
    {"id": "fuma", "label": "Fuma (chat espiègle)", "kind": "synthese", "engine": "piper",
     "voice": "fr_FR-siwis-medium", "speaker": 0, "speed": 1.1, "effects": {"pitch": 4}},
    {"id": "inoue", "label": "Inoue (calme)", "kind": "synthese", "engine": "piper", "voice": "fr_FR-gilles-low",
     "speaker": 0, "speed": 0.95, "effects": {"pitch": -1, "bass": 4}},
    {"id": "robot", "label": "Robot", "kind": "synthese", "engine": "piper", "voice": "fr_FR-gilles-low",
     "speaker": 0, "speed": 1.0, "effects": {"robot": 0.7, "echo": 0.15}},
    {"id": "radio", "label": "Radio de bord", "kind": "synthese", "engine": "piper", "voice": "fr_FR-mls-medium",
     "speaker": 12, "speed": 1.05, "effects": {"radio": 0.8}},
    {"id": "windows", "label": "Voix de Windows", "kind": "synthese", "engine": "sapi", "voice": "", "speaker": 0,
     "speed": 1.0, "effects": {}},
    {"id": "ma_voix", "label": "Ma voix (naturelle)", "kind": "micro", "effects": {}},
    {"id": "ma_voix_grave", "label": "Ma voix, plus grave", "kind": "micro", "effects": {"pitch": -4, "bass": 3}},
    {"id": "ma_voix_robot", "label": "Ma voix en robot", "kind": "micro", "effects": {"robot": 0.8, "echo": 0.1}},
    {"id": "ma_voix_radio", "label": "Ma voix à la radio", "kind": "micro", "effects": {"radio": 0.9}},
]
BUILTIN_IDS = {p["id"] for p in BUILTIN}


def validate(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ValueError("profil attendu")
    pid = str(profile.get("id", "")).strip().lower()
    if not PROFILE_ID.match(pid):
        raise ValueError("identifiant de profil invalide (minuscules, chiffres, « _ », « - »)")
    kind = profile.get("kind", "synthese")
    if kind not in KINDS:
        raise ValueError("sorte de profil : synthese ou micro")
    out: dict[str, Any] = {"id": pid, "label": str(profile.get("label") or pid)[:60], "kind": kind,
                           "effects": {k: v for k, v in effects.clean(profile.get("effects")).items() if v}}
    if kind == "synthese":
        engine = profile.get("engine", "piper")
        if engine not in ("piper", "sapi"):
            raise ValueError("moteur : piper ou sapi")
        out.update(engine=engine, voice=str(profile.get("voice", ""))[:120],
                   speaker=max(0, min(500, int(profile.get("speaker", 0) or 0))),
                   speed=max(0.5, min(2.0, float(profile.get("speed", 1.0) or 1.0))))
    return out


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> dict[str, Any]:
        data = self._read()
        custom = {}
        for p in data.get("profiles", []):
            try:
                custom[p["id"]] = validate(p)
            except (ValueError, KeyError, TypeError):
                continue
        profiles = [custom.pop(p["id"], dict(p, builtin=True)) for p in BUILTIN] + list(custom.values())
        for p in profiles:  # profil intégré modifié : personnel (supprimable), l'original revient une fois supprimé
            if not p.setdefault("builtin", False) and p["id"] in BUILTIN_IDS:
                p["overrides"] = True
        default = data.get("default") if any(p["id"] == data.get("default") and p["kind"] == "synthese"
                                             for p in profiles) else "aether"
        mic = data.get("mic") if any(p["id"] == data.get("mic") and p["kind"] == "micro"
                                     for p in profiles) else "ma_voix"
        return {"profiles": profiles, "default": default, "mic": mic,
                "speak_replies": bool(data.get("speak_replies", False))}

    def get(self, pid: str | None) -> dict[str, Any]:
        state = self.all()
        pid = pid or state["default"]
        for p in state["profiles"]:
            if p["id"] == pid:
                return p
        raise ValueError(f"profil de voix inconnu : {pid}")

    def save(self, profile: Any) -> dict[str, Any]:
        p = validate(profile)
        data = self._read()
        others = [q for q in data.get("profiles", []) if isinstance(q, dict) and q.get("id") != p["id"]]
        if len(others) >= MAX_PROFILES:
            raise ValueError(f"{MAX_PROFILES} profils personnels au plus")
        data["profiles"] = others + [p]
        self._write(data)
        return p

    def delete(self, pid: str) -> bool:
        data = self._read()
        before = data.get("profiles", [])
        data["profiles"] = [q for q in before if isinstance(q, dict) and q.get("id") != pid]
        if len(data["profiles"]) == len(before):
            return False  # profil intégré (ou inconnu) : rien à supprimer
        self._write(data)
        return True

    def settings(self, values: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        state = self.all()
        ids = {p["id"]: p["kind"] for p in state["profiles"]}
        if "default" in values:
            if ids.get(values["default"]) != "synthese":
                raise ValueError("voix des réponses : profil de synthèse attendu")
            data["default"] = values["default"]
        if "mic" in values:
            if ids.get(values["mic"]) != "micro":
                raise ValueError("micro : profil « micro » attendu")
            data["mic"] = values["mic"]
        if "speak_replies" in values:
            data["speak_replies"] = bool(values["speak_replies"])
        self._write(data)
        return self.all()
