"""Professeur Personnel Adaptatif.

Principe : **le code calcule, le LLM explique.**
- Les exercices et leurs réponses sont produits par les fonctions déterministes de `bio`, `astro`, `chem`.
- La correction (juste / faux) est décidée par le code, avec une tolérance numérique.
- Le LLM local, s'il est disponible, ne sert qu'à formuler l'explication au niveau de l'élève ; il reçoit
  la réponse déjà calculée et ne peut pas la changer. Sans LLM, une explication type est donnée.
- Garde-fou : une explication qui contient un nombre que le code n'a pas fourni est rejetée (le modèle a
  tendance à inventer des calculs intermédiaires faux). Une seconde chance, puis l'explication type.
- Les sources (base de connaissances locale, recherche web polie) sont citées quand elles existent.

La progression est mémorisée dans un fichier JSON local, propre à chaque élève.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from modules.genesis_lab import astro, bio, chem

DOMAINS = {"bio": "génétique et bio-informatique", "astro": "astrophysique", "chem": "génie chimique"}
LEVELS = {1: "débutant", 2: "intermédiaire", 3: "avancé"}
VOCABULARY = {
    1: "Explique avec des mots simples, sans jargon, avec une image de la vie courante. Trois phrases au plus.",
    2: "Explique avec le vocabulaire du lycée et rappelle la formule utilisée. Quatre phrases au plus.",
    3: "Explique de façon rigoureuse, avec la formule, ses hypothèses et ses limites. Cinq phrases au plus.",
}
PROMOTE_AFTER = 2  # réussites consécutives pour monter d'un niveau
DEMOTE_AFTER = 2  # échecs consécutifs pour descendre d'un niveau

Llm = Callable[[list[dict[str, str]]], str]
Search = Callable[[str], list[dict[str, str]]]


@dataclass(frozen=True)
class Exercise:
    id: str
    domain: str
    level: int
    question: str
    answer: float | str
    unit: str = ""
    tolerance: float = 0.01  # tolérance relative pour une réponse numérique
    method: str = ""  # la formule ou la démarche, calculée ici, donnée au LLM pour l'explication
    topic: str = ""  # mots-clés pour la recherche de sources

    def to_dict(self, with_answer: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not with_answer:
            for key in ("answer", "method"):
                data.pop(key)
        return data


# --------------------------------------------------------------------------- générateurs d'exercices
def _sequence(rng: random.Random, length: int) -> str:
    return "".join(rng.choice("ACGT") for _ in range(length))


def _bio(level: int, rng: random.Random) -> Exercise:
    if level == 1:
        seq = _sequence(rng, 12)
        return Exercise("bio-gc", "bio", 1, f"Quel est le pourcentage de bases G et C dans la séquence {seq} ?",
                        round(bio.gc_percent(seq), 2), "%", 0.01,
                        f"On compte les G et les C ({seq.count('G') + seq.count('C')}) et on divise par le nombre "
                        f"de bases ({len(seq)}).", "pourcentage GC ADN")
    if level == 2:
        codons = [rng.choice([c for c, a in bio.CODON_TABLE.items() if a != "*"]) for _ in range(4)]
        seq = "ATG" + "".join(codons) + rng.choice(bio.STOPS)
        return Exercise("bio-translate", "bio", 2,
                        f"Traduis cette séquence codante en protéine (code à une lettre, sans le stop) : {seq}",
                        bio.translate(seq, to_stop=True), "", 0.0,
                        "On lit la séquence par groupes de trois bases (codons) depuis ATG, jusqu'au codon stop.",
                        "code génétique traduction codon")
    seq = _sequence(rng, 15)
    return Exercise("bio-revcomp", "bio", 3, f"Donne le brin complémentaire inverse (5' vers 3') de {seq}.",
                    bio.reverse_complement(seq), "", 0.0,
                    "On remplace A par T, T par A, C par G, G par C, puis on lit la séquence à l'envers.",
                    "brin complémentaire inverse ADN")


def _astro(level: int, rng: random.Random) -> Exercise:
    if level == 1:
        distance = rng.choice([1.3, 2.6, 4.2, 8.6, 10.0, 25.0])
        return Exercise("astro-pc-ly", "astro", 1, f"Une étoile est à {distance} parsecs. Combien d'années-lumière ?",
                        round(astro.pc_to_ly(distance), 3), "années-lumière", 0.01,
                        "Un parsec vaut environ 3,26 années-lumière : on multiplie.",
                        "parsec année-lumière conversion")
    if level == 2:
        axis = rng.choice([0.39, 0.72, 1.52, 5.2, 9.58])
        days = astro.seconds_to_days(astro.orbital_period_s(astro.au_to_m(axis)))
        return Exercise("astro-kepler", "astro", 2,
                        f"Une planète tourne autour du Soleil à {axis} unités astronomiques. "
                        "Quelle est sa période de révolution, en jours ?", round(days, 1), "jours", 0.01,
                        "Troisième loi de Kepler : T = 2π √(a³ / GM). En années et en unités astronomiques, T² = a³.",
                        "troisième loi de Kepler période orbitale")
    magnitude, distance = rng.choice([(-1.46, 2.64), (0.03, 7.68), (1.25, 430.0), (4.83, 10.0)])
    return Exercise("astro-magnitude", "astro", 3,
                    f"Une étoile de magnitude apparente {magnitude} est à {distance} parsecs. "
                    "Quelle est sa magnitude absolue ?", round(astro.absolute_magnitude(magnitude, distance), 2), "",
                    0.02, "M = m − 5 log10(d / 10 pc) : c'est la magnitude qu'aurait l'étoile à 10 parsecs.",
                    "magnitude absolue module de distance")


def _chem(level: int, rng: random.Random) -> Exercise:
    if level == 1:
        formula = rng.choice(["H2O", "CO2", "NaCl", "CH4", "NH3", "O2"])
        return Exercise("chem-molar-mass", "chem", 1, f"Quelle est la masse molaire de {formula}, en g/mol ?",
                        round(chem.molar_mass_g_mol(formula), 3), "g/mol", 0.01,
                        "On additionne les masses atomiques de chaque atome de la formule.", "masse molaire")
    if level == 2:
        formula, mass = rng.choice(["C6H12O6", "CaCO3", "H2SO4", "NaOH"]), rng.choice([10.0, 25.0, 50.0, 100.0])
        return Exercise("chem-moles", "chem", 2, f"Combien de moles y a-t-il dans {mass} g de {formula} ?",
                        round(chem.moles_from_mass(mass, formula), 4), "mol", 0.01,
                        f"n = m / M, avec M = {chem.molar_mass_g_mol(formula):.3f} g/mol.", "quantité de matière mole")
    concentration, ka = rng.choice([0.1, 0.05, 0.01]), 1.8e-5
    return Exercise("chem-weak-acid", "chem", 3,
                    f"Quel est le pH d'une solution d'acide acétique à {concentration} mol/L (Ka = 1,8 × 10⁻⁵) ?",
                    round(chem.ph_weak_acid(concentration, ka), 2), "", 0.01,
                    "On résout Ka = x² / (C − x) pour x = [H₃O⁺], puis pH = −log10(x).", "pH acide faible Ka")


GENERATORS = {"bio": _bio, "astro": _astro, "chem": _chem}


def make_exercise(domain: str, level: int, seed: int) -> Exercise:
    """Exercice reproductible : mêmes domaine, niveau et graine → même exercice."""
    if domain not in GENERATORS:
        raise ValueError(f"domaine inconnu : {domain!r} (attendu : {', '.join(GENERATORS)})")
    level = max(1, min(3, int(level)))
    return GENERATORS[domain](level, random.Random(f"{domain}:{level}:{seed}"))  # noqa: S311 — pas un usage cryptographique


def check_answer(exercise: Exercise, given: Any) -> bool:
    """Décide si la réponse est juste. Nombre : tolérance relative. Texte : comparaison sans casse ni espaces."""
    if isinstance(exercise.answer, str):
        return str(given).strip().replace(" ", "").upper() == exercise.answer.upper()
    try:
        value = float(str(given).replace(",", ".").replace("%", "").strip())
    except ValueError:
        return False
    scale = max(abs(exercise.answer), 1e-12)
    return abs(value - exercise.answer) <= exercise.tolerance * scale + 1e-9


# --------------------------------------------------------------------------- profil de l'élève
@dataclass
class LearnerProfile:
    learner: str = "élève"
    levels: dict[str, int] = field(default_factory=dict)
    streaks: dict[str, int] = field(default_factory=dict)  # positif : réussites d'affilée ; négatif : échecs
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> LearnerProfile:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(str(raw.get("learner", "élève")), dict(raw.get("levels", {})), dict(raw.get("streaks", {})),
                       list(raw.get("history", [])))
        except (OSError, ValueError, AttributeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


class Tutor:
    """Évalue le niveau, propose des exercices, corrige, explique et mémorise la progression."""

    def __init__(self, profile_path: Path, llm: Llm | None = None, search: Search | None = None, seed: int = 0,
                 now: Callable[[], float] = time.time) -> None:
        self.profile_path = profile_path
        self.profile = LearnerProfile.load(profile_path)
        self.llm, self.search, self.seed, self._now = llm, search, seed, now

    # -- évaluation du niveau
    def placement_questions(self, domain: str) -> list[Exercise]:
        """Trois questions de difficulté croissante pour situer l'élève."""
        return [make_exercise(domain, level, self.seed) for level in (1, 2, 3)]

    def submit_placement(self, domain: str, answers: list[Any]) -> int:
        """Niveau retenu = nombre de bonnes réponses consécutives depuis la plus facile (au moins 1)."""
        level = 1
        for exercise, given in zip(self.placement_questions(domain), answers, strict=False):
            if not check_answer(exercise, given):
                break
            level = exercise.level
        self.profile.levels[domain] = level
        self.profile.streaks[domain] = 0
        self.profile.save(self.profile_path)
        return level

    def level(self, domain: str) -> int:
        return int(self.profile.levels.get(domain, 1))

    # -- exercices
    def next_exercise(self, domain: str) -> Exercise:
        done = sum(1 for item in self.profile.history if item["domain"] == domain)
        return make_exercise(domain, self.level(domain), self.seed + 1 + done)

    def answer(self, exercise: Exercise, given: Any) -> dict[str, Any]:
        """Corrige une réponse, adapte le niveau, mémorise, et rend l'explication avec ses sources."""
        correct = check_answer(exercise, given)
        before = self.level(exercise.domain)
        streak = self.profile.streaks.get(exercise.domain, 0)
        streak = (max(streak, 0) + 1) if correct else (min(streak, 0) - 1)
        after = before
        if streak >= PROMOTE_AFTER and before < 3:
            after, streak = before + 1, 0
        elif streak <= -DEMOTE_AFTER and before > 1:
            after, streak = before - 1, 0
        self.profile.levels[exercise.domain], self.profile.streaks[exercise.domain] = after, streak
        self.profile.history.append({"ts": int(self._now()), "domain": exercise.domain, "level": exercise.level,
                                     "exercise": exercise.id, "correct": correct})
        self.profile.save(self.profile_path)
        sources = self._sources(exercise)
        return {"correct": correct, "expected": exercise.answer, "unit": exercise.unit, "level_before": before,
                "level_after": after, "explanation": self._explain(exercise, given, correct, before),
                "sources": sources}

    def progress(self) -> dict[str, Any]:
        summary = {}
        for domain in DOMAINS:
            items = [item for item in self.profile.history if item["domain"] == domain]
            summary[domain] = {"level": self.level(domain), "level_name": LEVELS[self.level(domain)],
                               "done": len(items), "correct": sum(1 for item in items if item["correct"])}
        return summary

    # -- explication et sources
    def _sources(self, exercise: Exercise) -> list[dict[str, str]]:
        if self.search is None:
            return []
        try:
            found = self.search(exercise.topic)
        except Exception:  # noqa: BLE001 — une recherche ratée ne doit pas empêcher la correction
            return []
        sources: list[dict[str, str]] = []
        for s in found:  # une page citée une seule fois, trois au plus
            if s.get("url") and all(str(s["url"]) != known["url"] for known in sources):
                sources.append({"title": str(s.get("title", "")), "url": str(s["url"])})
            if len(sources) == 3:
                break
        return sources

    def _explain(self, exercise: Exercise, given: Any, correct: bool, level: int) -> str:
        expected = f"{exercise.answer} {exercise.unit}".strip()
        verdict = "La réponse est juste." if correct else f"La réponse attendue est {expected}."
        fallback = f"{verdict} {exercise.method}"
        if self.llm is None:
            return fallback
        prompt = (
            f"Tu es un professeur bienveillant de {DOMAINS[exercise.domain]}. Niveau de l'élève : {LEVELS[level]}.\n"
            f"{VOCABULARY[level]}\n\n"
            f"Question : {exercise.question}\nRéponse de l'élève : {given}\n"
            f"Réponse exacte, calculée par le programme (ne la recalcule pas, ne la modifie pas) : {expected}\n"
            f"Démarche : {exercise.method}\n"
            + ("L'élève a réussi : félicite-le brièvement. " if correct else
               "L'élève s'est trompé : ne le félicite pas pour sa réponse et ne dis pas qu'elle est juste ; "
               "montre sans reproche où est l'erreur probable. ")
            + "Explique la démarche, encourage, et ne donne aucun autre nombre que ceux fournis ci-dessus."
        )
        allowed = numbers_in(f"{exercise.question} {expected} {exercise.method} {given}")
        messages = [{"role": "user", "content": prompt}]
        text = ""
        for _attempt in range(2):
            try:
                text = self.llm(messages).strip()
            except Exception:  # noqa: BLE001 — LLM indisponible : on donne l'explication type
                return fallback
            invented = foreign_numbers(text, allowed)
            if not invented:
                break
            # Le modèle a écrit un nombre que le code n'a pas fourni (calcul intermédiaire de son cru, souvent
            # faux) : on le lui signale une fois, puis on renonce à son texte.
            messages = [*messages, {"role": "assistant", "content": text}, {"role": "user", "content": (
                f"Ton texte contient des nombres que je ne t'ai pas donnés ({', '.join(invented[:5])}). "
                "Réécris l'explication sans aucun calcul intermédiaire, avec les seuls nombres fournis.")}]
        else:
            return fallback
        # garde-fou : la valeur calculée par le code figure toujours dans la correction affichée
        if isinstance(exercise.answer, str):
            shown = exercise.answer in text
        else:  # « 89,0 » dans le texte vaut « 89.0 »
            shown = not foreign_numbers(str(exercise.answer), numbers_in(text))
        return text if shown else f"{text}\n\n{verdict}"


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
SMALL_INTEGER_MAX = 10  # exposants, rangs (« 3ᵉ loi »), « 2 fois » : toujours admis


def numbers_in(text: str) -> list[float]:
    """Nombres écrits dans un texte (virgule ou point décimal)."""
    return [float(match.replace(",", ".")) for match in _NUMBER.findall(text)]


def foreign_numbers(text: str, allowed: list[float], tolerance: float = 0.005) -> list[str]:
    """Nombres du texte absents de la liste admise (à 0,5 % près). Les petits entiers sont toujours admis."""
    foreign = []
    for raw in _NUMBER.findall(text):
        value = float(raw.replace(",", "."))
        if value == int(value) and value <= SMALL_INTEGER_MAX and "." not in raw and "," not in raw:
            continue
        if not any(abs(value - ok) <= tolerance * max(abs(ok), 1e-9) for ok in allowed):
            foreign.append(raw)
    return foreign
