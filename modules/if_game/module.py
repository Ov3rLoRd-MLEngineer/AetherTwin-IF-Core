"""Module du Hub : le jeu « Fuma & Inoue : Les Gardiens de l'Éther ».

    module.if_game.cmd.new    {"request_id", "seed": 42}
    module.if_game.cmd.act    {"request_id", "text": "nord"}
    module.if_game.cmd.state  {"request_id"}

Sauvegarde automatique après chaque action dans `data/if_game/partie.json` (ignoré par Git).
Configuration (section `if_game`) : `hub_api` (vide = jeu sans modèle, entièrement procédural), `model`.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.if_game.world import World, act, describe, view

REPO_ROOT = Path(__file__).resolve().parents[2]


def hub_text(hub_api: str, model: str = "", temperature: float = 0.8, timeout_s: float = 120.0):
    def call(prompt: str) -> str:
        body = {"messages": [{"role": "user", "content": prompt}], "think": False, "temperature": temperature}
        if model:
            body["model"] = model
        request = urllib.request.Request(hub_api.rstrip("/") + "/v1/chat/completions",  # noqa: S310
                                         data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 — API locale du Hub
            return str(json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"])
    return call


class IfGameModule(ModuleBase):
    def start(self) -> None:
        self.save_path = Path(str(self.config.get("save") or REPO_ROOT / "data" / "if_game" / "partie.json"))
        hub = str(self.config.get("hub_api", "http://127.0.0.1:5750"))
        self.propose = hub_text(hub, str(self.config.get("model", ""))) if hub else None
        try:
            self.world: World | None = World.load(self.save_path) if self.save_path.is_file() else None
            self.load_error = ""
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.world, self.load_error = None, f"sauvegarde illisible ({exc}) : nouvelle partie"

    def stop(self) -> None:
        if self.world is not None:
            self.world.save(self.save_path)

    def health(self) -> Health:
        if self.world is None:
            return Health(ok=True, detail=self.load_error or "aucune partie en cours")
        return Health(ok=True, degraded=self.propose is None,
                      detail=f"tour {self.world.turn}, {len(self.world.places)} lieux explorés"
                             + ("" if self.propose else " — sans modèle (procédural)"))

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        try:
            reply = {"ok": True, "result": self._run(command, payload)}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def _run(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "new" or (self.world is None and command in ("act", "state")):
            self.world = World.new(int(payload.get("seed", 0)) if command == "new" else 0)
            self.world.log(describe(self.world))
            narration = self.world.journal[-1]
        elif command == "act":
            narration = act(self.world, str(payload.get("text", ""))[:200], self.propose, self.propose)
        elif command == "state":
            narration = ""
        else:
            raise ValueError(f"commande inconnue : {command!r}")
        self.world.save(self.save_path)
        return {"narration": narration, **view(self.world)}
