"""Filtre de confidentialité commun aux adaptateurs (mode Showcase / diffusion OBS).

Principe : on ne fait pas confiance à la forme des données. L'état est parcouru en entier et
- toute **clé** au nom sensible (chemin, compte, e-mail, clé, jeton…) est supprimée ;
- toute **chaîne** est nettoyée des e-mails, chemins de fichiers et jetons qu'elle contient ;
- les montants sont arrondis ou masqués ;
- les noms de personnages (et toute chaîne qui les contient) sont remplacés, si l'option est activée.

L'état d'origine n'est jamais modifié : le filtre rend une copie.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

MASK = "•••"

# Noms de clés qui ne doivent jamais sortir, quelle que soit leur valeur.
SENSITIVE_KEY = re.compile(
    r"(account|compte|e-?mail|courriel|battle_?tag|btag|pass(word|wd)?|mot_?de_?passe|secret|token|jeton|"
    r"api_?key|apikey|cle_?api|credential|auth|cookie|session_?id|"
    r"path|chemin|file(name)?$|fichier|folder|dossier|directory|source_file|home|user(name)?$|login|ip_?addr)",
    re.IGNORECASE,
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# (?<![A-Za-z]) : « C:\… » est un chemin, mais pas le « p:// » de « http:// »
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?:[^\s\"'<>|:*?\\/]+[\\/]?)+")
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>|]+")
_UNIX_HOME = re.compile(r"(?:/home/|/Users/)[^\s\"'<>|:]+")
_TOKEN = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}|\b[0-9a-fA-F]{32,}\b|\b[A-Za-z0-9+/]{40,}={0,2})"
)
_SCRUBBERS = (_EMAIL, _UNC_PATH, _WINDOWS_PATH, _UNIX_HOME, _TOKEN)


@dataclass(frozen=True)
class PrivacyOptions:
    """Réglages du mode Showcase."""

    hide_character_names: bool = False
    gold: str = "round"  # « round » (1 chiffre significatif) | « hide » | « keep »
    name_placeholder: str = "Aventurier"

    def __post_init__(self) -> None:
        if self.gold not in ("round", "hide", "keep"):
            raise ValueError("gold doit valoir « round », « hide » ou « keep »")


def scrub_text(text: str) -> str:
    """Retire e-mails, chemins de fichiers et jetons d'une chaîne."""
    for pattern in _SCRUBBERS:
        text = pattern.sub(MASK, text)
    return text


def round_amount(value: float, unit: int = 1) -> int:
    """Arrondit à 1 chiffre significatif, dans l'unité donnée (ex. 10 000 cuivres = 1 pièce d'or)."""
    amount = float(value) / unit
    if amount <= 0:
        return 0
    if amount < 1:
        return 0
    magnitude = 10 ** math.floor(math.log10(amount))
    return int(round(amount / magnitude) * magnitude) * unit


def filter_state(
    state: Any,
    options: PrivacyOptions,
    *,
    money_keys: Iterable[str] = (),
    money_unit: int = 1,
    name_keys: Iterable[str] = (),
    names: Iterable[str] = (),
    private_keys: Iterable[str] = (),
) -> Any:
    """Copie filtrée de `state`.

    - `money_keys` : clés dont la valeur numérique est un montant (arrondi ou masqué selon `options.gold`).
    - `name_keys`  : clés qui portent un nom de personnage / de guilde / de royaume.
    - `names`      : noms connus, à remplacer partout où ils apparaissent dans du texte.
    - `private_keys` : clés supplémentaires à supprimer (déclarées par l'adaptateur).
    """
    money = {k.lower() for k in money_keys}
    named = {k.lower() for k in name_keys}
    private = {k.lower() for k in private_keys}
    known_names = sorted({n for n in names if isinstance(n, str) and len(n.strip()) >= 2}, key=len, reverse=True)
    name_pattern = (re.compile("|".join(re.escape(n) for n in known_names), re.IGNORECASE)
                    if options.hide_character_names and known_names else None)

    def clean_text(text: str) -> str:
        text = scrub_text(text)
        if name_pattern is not None:
            text = name_pattern.sub(options.name_placeholder, text)
        return text

    def walk(value: Any, key: str = "") -> Any:
        low = key.lower()
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                name = str(k)
                if name.lower() in private or SENSITIVE_KEY.search(name):
                    continue
                out[k if not isinstance(k, str) else clean_text(k)] = walk(v, name)
            return out
        if isinstance(value, list | tuple):
            return [walk(item, key) for item in value]
        if low in money and isinstance(value, int | float) and not isinstance(value, bool):
            if options.gold == "hide":
                return None
            return round_amount(value, money_unit) if options.gold == "round" else value
        if isinstance(value, str):
            if low in named and options.hide_character_names and value.strip():
                return options.name_placeholder
            return clean_text(value)
        return value

    return walk(state)


def leaks(filtered: Any, canaries: Iterable[str]) -> list[str]:
    """Canaris retrouvés dans la sortie filtrée (aide de test : la liste doit être vide)."""
    import json

    blob = json.dumps(filtered, ensure_ascii=False, default=str).lower()
    return [c for c in canaries if c.lower() in blob]
