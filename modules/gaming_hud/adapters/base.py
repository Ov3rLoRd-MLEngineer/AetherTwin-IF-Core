"""Interface commune « adaptateur de jeu ».

Un adaptateur sait lire l'état d'un jeu **en lecture seule** (fichiers écrits par le jeu, journaux,
captures d'écran) et le présenter sous une forme normalisée. Aucune lecture mémoire, aucune
automatisation, aucun envoi d'entrées dans le jeu.

Le HUD, l'overlay OBS et l'assistant ne connaissent que cette interface : ajouter un jeu revient
à écrire un adaptateur.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

PRIVACY_OFF = "off"
PRIVACY_SHOWCASE = "showcase"  # diffusion en direct (OBS) : rien de privé ne doit sortir
PRIVACY_MODES = (PRIVACY_OFF, PRIVACY_SHOWCASE)

META_KEY = "_meta"  # informations sur la lecture elle-même (adaptateur, source, horodatage)


@runtime_checkable
class GameAdapter(Protocol):
    """Contrat d'un adaptateur de jeu."""

    id: str  # identifiant stable, ex. « wow_retail »

    def detect(self) -> bool:
        """Le jeu est-il installé ou en cours d'exécution ? Ne lève jamais d'exception."""

    def read_state(self) -> dict[str, Any]:
        """État normalisé, en lecture seule. Un état partiel ou vide est un résultat valide."""

    def schema(self) -> dict[str, Any]:
        """Description des sections de l'état (pour l'interface et pour le LLM)."""

    def widgets(self) -> list[dict[str, Any]]:
        """Widgets proposés par l'adaptateur : `[{"id", "title", "section", "note"}]`."""

    def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]:
        """Copie de l'état sans données privées. `mode` : « off » ou « showcase »."""

    def context_for_llm(self, state: dict[str, Any]) -> str:
        """Résumé textuel court de l'état, joint aux questions posées à l'assistant."""


def check_mode(mode: str) -> str:
    if mode not in PRIVACY_MODES:
        raise ValueError(f"mode de confidentialité inconnu : {mode!r} (attendu : {', '.join(PRIVACY_MODES)})")
    return mode
