"""Module du Hub : labo de chimie (tableau périodique, équations, stœchiométrie, solutions, titrages simulés).

Tout est calculé ici, en Python déterministe ; la page `core/web/chem_app.html` affiche et anime.

Commandes (`POST /modules/chem_lab/command/<commande>`, ou bus `module.chem_lab.cmd.<commande>`) :

    elements     {}                                             les 118 éléments et les familles
    element      {"element"}                                    une fiche
    molar_mass   {"formula"}                                    masse molaire et composition
    balance      {"equation"}                                   équilibrage exact
    stoichiometry {"equation", "quantities", "yield_percent"?}  réactif limitant, masses formées
    ph           {"kind", "concentration", "pka"?}              pH exact
    buffer       {"acid", "base", "pka"}                        tampon
    titration    {"analyte", "c_analyte", "v_analyte_ml", "c_titrant", "pka"?}   courbe simulée
    dilution     {"c1"?, "v1"?, "c2"?, "v2"?}                   C1V1 = C2V2
    preparation  {"formula", "concentration", "volume_L", "purity_percent"?}
    tools {}  ·  tool {"name", "arguments"}                     outils des agents (mêmes que le serveur MCP)
    hermes {}  ·  hermes_register {}                            serveur MCP « aethertwin_chimie » chez Hermes
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.chem_lab import agent, chemistry, elements, solutions

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_NAME = "aethertwin_chimie"
MCP_SCRIPT = REPO_ROOT / "modules" / "chem_lab" / "mcp_server.py"


class ChemLabModule(ModuleBase):
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def health(self) -> Health:
        return Health(ok=True, detail=f"{len(elements.ELEMENTS)} éléments")

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
        except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError) as exc:
            reply = {"ok": False, "error": str(exc) or type(exc).__name__}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def run(self, command: str, p: dict[str, Any]) -> Any:
        """Exécute une commande (aussi appelée directement par les tests)."""
        if command == "elements":
            return {"elements": elements.ELEMENTS, "categories": elements.CATEGORIES}
        if command == "element":
            return elements.element(p.get("element"))
        if command == "molar_mass":
            return chemistry.molar_mass(str(p.get("formula", "")))
        if command == "balance":
            return chemistry.balance(str(p.get("equation", "")))
        if command == "stoichiometry":
            return chemistry.stoichiometry(str(p.get("equation", "")), dict(p.get("quantities") or {}),
                                           float(p.get("yield_percent") or 100))
        if command == "ph":
            return solutions.solution_ph(str(p.get("kind")), p.get("concentration"), p.get("pka"))
        if command == "buffer":
            return solutions.buffer_ph(p.get("acid"), p.get("base"), float(p.get("pka")))
        if command == "titration":
            return solutions.titration(str(p.get("analyte")), p.get("c_analyte"), p.get("v_analyte_ml"),
                                       p.get("c_titrant"), p.get("pka"), p.get("v_max_ml"))
        if command == "dilution":
            return solutions.dilution(p.get("c1"), p.get("v1"), p.get("c2"), p.get("v2"))
        if command == "preparation":
            return solutions.preparation(str(p.get("formula", "")), p.get("concentration"), p.get("volume_L"),
                                         float(p.get("purity_percent") or 100))
        if command == "tools":
            return agent.TOOL_SPECS
        if command == "tool":
            return agent.call_tool(str(p.get("name", "")), p.get("arguments") or {})
        if command in ("hermes", "hermes_register"):
            return self.hermes(register=command == "hermes_register")
        raise ValueError(f"commande inconnue : {command!r}")
