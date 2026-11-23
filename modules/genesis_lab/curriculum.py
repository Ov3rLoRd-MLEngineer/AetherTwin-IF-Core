"""Programmes annuels du Professeur : niveaux (CP à terminale), matières, chapitres et calendrier de l'année.

Les chapitres viennent de `programmes.yaml` (découpage proposé d'après les programmes officiels, à vérifier).
Le calendrier répartit les chapitres sur 36 semaines de cours, en trois trimestres, dans l'ordre du programme.
Un identifiant de chapitre est stable : `<niveau>/<matière>/<numéro>` (ex. `4e/svt/4`).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROGRAMMES = Path(__file__).with_name("programmes.yaml")
WEEKS = 36
TERMS = (("1er trimestre", "septembre à décembre", 13), ("2e trimestre", "janvier à mars", 11),
         ("3e trimestre", "avril à juin", 12))
CHAPTER_ID = re.compile(r"^([a-z0-9]+)/([a-z_]+)/(\d{1,2})$")

# Simulations intégrées (modules/genesis_lab/sims) : mots qui les rattachent à un chapitre.
SIM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "systeme_solaire": ("système solaire", "kepler", "gravitation", "satellites", "saisons", "jour et nuit",
                        "planète", "soleil", "astre"),
    "gaz_parfait": ("gaz", "états de l'eau", "changements d'état", "thermodynamique", "pression", "air",
                    "états et changements"),
    "fluides": ("fluide", "bernoulli", "archimède", "écoulement"),
    "coeur": ("cœur", "circulation", "sanguine", "effort physique", "respiration et effort"),
    "neurone": ("nerveux", "cerveau", "réflexe", "neurone", "stress", "motricité", "comportements"),
    "circuit": ("circuit", "électri", "loi d'ohm", "tension", "intensité", "dipôle"),
    "projectile": ("mouvement", "vitesse", "newton", "inertie", "forces", "chute", "interactions"),
    "ondes": ("onde", "son", "lumière", "signaux", "doppler", "interférences", "musique"),
    "fonctions": ("fonction", "second degré", "dérivation", "exponentielle", "logarithme", "affines",
                  "linéaires", "variations"),
    "fractions": ("fraction", "partage", "moitié", "quart"),
}


class CurriculumError(ValueError):
    """Niveau, matière ou chapitre inconnu."""


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    data = yaml.safe_load(PROGRAMMES.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("niveaux"), list) or not isinstance(data.get("matieres"), dict):
        raise CurriculumError("programmes.yaml illisible")
    return data


def _split(text: str) -> tuple[str, str]:
    title, _, notions = str(text).partition(" : ")
    return title.strip(), notions.strip()


def subject_name(subject: str) -> str:
    return str(_data()["matieres"].get(subject, subject))


def _level(level: str) -> dict[str, Any]:
    for item in _data()["niveaux"]:
        if item["id"] == level:
            return item
    raise CurriculumError(f"niveau inconnu : {level!r}")


def levels() -> list[dict[str, Any]]:
    """Niveaux et leurs matières (nombre de chapitres), pour les listes de choix."""
    return [{"id": n["id"], "nom": n["nom"], "cycle": n.get("cycle", ""), "age": n.get("age"),
             "matieres": [{"id": s, "nom": subject_name(s), "chapitres": len(ch)}
                          for s, ch in (n.get("matieres") or {}).items()]}
            for n in _data()["niveaux"]]


def chapters(level: str, subject: str) -> list[dict[str, Any]]:
    items = (_level(level).get("matieres") or {}).get(subject)
    if not items:
        raise CurriculumError(f"matière inconnue en {level} : {subject!r}")
    out = []
    for i, text in enumerate(items, start=1):
        title, notions = _split(text)
        out.append({"id": f"{level}/{subject}/{i}", "numero": i, "titre": title, "notions": notions,
                    "simulations": suggest_simulations(f"{title} {notions}", subject)})
    return out


def chapter(chapter_id: str) -> dict[str, Any]:
    """Un chapitre et son contexte (niveau, matière, chapitres voisins)."""
    match = CHAPTER_ID.fullmatch(str(chapter_id))
    if not match:
        raise CurriculumError(f"identifiant de chapitre invalide : {chapter_id!r}")
    level, subject, number = match.group(1), match.group(2), int(match.group(3))
    items = chapters(level, subject)
    if not 1 <= number <= len(items):
        raise CurriculumError(f"chapitre inconnu : {chapter_id!r}")
    info = _level(level)
    return {**items[number - 1], "niveau": level, "niveau_nom": info["nom"], "cycle": info.get("cycle", ""),
            "age": info.get("age"), "matiere": subject, "matiere_nom": subject_name(subject),
            "precedent": items[number - 2]["titre"] if number > 1 else "",
            "suivant": items[number]["titre"] if number < len(items) else ""}


def programme(level: str, subject: str) -> dict[str, Any]:
    """Programme de l'année : chapitres répartis sur 36 semaines en trois trimestres, dans l'ordre."""
    items = chapters(level, subject)
    per = WEEKS / len(items)
    week, terms, start = 1.0, [], 1
    bounds = []
    for name, months, length in TERMS:
        bounds.append((name, months, start, start + length - 1))
        start += length
    for name, months, first, last in bounds:
        terms.append({"nom": name, "mois": months, "semaines": f"{first} à {last}", "chapitres": []})
    for item in items:
        begin = round(week)
        end = max(begin, round(week + per) - 1)
        week += per
        term = next((t for t, (_n, _m, first, last) in zip(terms, bounds, strict=True) if first <= begin <= last),
                    terms[-1])
        term["chapitres"].append({**item, "semaines": f"{begin} à {end}" if end > begin else str(begin)})
    info = _level(level)
    return {"niveau": level, "niveau_nom": info["nom"], "cycle": info.get("cycle", ""), "matiere": subject,
            "matiere_nom": subject_name(subject), "source": _data().get("source", ""), "trimestres": terms,
            "chapitres": len(items)}


SCIENCES = ("monde", "sciences", "svt", "physique_chimie", "ens_scientifique", "technologie")
SIM_SUBJECTS: dict[str, tuple[str, ...]] = {
    "systeme_solaire": SCIENCES, "gaz_parfait": SCIENCES, "fluides": SCIENCES,
    "coeur": ("monde", "sciences", "svt"), "neurone": ("svt", "sciences"),
    "circuit": SCIENCES, "projectile": ("sciences", "physique_chimie"),
    "ondes": ("sciences", "physique_chimie", "ens_scientifique"), "fonctions": ("maths",), "fractions": ("maths",),
}


def suggest_simulations(text: str, subject: str = "") -> list[str]:
    """Simulations intégrées utiles pour un chapitre (mots du titre, matière compatible)."""
    lowered = text.lower()
    return [sim for sim, words in SIM_KEYWORDS.items()
            if (not subject or subject in SIM_SUBJECTS.get(sim, ()))
            and any(re.search(r"(?<!\w)" + re.escape(word) + (r"(?!\w)" if len(word) <= 4 else ""), lowered)
                    for word in words)][:2]
