"""Adaptateur EXPÉRIMENTAL : état dérivé d'une capture d'écran par un modèle de vision local.

Pour les jeux qui n'écrivent ni fichier de sauvegarde lisible ni journal. Une capture d'écran est
envoyée au modèle de vision local (Ollama) avec la liste des champs à lire ; le modèle répond en JSON.

Limites assumées :
- lent (plusieurs secondes par lecture) et consommateur de VRAM : à espacer, jamais à chaque image ;
- un modèle de vision peut se tromper ou inventer une valeur : les champs sont validés par type,
  une valeur illisible reste absente, et l'état porte toujours `"experimental": true` ;
- aucune requête ne sort de la machine : l'hôte Ollama est local ou sur le réseau local.

La capture et l'appel au modèle sont injectables, ce qui permet de tester sans écran ni GPU.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from modules.gaming_hud.adapters.base import META_KEY, PRIVACY_OFF, check_mode
from modules.gaming_hud.adapters.privacy import MASK, PrivacyOptions, filter_state

DEFAULT_OLLAMA_HOST = "127.0.0.1:11434"
_CASTS = {"str": str, "int": lambda v: int(float(v)), "float": float, "bool": bool}


def grab_screen_png(max_edge: int = 1280) -> bytes:
    """Capture l'écran principal (Pillow) et le réduit. Lève `RuntimeError` si la capture est impossible."""
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("Pillow est requis pour la capture d'écran : pip install pillow") from exc
    try:
        image = ImageGrab.grab()
    except Exception as exc:  # noqa: BLE001 — pas d'écran (serveur, CI), session verrouillée…
        raise RuntimeError(f"capture d'écran impossible : {exc}") from exc
    image.thumbnail((max_edge, max_edge))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def ollama_vision(host: str, model: str, prompt: str, image_png: bytes, num_ctx: int = 4096,
                  keep_alive: str = "30s", timeout_s: float = 180.0) -> str:
    """Question + image au modèle de vision local, réponse au format JSON (API native d'Ollama)."""
    base = host if host.startswith(("http://", "https://")) else f"http://{host}"
    body = json.dumps({
        "model": model, "stream": False, "format": "json", "keep_alive": keep_alive,
        "options": {"num_ctx": num_ctx, "temperature": 0},
        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(image_png).decode("ascii")]}],
    }).encode("utf-8")
    request = urllib.request.Request(base.rstrip("/") + "/api/chat", data=body,  # noqa: S310 — hôte Ollama configuré
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        data = json.loads(response.read().decode("utf-8"))
    return str((data.get("message") or {}).get("content", ""))


def extract_json(text: str) -> dict[str, Any]:
    """Extrait l'objet JSON d'une réponse de modèle (tolère les balises de code et le texte autour)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        value = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


class ScreenOcrAdapter:
    """Lit des champs à l'écran avec un modèle de vision local."""

    experimental = True

    def __init__(self, config: dict[str, Any], options: PrivacyOptions | None = None,
                 capture: Callable[[], bytes] | None = None,
                 vision: Callable[[str, bytes], str] | None = None) -> None:
        fields = config.get("fields")
        if not isinstance(fields, list) or not fields or not all(isinstance(f, dict) and f.get("name") for f in fields):
            raise ValueError("`fields` doit être une liste non vide de {name, description, type}")
        for item in fields:
            if str(item.get("type", "str")) not in _CASTS:
                raise ValueError(f"champ « {item['name']} » : type inconnu (str, int, float, bool)")
        self.id = str(config.get("id", "screen_ocr"))
        self.game = str(config.get("game", "Jeu (capture d'écran)"))
        self.fields = [{"name": str(f["name"]), "description": str(f.get("description", "")),
                        "type": str(f.get("type", "str")), "private": bool(f.get("private", False))} for f in fields]
        self.model = str(config.get("model", "qwen2.5vl:7b"))
        self.host = str(config.get("ollama_host", DEFAULT_OLLAMA_HOST))
        self.min_interval_s = float(config.get("min_interval_s", 10.0))
        self.options = options or PrivacyOptions()
        self._capture = capture or grab_screen_png
        self._vision = vision or (lambda prompt, png: ollama_vision(self.host, self.model, prompt, png))
        self._last: dict[str, Any] = {}
        self._last_read = 0.0
        self._error = ""
        self._duration_s: float | None = None

    def prompt(self) -> str:
        lines = [f'- "{f["name"]}" ({f["type"]}) : {f["description"] or f["name"]}' for f in self.fields]
        return ("Tu lis une capture d'écran de jeu vidéo. Relève uniquement les valeurs visibles à l'écran.\n"
                "Réponds par un seul objet JSON avec exactement ces clés :\n" + "\n".join(lines) +
                "\nSi une valeur n'est pas lisible à l'écran, mets null. N'invente rien.")

    def detect(self) -> bool:
        try:
            return bool(self._capture())
        except Exception:  # noqa: BLE001 — pas d'écran : l'adaptateur est simplement indisponible
            return False

    def _validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for spec in self.fields:
            value = raw.get(spec["name"])
            if value is None or value == "":
                continue
            try:
                out[spec["name"]] = _CASTS[spec["type"]](value)
            except (TypeError, ValueError):
                continue  # le modèle a répondu autre chose qu'une valeur du bon type : champ laissé absent
        return out

    def read_state(self, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if force or now - self._last_read >= self.min_interval_s:
            self._last_read, self._error = now, ""
            started = time.perf_counter()
            try:
                answer = self._vision(self.prompt(), self._capture())
                self._last = self._validate(extract_json(answer))
                if not self._last:
                    self._error = "aucune valeur lisible dans la réponse du modèle"
            except (RuntimeError, OSError, urllib.error.URLError, ValueError) as exc:
                self._error = f"{type(exc).__name__}: {exc}"
            self._duration_s = round(time.perf_counter() - started, 2)
        state: dict[str, Any] = {"fields": copy.deepcopy(self._last)}
        state[META_KEY] = {
            "adapter": self.id, "game": self.game, "read_only": True, "experimental": True,
            "has_data": bool(self._last), "model": self.model, "last_read": self._last_read or None,
            "duration_s": self._duration_s, "error": self._error,
        }
        return state

    def schema(self) -> dict[str, Any]:
        return {"adapter": self.id, "experimental": True,
                "sections": {"fields": "Champs lus à l'écran par le modèle de vision"},
                "fields": {f["name"]: {"type": f["type"], "private": f["private"], "description": f["description"]}
                           for f in self.fields}}

    def widgets(self) -> list[dict[str, Any]]:
        return [{"id": f"{self.id}_fields", "title": f"{self.game} (expérimental)", "section": "fields",
                 "note": "Valeurs lues à l'écran par un modèle de vision : peuvent être fausses"}]

    def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]:
        if check_mode(mode) == PRIVACY_OFF:
            return copy.deepcopy(state)
        private = {f["name"] for f in self.fields if f["private"]}
        fields = {k: (MASK if k in private else v) for k, v in (state.get("fields") or {}).items()}
        return filter_state({**state, "fields": fields}, self.options)

    def context_for_llm(self, state: dict[str, Any]) -> str:
        fields = state.get("fields") or {}
        if not fields:
            return f"Contexte {self.game} : rien de lisible à l'écran pour l'instant."
        return (f"Contexte {self.game} (lu à l'écran, peut être inexact) : "
                + " ; ".join(f"{k} = {v}" for k, v in fields.items()) + ".")
