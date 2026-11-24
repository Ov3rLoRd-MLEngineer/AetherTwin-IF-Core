"""Module du Hub : explorateur de données (tableur à formules, graphiques, ajustements, simulations).

Le moteur de formules et les analyses sont en Python (`formula.py`, `analysis.py`) ; la page
`core/web/data_app.html` envoie le contenu brut des cellules et affiche les valeurs, graphiques et résultats.

Commandes (`POST /modules/data_lab/command/<commande>`, ou bus `module.data_lab.cmd.<commande>`) :

    recalc      {"cells"}                                   valeurs affichées de toutes les cellules
    functions   {}                                          noms des fonctions connues
    list {}  ·  load {"name"}  ·  save {"name", "cells", "widths"?, "charts"?}  ·  delete {"name"}
    import      {"filename", "data" (base64)}               CSV, TSV ou Excel .xlsx → cellules
    export_csv  {"cells", "separator"?}                     texte CSV des valeurs
    sweep       {"cells", "input", "start", "stop", "steps", "outputs", "input2"?, …}
    montecarlo  {"cells", "inputs", "outputs", "runs"?, "threshold"?, "seed"?}
    goal_seek   {"cells", "target", "value", "input"}
    fit         {"cells", "x_range", "y_range", "model"?, "degree"?}
    describe    {"cells", "range"}  ·  sort {"cells", "range", "column", "descending"?, "header"?}
    tools {}  ·  tool {"name", "arguments"}                 outils des agents (mêmes que le serveur MCP)
    hermes {}  ·  hermes_register {}                        serveur MCP « aethertwin_donnees » chez Hermes

Configuration (section `data_lab` de `config/local.yaml`), facultative : `data_dir: "data/data_lab"`.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.data_lab import agent, analysis
from modules.data_lab.formula import Err, Sheet, display
from modules.data_lab.workbooks import DATA_DIR, REPO_ROOT, Store, export_csv, import_file

MCP_NAME = "aethertwin_donnees"
MCP_SCRIPT = REPO_ROOT / "modules" / "data_lab" / "mcp_server.py"


def recalc(cells: dict[str, Any]) -> dict[str, Any]:
    values = Sheet(cells or {}).values()
    out = {}
    for ref, v in values.items():
        kind = "e" if isinstance(v, Err) else "b" if isinstance(v, bool) else "n" if isinstance(v, float) else "t"
        out[ref] = [display(v), kind]
    return {"values": out}


class DataLabModule(ModuleBase):
    def start(self) -> None:
        self.store = Store(REPO_ROOT / str(self.config.get("data_dir") or DATA_DIR))

    def stop(self) -> None:
        pass

    def health(self) -> Health:
        try:
            count = len(self.store.list())
        except OSError as exc:
            return Health(ok=True, degraded=True, detail=f"dossier des classeurs illisible ({exc})")
        return Health(ok=True, detail=f"{count} classeur(s)")

    def hermes(self, register: bool = False) -> dict[str, Any]:
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
        except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError, OverflowError) as exc:
            reply = {"ok": False, "error": str(exc) or type(exc).__name__}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def run(self, command: str, p: dict[str, Any]) -> Any:
        """Exécute une commande (aussi appelée directement par les tests)."""
        cells = p.get("cells") or {}
        if command == "recalc":
            return recalc(cells)
        if command == "list":
            return self.store.list()
        if command == "load":
            return self.store.load(p.get("name"))
        if command == "save":
            return self.store.save(p.get("name"), cells, {k: p[k] for k in ("widths", "charts") if k in p})
        if command == "delete":
            return self.store.delete(p.get("name"))
        if command == "import":
            try:
                data = base64.b64decode(str(p.get("data", "")), validate=True)
            except (binascii.Error, ValueError):
                raise ValueError("fichier illisible (base64 attendu)") from None
            return {"cells": import_file(str(p.get("filename", "")), data)}
        if command == "export_csv":
            return {"csv": export_csv(cells, str(p.get("separator") or ";"))}
        if command == "sweep":
            return analysis.sweep(cells, p["input"], p["start"], p["stop"], p["steps"], p["outputs"],
                                  p.get("input2"), p.get("start2"), p.get("stop2"), p.get("steps2"))
        if command == "montecarlo":
            return analysis.monte_carlo(cells, p.get("inputs") or {}, p["outputs"], int(p.get("runs") or 5000),
                                        p.get("seed"), p.get("threshold"))
        if command == "goal_seek":
            return analysis.goal_seek(cells, p["target"], p["value"], p["input"])
        if command == "fit":
            return analysis.fit(cells, p["x_range"], p["y_range"], str(p.get("model") or "lineaire"),
                                int(p.get("degree") or 2))
        if command == "describe":
            return analysis.describe(cells, p["range"])
        if command == "sort":
            return analysis.sort_range(cells, p["range"], str(p["column"]), bool(p.get("descending")),
                                       bool(p.get("header")))
        if command == "functions":
            from modules.data_lab.formula import FUNCTIONS

            extra = ["SI", "IF", "SIERREUR", "IFERROR", "ET", "AND", "OU", "OR", "ALEA", "RAND", "ALEA.ENTRE.BORNES",
                     "RANDBETWEEN", "LOI.NORMALE", "UNIFORME", "RESOUDRE", "SOLVE", "DERIVEE", "INTEGRALE"]
            return sorted(set(FUNCTIONS) | set(extra))
        if command == "tools":
            return agent.TOOL_SPECS
        if command == "tool":
            return agent.call_tool(self.store, str(p.get("name", "")), p.get("arguments") or {})
        if command in ("hermes", "hermes_register"):
            return self.hermes(register=command == "hermes_register")
        raise ValueError(f"commande inconnue : {command!r}")
