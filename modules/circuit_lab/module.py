"""Module du Hub : atelier circuits (consoles 8 et 16 bits à monter, téléviseur, programmation de cartouches, banc
logique façon FPGA, cartes à microcontrôleur RP2040 et AVR).

Les émulations (processeurs, vidéo, son, manettes, portes logiques, microcontrôleurs) et les assembleurs tournent
dans la page `core/web/circuit_app.html` ;
le module fournit les exemples et range les programmes de l'utilisateur.

Commandes (`POST /modules/circuit_lab/command/<commande>`, ou bus `module.circuit_lab.cmd.<commande>`) :

    examples        {}                       exemples fournis
    example         {"name"}                 source d'un exemple
    projects        {}                       programmes enregistrés
    project_load    {"name"}  ·  project_save {"name", "source"}  ·  project_delete {"name"}

Configuration (section `circuit_lab` de `config/local.yaml`), facultative :

    data_dir: "data/circuit_lab"
"""
from __future__ import annotations

from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.circuit_lab.lab import DATA_DIR, REPO_ROOT, Lab


class CircuitLabModule(ModuleBase):
    def start(self) -> None:
        self.lab = Lab(REPO_ROOT / str(self.config.get("data_dir") or DATA_DIR))

    def stop(self) -> None:
        pass

    def health(self) -> Health:
        try:
            count = len(self.lab.list())
        except OSError as exc:
            return Health(ok=True, degraded=True, detail=f"dossier des programmes illisible ({exc})")
        return Health(ok=True, detail=f"{count} programme(s)")

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        try:
            reply = {"ok": True, "result": self.run(command, payload)}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            reply = {"ok": False, "error": str(exc) or type(exc).__name__}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def run(self, command: str, payload: dict[str, Any]) -> Any:
        """Exécute une commande (aussi appelée directement par les tests)."""
        if command == "examples":
            return self.lab.examples()
        if command == "example":
            return self.lab.example(payload.get("name"))
        if command == "projects":
            return self.lab.list()
        if command == "project_load":
            return self.lab.load(payload.get("name"))
        if command == "project_save":
            return self.lab.save(payload.get("name"), payload.get("source"))
        if command == "project_delete":
            return self.lab.delete(payload.get("name"))
        raise ValueError(f"commande inconnue : {command!r}")
