"""Module du Hub : intégration externe de la suite libre ArtCraft (équipe ArtCraft, github.com/storytold).

Rien n'est fourni avec AetherTwin : chaque logiciel se télécharge à la demande depuis sa publication GitHub officielle,
empreinte SHA-256 vérifiée (voir `suite.py`). Une fois installé, il s'ouvre depuis le Hub et son serveur MCP
(`<appli>-cli mcp`) se branche sur Hermes Agent ou Claude Code.

Commandes (`POST /modules/artcraft/command/<commande>`, ou bus `module.artcraft.cmd.<commande>`) :

    catalog     {}                        les dix logiciels, installés ou non, tâche en cours
    icons       {}                        télécharge les icônes officielles (kit presse) sur ce PC
    icon        {"app"}                   icône en base64 (PNG 128 px)
    install     {"app"}                   installe ou met à jour (en arrière-plan, suivre avec catalog)
    uninstall   {"app"}                   retire la version portable
    launch      {"app"}                   ouvre le logiciel
    mcp         {"app"}                   commande du serveur MCP et ligne pour Claude Code
    hermes      {"app", "register"?}      état du branchement Hermes ; register=true le branche

Configuration (section `artcraft` de `config/local.yaml`), facultative :

    data_dir: "data/artcraft"
"""
from __future__ import annotations

import base64
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.artcraft.suite import DATA_DIR, REPO_ROOT, Suite


class ArtCraftModule(ModuleBase):
    def start(self) -> None:
        self.suite = Suite(REPO_ROOT / str(self.config.get("data_dir") or DATA_DIR))

    def stop(self) -> None:
        pass

    def health(self) -> Health:
        try:
            count = sum(1 for app in self.suite.catalog() if app["installed"])
        except OSError as exc:
            return Health(ok=True, degraded=True, detail=f"dossier illisible ({exc})")
        return Health(ok=True, detail=f"{count} logiciel(s) ArtCraft installé(s) sur 10")

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
        app = payload.get("app")
        if command == "catalog":
            return self.suite.catalog()
        if command == "icons":
            return self.suite.fetch_icons()
        if command == "icon":
            return {"app": app, "png": base64.b64encode(self.suite.icon(app)).decode("ascii")}
        if command == "install":
            return self.suite.install_async(app)
        if command == "uninstall":
            return self.suite.uninstall(app)
        if command == "launch":
            return self.suite.launch(app)
        if command == "mcp":
            return self.suite.mcp(app)
        if command == "hermes":
            return self.suite.hermes(app, bool(payload.get("register")))
        raise ValueError(f"commande inconnue : {command!r}")
