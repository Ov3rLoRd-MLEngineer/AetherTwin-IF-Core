"""Module du Hub : studio pixel art (sprites, animations, cartes en tuiles), exports, outils pour les agents.

Commandes (`POST /modules/pixel_studio/command/<commande>`, ou bus `module.pixel_studio.cmd.<commande>`) :

    projects        {}                                   projets enregistrés (avec vignette)
    project_load    {"name"}  ·  project_save {"project"}  ·  project_delete {"name"}
    palettes        {}                                   palettes intégrées
    palette_ramp    {"base", "count"}                    rampe de tons avec glissement de teinte
    palette_from_image {"data": "<base64>", "count"}     palette tirée d'une image
    export          {"project", "kind": png|sheet|gif|map, "scale", "frame", "columns"}
                                                         fichier écrit dans data/pixel_studio/exports + base64
    game_export     {"name"}                             sprite pour `jeu.sprite()` / `jeu.carte()` (calculatrice)
    exports_open    {}                                   ouvre le dossier des exports
    hermes {}  ·  hermes_register {}                     serveur MCP du studio chez Hermes Agent
    tools  {}  ·  tool {"name", "arguments"}             outils des agents (`agent.py`)

Configuration (section `pixel_studio` de `config/local.yaml`), facultative :

    data_dir: "data/pixel_studio"
"""
from __future__ import annotations

import base64
import binascii
import os
import sys
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.pixel_studio import agent, palettes, project
from modules.pixel_studio.studio import DATA_DIR, REPO_ROOT, Studio

MCP_NAME = "aethertwin_pixel"
MCP_SCRIPT = REPO_ROOT / "modules" / "pixel_studio" / "mcp_server.py"
MAX_IMPORT = 8_000_000


class PixelStudioModule(ModuleBase):
    def start(self) -> None:
        self.studio = Studio(REPO_ROOT / str(self.config.get("data_dir") or DATA_DIR))  # relatif : depuis le dépôt

    def stop(self) -> None:
        pass

    def health(self) -> Health:
        try:
            folder = self.studio.store.folder
            count = len(list(folder.glob("*.aether-pixel"))) if folder.is_dir() else 0
        except OSError as exc:
            return Health(ok=True, degraded=True, detail=f"dossier des projets illisible ({exc})")
        return Health(ok=True, detail=f"{count} projet(s)")

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

    def run(self, command: str, payload: dict[str, Any]) -> Any:
        """Exécute une commande (aussi appelée directement par les tests)."""
        store = self.studio.store
        if command == "projects":
            return store.list()
        if command == "project_load":
            return store.load(project.clean_name(payload.get("name")))
        if command == "project_save":
            return store.save(payload.get("project"))
        if command == "project_delete":
            return store.delete(project.clean_name(payload.get("name")))
        if command == "palettes":
            return palettes.catalog()
        if command == "palette_ramp":
            return palettes.ramp(str(payload.get("base", "")), int(payload.get("count", 5)))
        if command == "palette_from_image":
            data = str(payload.get("data", "")).split(",")[-1]
            if len(data) > MAX_IMPORT * 4 // 3 + 4:
                raise ValueError("image de plus de 8 Mo")
            try:
                raw = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                raise ValueError("image illisible (base64 attendu)") from None
            return palettes.from_image(raw, int(payload.get("count", 16)))
        if command == "export":
            return self.studio.export(payload.get("project"), str(payload.get("kind", "png")),
                                      int(payload.get("scale", 1)), int(payload.get("frame", 0)),
                                      int(payload.get("columns", 0)))
        if command == "game_export":
            return self.studio.game_export(project.clean_name(payload.get("name")))
        if command == "exports_open":
            self.studio.exports.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(self.studio.exports)  # noqa: S606 — dossier fixe du studio
            return str(self.studio.exports)
        if command in ("hermes", "hermes_register"):
            return self.hermes(register=command == "hermes_register")
        if command == "tools":
            return agent.TOOL_SPECS
        if command == "tool":
            return agent.call_tool(self.studio, str(payload.get("name", "")), payload.get("arguments"))
        raise ValueError(f"commande inconnue : {command!r}")
