"""Module du Hub : calculs scientifiques à la demande et Professeur adaptatif.

Commandes reçues sur le bus (réponse sur `module.genesis_lab.result`, avec le même `request_id`) :

    module.genesis_lab.cmd.compute   {"request_id", "tool": "chem.molar_mass_g_mol", "args": {"formula": "H2O"}}
    module.genesis_lab.cmd.exercise  {"request_id", "domain": "astro"}
    module.genesis_lab.cmd.answer    {"request_id", "domain", "level", "seed", "given"}
    module.genesis_lab.cmd.progress  {"request_id"}

Seuls les outils de la liste blanche `TOOLS` peuvent être appelés : un nom d'outil venu d'un LLM ne
peut désigner aucune autre fonction.

Configuration (section `genesis_lab` de `config/local.yaml`), tout est facultatif :

    profile: "data/genesis_lab/eleve.json"   # progression de l'élève
    hub_api: "http://127.0.0.1:5750"          # pour faire rédiger les explications par le modèle local
    model: ""                                 # vide = modèle par défaut du Hub
"""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.module_api import Event, Health, Manifest, ModuleBase
from modules.genesis_lab import astro, bio, chem
from modules.genesis_lab.tutor import DOMAINS, Tutor, make_exercise

# Liste blanche : nom public -> fonction. Rien d'autre n'est appelable.
TOOLS: dict[str, Callable[..., Any]] = {
    "bio.analyze_fasta": bio.analyze_fasta,
    "bio.gc_percent": bio.gc_percent,
    "bio.reverse_complement": bio.reverse_complement,
    "bio.transcribe": bio.transcribe,
    "bio.translate": bio.translate,
    "bio.find_orfs": lambda **kw: [orf.to_dict() for orf in bio.find_orfs(**kw)],
    "bio.global_alignment": bio.global_alignment,
    "bio.melting_temperature_wallace": bio.melting_temperature_wallace,
    "astro.orbital_period_s": astro.orbital_period_s,
    "astro.semi_major_axis_m": astro.semi_major_axis_m,
    "astro.circular_speed_m_s": astro.circular_speed_m_s,
    "astro.escape_speed_m_s": astro.escape_speed_m_s,
    "astro.schwarzschild_radius_m": astro.schwarzschild_radius_m,
    "astro.absolute_magnitude": astro.absolute_magnitude,
    "astro.distance_pc_from_parallax": astro.distance_pc_from_parallax,
    "astro.flux_ratio": astro.flux_ratio,
    "astro.pc_to_ly": astro.pc_to_ly,
    "chem.molar_mass_g_mol": chem.molar_mass_g_mol,
    "chem.parse_formula": chem.parse_formula,
    "chem.mass_fractions": chem.mass_fractions,
    "chem.moles_from_mass": chem.moles_from_mass,
    "chem.ideal_gas_volume_m3": chem.ideal_gas_volume_m3,
    "chem.mix_streams": chem.mix_streams,
    "chem.dilution_volume": chem.dilution_volume,
    "chem.ph_weak_acid": chem.ph_weak_acid,
    "chem.ph_buffer": chem.ph_buffer,
    "chem.equilibrium_constant": chem.equilibrium_constant,
}


def compute(tool: str, args: dict[str, Any] | None = None) -> Any:
    """Appelle un outil de la liste blanche. Lève `ValueError` pour tout autre nom ou des arguments invalides."""
    if tool not in TOOLS:
        raise ValueError(f"outil inconnu : {tool!r}")
    if args is not None and not isinstance(args, dict):
        raise ValueError("`args` doit être un dictionnaire de paramètres nommés")
    try:
        return TOOLS[tool](**(args or {}))
    except TypeError as exc:
        raise ValueError(f"arguments invalides pour {tool} : {exc}") from exc


def hub_llm(hub_api: str, model: str = "", timeout_s: float = 300.0) -> Callable[[list[dict[str, str]]], str]:
    """Fabrique un appel au modèle local **par le Hub** (API compatible OpenAI), jamais directement."""
    def call(messages: list[dict[str, str]]) -> str:
        body = json.dumps({"model": model or None, "messages": messages}).encode("utf-8")
        request = urllib.request.Request(hub_api.rstrip("/") + "/v1/chat/completions", data=body,  # noqa: S310
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 — API locale du Hub
            data = json.loads(response.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"])
    return call


class GenesisLabModule(ModuleBase):
    """Calculs déterministes et Professeur adaptatif, pilotés par le bus."""

    def __init__(self, manifest: Manifest, config: dict[str, Any] | None = None) -> None:
        super().__init__(manifest, config)
        self.tutor: Tutor | None = None
        self.requests = 0
        self.errors = 0

    def start(self) -> None:
        profile = Path(str(self.config.get("profile") or "data/genesis_lab/eleve.json"))
        llm = None
        if self.config.get("hub_api"):
            llm = hub_llm(str(self.config["hub_api"]), str(self.config.get("model", "")))
        self.tutor = Tutor(profile, llm=llm)

    def stop(self) -> None:
        self.tutor = None

    def health(self) -> Health:
        with_llm = bool(self.tutor and self.tutor.llm)
        return Health(ok=True, degraded=not with_llm,
                      detail=f"{len(TOOLS)} outils de calcul ; {self.requests} demandes, {self.errors} erreurs ; "
                             + ("explications par le modèle local" if with_llm else "explications types (sans LLM)"))

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        self.requests += 1
        try:
            result = self._run(command, payload)
            reply = {"request_id": payload.get("request_id"), "command": command, "ok": True, "result": result}
        except (ValueError, KeyError, TypeError) as exc:  # demande invalide : erreur rendue, le module continue
            self.errors += 1
            reply = {"request_id": payload.get("request_id"), "command": command, "ok": False,
                     "error": f"{type(exc).__name__}: {exc}"}
        self.publish(Event(f"module.{self.name}.result", reply, source=self.name))

    def _run(self, command: str, payload: dict[str, Any]) -> Any:
        if command == "compute":
            return compute(str(payload.get("tool", "")), payload.get("args"))
        if self.tutor is None:
            raise ValueError("module non démarré")
        if command == "exercise":
            domain = str(payload.get("domain", ""))
            if domain not in DOMAINS:
                raise ValueError(f"domaine inconnu : {domain!r}")
            exercise = self.tutor.next_exercise(domain)
            seed = self.tutor.seed + 1 + sum(1 for item in self.tutor.profile.history if item["domain"] == domain)
            return {**exercise.to_dict(), "seed": seed}  # la réponse attendue n'est jamais envoyée avec l'énoncé
        if command == "answer":
            exercise = make_exercise(str(payload["domain"]), int(payload["level"]), int(payload["seed"]))
            return self.tutor.answer(exercise, payload.get("given"))
        if command == "progress":
            return self.tutor.progress()
        raise ValueError(f"commande inconnue : {command!r}")
