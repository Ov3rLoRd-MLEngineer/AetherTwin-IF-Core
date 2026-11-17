"""Adaptateur World of Warcraft (Retail) : l'implémentation d'origine derrière l'interface `GameAdapter`.

Chaîne de données inchangée : addon Lua `HermesAssistant` → fichier SavedVariables (écrit par le jeu
au `/reload`, à la déconnexion ou via `/ha save`) → lecture seule ici. Conforme aux CGU : aucune
lecture mémoire, aucune automatisation.

L'adaptateur réutilise `GameConnection`, `lua_parser` et `SnapshotCache` de `app/` sans les modifier.
Il ne lit que des fichiers et n'en écrit aucun.
"""
from __future__ import annotations

import copy
from typing import Any

from modules.gaming_hud import ensure_app_path
from modules.gaming_hud.adapters.base import META_KEY, PRIVACY_OFF, check_mode
from modules.gaming_hud.adapters.privacy import PrivacyOptions, filter_state

SECTIONS: dict[str, str] = {
    "character": "Personnage : nom, royaume, niveau, classe, spécialisation, zone, niveau d'objet, or, statistiques",
    "equipment": "Équipement porté, emplacement par emplacement, avec infobulles",
    "inventory": "Sacs : capacité, emplacements utilisés, objets",
    "quests": "Journal des quêtes : quêtes en cours, objectifs, récompenses",
    "professions": "Métiers et niveaux",
    "recipes": "Recettes connues par métier",
    "talents": "Talents et configuration",
    "spellbook": "Grimoire",
    "achievements": "Hauts faits : points, progression, derniers obtenus",
    "collections": "Collections du bataillon : montures, mascottes, jouets, héritage",
    "currencies": "Monnaies",
    "factions": "Réputations",
    "lockouts": "Verrouillages d'instances et boss mondiaux",
    "vault": "Grande Chambre forte",
    "warbandBank": "Banque de bataillon",
    "guildBank": "Banque de guilde",
    "log": "Journal d'événements capturés par l'addon",
}

WIDGETS: tuple[tuple[str, str, str, str], ...] = (
    ("personnage", "Personnage", "character", "Nom, niveau, expérience, or, zone"),
    ("equipement", "Équipement", "equipment", "Les 18 emplacements avec infobulles"),
    ("quetes", "Quêtes", "quests", "Quêtes suivies et objectifs"),
    ("sacs", "Sacs", "inventory", "Remplissage et objets les plus nombreux"),
    ("metiers", "Métiers", "professions", "Niveaux de métiers"),
    ("monnaies", "Monnaies", "currencies", "Monnaies de l'extension"),
    ("instances", "Instances", "lockouts", "Verrouillages et Grande Chambre forte"),
)

MONEY_KEYS = ("money", "warbandMoney")  # en pièces de cuivre
COPPER_PER_GOLD = 10_000
NAME_KEYS = ("name", "realm", "guild", "titleName")  # appliqué aux seules sections ci-dessous
NAMED_SECTIONS = ("character", "guildBank")


class WowRetailAdapter:
    """Lit l'état du personnage depuis les SavedVariables de l'addon HermesAssistant."""

    id = "wow_retail"

    def __init__(self, game_path: str | None = None, cache_path: str | None = None,
                 options: PrivacyOptions | None = None, autodetect: bool = True) -> None:
        ensure_app_path()
        from game_connection import GameConnection
        from snapcache import SnapshotCache

        from config import WoWConfig

        self.options = options or PrivacyOptions()
        self._merge = SnapshotCache.merge
        path = WoWConfig.normalize_path(game_path) if game_path else ""
        if not path and autodetect:
            path = WoWConfig.WOW_PATH if WoWConfig.is_wow_installed() else next(
                (c for c in WoWConfig.detect_installs() if WoWConfig.normalize_path(c)), "")
        self._connection = GameConnection(path or game_path or WoWConfig.WOW_PATH)
        # dernier état connu : sert la règle « une section vide n'écrase jamais une section connue »
        self._last: dict[str, Any] | None = SnapshotCache(cache_path).load() if cache_path else None

    def detect(self) -> bool:
        try:
            return bool(self._connection.is_connected())
        except OSError:
            return False

    def read_state(self) -> dict[str, Any]:
        connection = self._connection
        try:
            fresh = connection.refresh()
        except Exception as exc:  # noqa: BLE001 — une lecture ratée ne doit jamais faire tomber le module
            fresh, connection.last_error = False, f"{type(exc).__name__}: {exc}"
        if fresh and connection.snapshot:
            self._last = self._merge(connection.snapshot, self._last)
        state: dict[str, Any] = copy.deepcopy(self._last) if self._last else {}
        state[META_KEY] = {
            "adapter": self.id,
            "game": "World of Warcraft (Retail)",
            "read_only": True,
            "detected": self.detect(),
            "has_data": bool(self._last),
            "source_file": connection.file_path,
            "file_time": connection.file_mtime or None,
            "error": connection.last_error,
        }
        return state

    def schema(self) -> dict[str, Any]:
        return {"adapter": self.id, "sections": dict(SECTIONS), "money_unit": "cuivre (10 000 = 1 pièce d'or)"}

    def widgets(self) -> list[dict[str, Any]]:
        return [{"id": wid, "title": title, "section": section, "note": note} for wid, title, section, note in WIDGETS]

    def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]:
        if check_mode(mode) == PRIVACY_OFF:
            return copy.deepcopy(state)
        character = state.get("character") or {}
        guild_bank = state.get("guildBank") or {}
        names = [character.get("name"), guild_bank.get("guild")]
        out = {}
        for section, value in state.items():
            out[section] = filter_state(
                value, self.options, money_keys=MONEY_KEYS, money_unit=COPPER_PER_GOLD, names=names,
                name_keys=NAME_KEYS if section in NAMED_SECTIONS else (),
            )
        return out

    def context_for_llm(self, state: dict[str, Any]) -> str:
        """Même phrase que l'application d'origine (`main.player_context`), construite depuis l'état normalisé."""
        c = state.get("character") or {}
        if not c.get("name"):
            return "Contexte joueur : inconnu (aucune donnée de jeu disponible)."
        ilvl = c.get("ilvl") or 0
        try:
            ilvl_text = f"{float(ilvl):g}"
        except (TypeError, ValueError):
            ilvl_text = str(ilvl)
        return (f"Contexte joueur : {c.get('name')}, niveau {c.get('level', '?')} {c.get('class', '')} "
                f"{c.get('specialization', '')}, zone {c.get('zone') or 'inconnue'}, "
                f"niveau d'objet {ilvl_text}.").replace("  ", " ")
