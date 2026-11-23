"""Le Professeur : un enseignant pour chaque niveau (CP à terminale) et chaque matière.

Pour un chapitre du programme (`curriculum.py`), il prépare :
- un **cours** adapté à l'âge (objectifs, prérequis, explications, à retenir, exemple corrigé, vocabulaire) ;
- un **schéma** décrit en données (étapes, cycle, frise, courbe, tableau, parties d'un tout), dessiné par le
  tableau de bord : le modèle ne dessine pas, il remplit un gabarit vérifié ici ;
- des **exercices** (QCM, nombre, réponse courte, rédaction) avec corrigé, gardé côté Hub : l'élève ne reçoit
  jamais la réponse avec l'énoncé ;
- les **simulations** utiles (système solaire, cœur, gaz, fluides...) et celles créées à la demande.

Sources : passages de la base de connaissances locale et articles de Wikipédia lus poliment (robots.txt, délai,
liste blanche), cités dans le cours. Correction : QCM et nombres par le code ; réponses courtes comparées, puis
jugées par le modèle si besoin ; rédactions évaluées par le modèle avec le corrigé type sous les yeux.

Amélioration : l'élève (ou le parent) signale « trop difficile », « pas clair », « erreur » ; la remarque est
gardée et le cours est réécrit en en tenant compte. « Faire vérifier » demande à Hermes (recherche web) de relire
les faits du cours ; ses remarques sont gardées avec le cours.

Tout reste sur ce PC : `data/genesis_lab/` (ignoré par Git).
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from modules.genesis_lab import curriculum

Llm = Callable[[list[dict[str, str]]], str]
Search = Callable[[str], list[dict[str, str]]]
Web = Callable[[str], dict[str, str] | None]          # titre d'article -> {"title", "url", "text"} ou None
Verifier = Callable[[str], str]                        # consigne -> réponse de Hermes

SCHEMA_TYPES = ("etapes", "cycle", "frise", "fonction", "comparaison", "parties")
EXERCISE_TYPES = ("qcm", "nombre", "court", "redaction")
MAX_TEXT = 4000
FEEDBACK_KINDS = {"difficile": "trop difficile pour l'élève : simplifier, plus d'exemples concrets",
                  "facile": "trop facile : approfondir, exercices plus exigeants",
                  "pas_clair": "pas clair : reformuler, mieux découper, illustrer",
                  "erreur": "contient une erreur : la corriger (voir la remarque)",
                  "autre": "remarque de l'élève ou du parent"}


class TeacherError(ValueError):
    """Demande invalide ou cours impossible à préparer."""


def style_for(age: int | None) -> str:
    """Consigne de ton et de vocabulaire selon l'âge de l'élève."""
    age = age or 12
    if age <= 7:
        return ("L'élève a 6-7 ans et apprend à lire : phrases très courtes, mots simples, une idée par phrase, "
                "exemples du quotidien (jouets, fruits, animaux). Pas de mot savant sans l'expliquer.")
    if age <= 10:
        return ("L'élève a 8-10 ans : phrases courtes, vocabulaire courant, exemples concrets, une notion à la "
                "fois ; les mots nouveaux sont expliqués.")
    if age <= 14:
        return ("L'élève est au collège : vocabulaire de la matière introduit et défini, exemples concrets, "
                "méthode pas à pas, liens avec la vie courante.")
    return ("L'élève est au lycée : rigueur, vocabulaire disciplinaire, définitions précises, démonstrations ou "
            "argumentations quand c'est utile, méthode attendue au baccalauréat.")


def _clip(value: Any, size: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:size]


def _strings(value: Any, limit: int = 12, size: int = 600) -> list[str]:
    return [_clip(v, size) for v in (value if isinstance(value, list) else []) if _clip(v, size)][:limit]


def parse_json(text: str) -> dict[str, Any]:
    """Premier objet JSON d'une réponse de modèle (blocs ``` et texte autour tolérés)."""
    text = re.sub(r"<think>.*?</think>", "", str(text), flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise TeacherError("réponse du modèle sans objet JSON")
    raw = text[start:end + 1]
    try:
        value = json.loads(raw)
    except ValueError:
        try:
            value = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))   # virgule finale, fréquente
        except ValueError as exc:
            raise TeacherError(f"JSON illisible : {exc}") from exc
    if not isinstance(value, dict):
        raise TeacherError("le JSON attendu est un objet")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    match = re.fullmatch(r"\s*([-+]?\d+(?:[.,]\d+)?)\s*(?:[a-zA-Z%°²³/µ ]*)", str(value or ""))
    return float(match.group(1).replace(",", ".")) if match else None


def normalize(text: Any) -> str:
    """Minuscules, sans accents ni ponctuation, espaces réduits (pour comparer des réponses courtes)."""
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    raw = re.sub(r"\b(le|la|les|l|un|une|des|du|de|d|the|a|an)\b", " ", re.sub(r"[^\w\s]", " ", raw))
    return " ".join(raw.split())


def on_topic(hit: dict[str, Any], query: str) -> bool:
    """Passage de la base locale vraiment lié au chapitre : un mot du chapitre dans son titre, ou deux dans son texte.

    Les vecteurs seuls ne suffisent pas : essai réel du 23/11, « L'électricité, loi d'Ohm » rapprochait
    « Quantité de matière » à 0,70, faute d'article sur l'électricité dans la base."""
    words = {w for w in normalize(query).split() if len(w) >= 4}
    if not words:
        return True
    if words & set(normalize(hit.get("title")).split()):
        return True
    text = set(normalize(hit.get("text")).split())
    return len(words & text) >= 2


def clean_schema(raw: Any) -> dict[str, Any] | None:
    """Schéma vérifié : un type connu et des champs bornés ; sinon rien (le cours s'affiche sans schéma)."""
    if not isinstance(raw, dict) or raw.get("type") not in SCHEMA_TYPES:
        return None
    kind = raw["type"]
    out: dict[str, Any] = {"type": kind, "titre": _clip(raw.get("titre"), 120)}
    if kind in ("etapes", "cycle"):
        out["etapes"] = _strings(raw.get("etapes"), 8, 90)
        return out if len(out["etapes"]) >= 2 else None
    if kind == "frise":
        events = [{"date": _clip(e.get("date"), 30), "texte": _clip(e.get("texte"), 90)}
                  for e in raw.get("evenements") or [] if isinstance(e, dict) and e.get("date") and e.get("texte")]
        out["evenements"] = events[:10]
        return out if len(events) >= 2 else None
    if kind == "fonction":
        expression = _clip(raw.get("expression"), 80).replace("²", "^2").replace("³", "^3")
        if not re.fullmatch(r"(?:sin|cos|tan|exp|ln|sqrt|abs|pi|x|[0-9.,+\-*/^() ])+", expression) \
                or "x" not in expression:
            return None
        xmin, xmax = _number(raw.get("xmin")), _number(raw.get("xmax"))
        xmin = -5.0 if xmin is None else max(-1e4, xmin)
        xmax = 5.0 if xmax is None or xmax <= xmin else min(1e4, xmax)
        out.update(expression=expression, xmin=xmin, xmax=xmax)
        return out
    if kind == "comparaison":
        columns = _strings(raw.get("colonnes"), 5, 60)
        rows = [[_clip(c, 120) for c in row[:len(columns)]] for row in raw.get("lignes") or []
                if isinstance(row, list) and len(row) >= 2][:10]
        out.update(colonnes=columns, lignes=rows)
        return out if len(columns) >= 2 and rows else None
    parts = [{"nom": _clip(p.get("nom"), 50), "role": _clip(p.get("role"), 110)}
             for p in raw.get("parties") or [] if isinstance(p, dict) and p.get("nom")]
    out.update(centre=_clip(raw.get("centre"), 50) or out["titre"], parties=parts[:8])
    return out if len(parts) >= 2 else None


def clean_exercise(raw: Any, ident: str) -> dict[str, Any] | None:
    """Exercice vérifié : type connu, énoncé, réponse cohérente (choix existant, nombre lisible)."""
    if not isinstance(raw, dict) or raw.get("type") not in EXERCISE_TYPES or not _clip(raw.get("enonce")):
        return None
    out: dict[str, Any] = {"id": ident, "type": raw["type"], "enonce": _clip(raw.get("enonce"), 1200),
                           "explication": _clip(raw.get("explication"), 1500),
                           "difficulte": min(3, max(1, int(_number(raw.get("difficulte")) or 1)))}
    if raw["type"] == "qcm":
        choices = _strings(raw.get("choix"), 6, 200)
        answer = raw.get("reponse")
        index = int(answer) if isinstance(answer, int | float) and not isinstance(answer, bool) else None
        if index is None:
            wanted = normalize(answer)
            index = next((i for i, c in enumerate(choices) if normalize(c) == wanted), None)
        if len(choices) < 2 or index is None or not 0 <= index < len(choices):
            return None
        out.update(choix=choices, reponse=index)
    elif raw["type"] == "nombre":
        value = _number(raw.get("reponse"))
        if value is None:
            return None
        tolerance = _number(raw.get("tolerance"))
        out.update(reponse=value, unite=_clip(raw.get("unite"), 20),
                   tolerance=min(0.2, max(0.0, tolerance)) if tolerance is not None else 0.01)
    else:
        out["reponse"] = _clip(raw.get("reponse"), 1500)
        if not out["reponse"]:
            return None
        out["mots_cles"] = _strings(raw.get("mots_cles"), 8, 40)
    return out


def public_exercise(exercise: dict[str, Any]) -> dict[str, Any]:
    """Ce que voit l'élève : jamais la réponse ni l'explication avant la correction."""
    return {k: v for k, v in exercise.items() if k not in ("reponse", "explication", "mots_cles", "tolerance")}


LESSON_FORMAT = """Réponds uniquement par un objet JSON, sans texte autour, de la forme :
{"titre": "...", "objectifs": ["..."], "prerequis": ["..."],
 "sections": [{"titre": "...", "texte": "..."}],
 "a_retenir": ["..."],
 "exemple": {"enonce": "...", "solution": "..."},
 "vocabulaire": [{"mot": "...", "definition": "..."}],
 "schema": <un schéma>,
 "exercices": [<4 à 6 exercices, du plus facile au plus difficile>],
 "pour_aller_plus_loin": "..."}
Un schéma est l'un de :
 {"type": "etapes", "titre": "...", "etapes": ["...", "..."]}            (étapes d'une méthode ou d'un processus)
 {"type": "cycle", "titre": "...", "etapes": ["...", "..."]}             (phénomène qui se répète : cycle de l'eau)
 {"type": "frise", "titre": "...", "evenements": [{"date": "...", "texte": "..."}]}
 {"type": "fonction", "titre": "...", "expression": "x^2 - 2*x", "xmin": -3, "xmax": 5}
 {"type": "comparaison", "titre": "...", "colonnes": ["...", "..."], "lignes": [["...", "..."]]}
 {"type": "parties", "titre": "...", "centre": "...", "parties": [{"nom": "...", "role": "..."}]}
Un exercice est l'un de :
 {"type": "qcm", "enonce": "...", "choix": ["...", "...", "..."], "reponse": <numéro du bon choix, 0 pour le premier>,
  "explication": "...", "difficulte": 1}
 {"type": "nombre", "enonce": "...", "reponse": 12.5, "unite": "cm", "tolerance": 0.01, "explication": "...",
  "difficulte": 2}
 {"type": "court", "enonce": "...", "reponse": "réponse attendue courte", "mots_cles": ["..."], "explication": "...",
  "difficulte": 2}
 {"type": "redaction", "enonce": "...", "reponse": "corrigé type", "explication": "critères de réussite",
  "difficulte": 3}
Les calculs des exercices « nombre » doivent être justes : refais-les avant de répondre."""


class Teacher:
    """Cours, exercices, corrections et progression ; un fichier JSON par chapitre préparé."""

    def __init__(self, data_dir: Path, llm: Llm | None = None, search: Search | None = None,
                 web: Web | None = None, verifier: Verifier | None = None,
                 now: Callable[[], float] = time.time) -> None:
        self.data_dir = Path(data_dir)
        self.llm, self.search, self.web, self.verifier, self.now = llm, search, web, verifier, now
        self._lock = threading.RLock()
        self.preparing: dict[str, Any] = {}

    # -- fichiers
    def _path(self, chapter_id: str) -> Path:
        info = curriculum.chapter(chapter_id)
        return self.data_dir / "cours" / info["niveau"] / info["matiere"] / f"{info['numero']}.json"

    def _load(self, chapter_id: str) -> dict[str, Any] | None:
        path = self._path(chapter_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("lecon") else None

    def _save(self, chapter_id: str, data: dict[str, Any]) -> None:
        path = self._path(chapter_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def _progress_file(self) -> Path:
        return self.data_dir / "progression.json"

    def _progress(self) -> dict[str, Any]:
        try:
            data = json.loads(self._progress_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_progress(self, data: dict[str, Any]) -> None:
        path = self._progress_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # -- sources
    def sources_for(self, info: dict[str, Any]) -> list[dict[str, str]]:
        """Passages de la base locale et articles Wikipédia proposés par le modèle, lus poliment."""
        found: list[dict[str, str]] = []
        query = f"{info['titre']} {info['notions']}".strip()
        if self.search is not None:
            try:
                found += [{**hit, "text": _clip(hit.get("text"), 1500), "origine": "base locale"}
                          for hit in self.search(query) if on_topic(hit, query)][:2]
            except Exception:  # noqa: BLE001, S110 — base absente ou Hub injoignable : cours sans
                pass
        if self.web is not None and self.llm is not None:
            try:
                answer = parse_json(self.llm([
                    {"role": "system", "content": "Tu connais Wikipédia en français. Réponds en JSON seulement."},
                    {"role": "user", "content": "Donne les titres exacts de 2 articles de Wikipédia en français "
                                                f"utiles pour le chapitre « {info['titre']} » ({info['notions']}, "
                                                f"{info['matiere_nom']}, {info['niveau_nom']}). "
                                                'Format : {"articles": ["Titre 1", "Titre 2"]}'}]))
                for title in _strings(answer.get("articles"), 2, 120):
                    page = self.web(title)
                    if page and page.get("text"):
                        found.append({"title": page.get("title") or title, "url": page.get("url", ""),
                                      "license": "CC BY-SA 4.0", "text": _clip(page["text"], 3500),
                                      "origine": "Wikipédia"})
            except Exception:  # noqa: BLE001, S110 — pas de source web : le cours reste possible
                pass
        return found[:4]

    # -- cours
    def lesson(self, chapter_id: str, regenerate: bool = False, simpler: bool = False) -> dict[str, Any]:
        """Cours du chapitre : lu s'il est déjà préparé, sinon rédigé (le modèle local est alors nécessaire)."""
        info = curriculum.chapter(chapter_id)
        with self._lock:
            data = None if regenerate else self._load(chapter_id)
            if data is None:
                data = self._write_lesson(info, self._load(chapter_id), simpler)
        return self._public(info, data)

    def has_lesson(self, chapter_id: str) -> bool:
        return self._load(chapter_id) is not None

    def _write_lesson(self, info: dict[str, Any], previous: dict[str, Any] | None, simpler: bool) -> dict[str, Any]:
        if self.llm is None:
            raise TeacherError("modèle local indisponible : le Hub doit être joignable pour rédiger un cours")
        notes = list((previous or {}).get("notes") or [])
        sources = self.sources_for(info)
        extracts = "\n\n".join(f"[{i + 1}] {s['title']} ({s.get('origine', '')}) :\n{s['text']}"
                               for i, s in enumerate(sources))
        remarks = "\n".join(f"- {FEEDBACK_KINDS.get(n.get('genre'), '')} : {n.get('texte', '')}" for n in notes[-6:])
        prompt = (
            f"Prépare le cours du chapitre « {info['titre']} » pour une classe de {info['niveau_nom']} "
            f"({info['cycle']}), en {info['matiere_nom']}.\n"
            f"Notions du programme : {info['notions'] or info['titre']}.\n"
            + (f"Chapitre précédent : {info['precedent']}.\n" if info["precedent"] else "")
            + (f"Chapitre suivant : {info['suivant']}.\n" if info["suivant"] else "")
            + f"Ton et vocabulaire : {style_for(info.get('age'))}\n"
            + ("Version plus simple demandée : explique autrement, avec plus d'exemples et des étapes plus petites.\n"
               if simpler else "")
            + (f"Remarques à prendre en compte (amélioration du cours) :\n{remarks}\n" if remarks else "")
            + (f"Sources (à utiliser si elles sont pertinentes, sans recopier) :\n{extracts}\n" if extracts else "")
            + "Le cours suit les programmes officiels de l'Éducation nationale. 3 à 5 sections. "
              "Exercices variés (au moins un QCM et un exercice « nombre » si la matière s'y prête), corrigés.\n"
            + LESSON_FORMAT)
        messages = [{"role": "system", "content": "Tu es un professeur de l'Éducation nationale, bienveillant et "
                                                  "précis. Tu écris en français correct."},
                    {"role": "user", "content": prompt}]
        lesson, error = None, ""
        for _attempt in range(2):
            try:
                lesson = self._clean_lesson(parse_json(self.llm(messages)), info)
                break
            except TeacherError as exc:
                error = str(exc)
                messages = [*messages, {"role": "user", "content": f"Réponse refusée ({error}). Recommence : JSON "
                                                                    "valide uniquement, au format demandé."}]
        if lesson is None:
            raise TeacherError(f"cours impossible à préparer : {error}")
        version = int((previous or {}).get("version", 0)) + 1
        data = {"chapitre": info["id"], "version": version, "cree": self.now(), "simple": simpler,
                "lecon": lesson, "sources": [{k: s.get(k, "") for k in ("title", "url", "license", "origine")}
                                             for s in sources],
                "notes": notes, "verification": None, "series": []}
        self._save(info["id"], data)
        return data

    def _clean_lesson(self, raw: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
        sections = [{"titre": _clip(s.get("titre"), 120), "texte": _clip(s.get("texte"))}
                    for s in raw.get("sections") or [] if isinstance(s, dict) and _clip(s.get("texte"))][:8]
        if not sections:
            raise TeacherError("cours sans section")
        exercises = [e for i, item in enumerate(raw.get("exercices") or [])
                     if (e := clean_exercise(item, f"e{i + 1}")) is not None][:8]
        if not exercises:
            raise TeacherError("aucun exercice utilisable")
        example = raw.get("exemple") if isinstance(raw.get("exemple"), dict) else {}
        vocabulary = [{"mot": _clip(v.get("mot"), 60), "definition": _clip(v.get("definition"), 300)}
                      for v in raw.get("vocabulaire") or [] if isinstance(v, dict) and v.get("mot")][:10]
        return {"titre": _clip(raw.get("titre"), 160) or info["titre"], "objectifs": _strings(raw.get("objectifs"), 6),
                "prerequis": _strings(raw.get("prerequis"), 5), "sections": sections,
                "a_retenir": _strings(raw.get("a_retenir"), 8),
                "exemple": {"enonce": _clip(example.get("enonce"), 1200), "solution": _clip(example.get("solution"))},
                "vocabulaire": vocabulary, "schema": clean_schema(raw.get("schema")), "exercices": exercises,
                "pour_aller_plus_loin": _clip(raw.get("pour_aller_plus_loin"), 1200)}

    def _public(self, info: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        lesson = dict(data["lecon"])
        lesson["exercices"] = [public_exercise(e) for e in lesson["exercices"]]
        series = [{"numero": i + 1, "difficulte": s.get("difficulte"),
                   "exercices": [public_exercise(e) for e in s.get("exercices", [])]}
                  for i, s in enumerate(data.get("series") or [])]
        return {"chapitre": info, "version": data.get("version", 1), "cree": data.get("cree"),
                "simple": data.get("simple", False), "lecon": lesson, "series": series,
                "sources": data.get("sources") or [], "notes": data.get("notes") or [],
                "verification": data.get("verification"), "progression": self._progress().get(info["id"])}

    # -- exercices supplémentaires
    def more_exercises(self, chapter_id: str, difficulty: int = 2, count: int = 4) -> dict[str, Any]:
        info = curriculum.chapter(chapter_id)
        if self.llm is None:
            raise TeacherError("modèle local indisponible")
        difficulty = min(3, max(1, int(difficulty)))
        with self._lock:
            data = self._load(chapter_id)
            if data is None:
                raise TeacherError("préparez d'abord le cours de ce chapitre")
            summary = "\n".join(data["lecon"].get("a_retenir") or [s["titre"] for s in data["lecon"]["sections"]])
            seen = "\n".join(e["enonce"][:120] for e in self._all_exercises(data))
            level = {1: "faciles (application directe)", 2: "moyens (deux étapes)",
                     3: "difficiles (problèmes, justification)"}[difficulty]
            prompt = (f"Chapitre « {info['titre']} », {info['niveau_nom']}, {info['matiere_nom']}.\n"
                      f"À retenir du cours :\n{summary}\nTon : {style_for(info.get('age'))}\n"
                      f"Écris {count} nouveaux exercices {level}, différents de ceux-ci :\n{seen}\n"
                      'Réponds uniquement par {"exercices": [...]} avec le format d\'exercice suivant.\n'
                      + LESSON_FORMAT.split("Un exercice est l'un de :", 1)[1])
            raw = parse_json(self.llm([{"role": "system", "content": "Tu es un professeur de l'Éducation nationale."},
                                       {"role": "user", "content": prompt}]))
            number = len(data.get("series") or []) + 2
            exercises = [e for i, item in enumerate(raw.get("exercices") or [])
                         if (e := clean_exercise(item, f"s{number}e{i + 1}")) is not None][:count + 2]
            if not exercises:
                raise TeacherError("le modèle n'a proposé aucun exercice utilisable")
            data.setdefault("series", []).append({"difficulte": difficulty, "exercices": exercises,
                                                  "cree": self.now()})
            self._save(chapter_id, data)
        return {"numero": number - 1, "difficulte": difficulty, "exercices": [public_exercise(e) for e in exercises]}

    @staticmethod
    def _all_exercises(data: dict[str, Any]) -> list[dict[str, Any]]:
        out = list(data["lecon"].get("exercices") or [])
        for serie in data.get("series") or []:
            out += serie.get("exercices") or []
        return out

    # -- correction
    def grade(self, chapter_id: str, answers: dict[str, Any]) -> dict[str, Any]:
        """Corrige les réponses données (`{id d'exercice: réponse}`) et met à jour la progression."""
        info = curriculum.chapter(chapter_id)
        data = self._load(chapter_id)
        if data is None:
            raise TeacherError("cours introuvable : préparez-le d'abord")
        by_id = {e["id"]: e for e in self._all_exercises(data)}
        results, points, total = [], 0.0, 0
        for ident, given in (answers or {}).items():
            exercise = by_id.get(str(ident))
            if exercise is None:
                continue
            score, comment = self._grade_one(exercise, given, info)
            points += score
            total += 1
            expected = exercise["reponse"]
            if exercise["type"] == "qcm":
                expected = exercise["choix"][int(expected)]
            elif exercise["type"] == "nombre":
                expected = f"{expected:g} {exercise.get('unite', '')}".strip()
            results.append({"id": exercise["id"], "score": round(score, 2), "juste": score >= 0.75,
                            "attendu": expected, "explication": exercise.get("explication", ""),
                            "commentaire": comment})
        if not total:
            raise TeacherError("aucune réponse à corriger")
        rate = points / total
        with self._lock:
            progress = self._progress()
            item = progress.setdefault(chapter_id, {"essais": 0, "points": 0.0, "questions": 0, "difficulte": 1})
            item["essais"] += 1
            item["points"] = round(item["points"] + points, 2)
            item["questions"] += total
            item["dernier_taux"] = round(rate, 2)
            item["derniere"] = self.now()
            if rate >= 0.8:
                item["difficulte"] = min(3, item.get("difficulte", 1) + 1)
            elif rate < 0.5:
                item["difficulte"] = max(1, item.get("difficulte", 1) - 1)
            item["statut"] = "acquis" if rate >= 0.8 and item["questions"] >= 4 else (
                "à revoir" if rate < 0.5 else "en cours")
            self._save_progress(progress)
        advice = ("Bravo : chapitre acquis. Passe au suivant, ou essaie des exercices plus difficiles."
                  if rate >= 0.8 else
                  "Relis le cours (ou demande une version plus simple), puis refais des exercices faciles."
                  if rate < 0.5 else "C'est en bonne voie : refais une série du même niveau.")
        return {"resultats": results, "taux": round(rate, 2), "conseil": advice, "progression": item}

    def _grade_one(self, exercise: dict[str, Any], given: Any, info: dict[str, Any]) -> tuple[float, str]:
        kind, expected = exercise["type"], exercise["reponse"]
        if given is None or str(given).strip() == "":
            return 0.0, "pas de réponse"
        if kind == "qcm":
            try:
                return (1.0, "") if int(given) == int(expected) else (0.0, "")
            except (TypeError, ValueError):
                return (1.0, "") if normalize(given) == normalize(exercise["choix"][int(expected)]) else (0.0, "")
        if kind == "nombre":
            value = _number(given)
            if value is None:
                return 0.0, "réponse non numérique"
            margin = abs(float(expected)) * float(exercise.get("tolerance", 0.01)) or 1e-9
            return (1.0, "") if abs(value - float(expected)) <= margin else (0.0, "")
        if kind == "court":
            wanted, got = normalize(expected), normalize(given)
            if got and (got == wanted or (len(wanted) > 3 and wanted in got)):
                return 1.0, ""
            keys = [normalize(k) for k in exercise.get("mots_cles") or [] if normalize(k)]
            if keys and all(k in got for k in keys):
                return 1.0, "mots clés présents"
        return self._judge(exercise, str(given), info)

    def _judge(self, exercise: dict[str, Any], given: str, info: dict[str, Any]) -> tuple[float, str]:
        """Réponse rédigée : évaluée par le modèle, le corrigé type sous les yeux ; sans modèle, auto-évaluation."""
        if self.llm is None:
            return 0.0, "correction automatique indisponible : compare avec le corrigé type"
        prompt = (f"Classe de {info['niveau_nom']}, {info['matiere_nom']}. Évalue la réponse d'un élève.\n"
                  f"Consigne : {exercise['enonce']}\nCorrigé type : {exercise['reponse']}\n"
                  f"Critères : {exercise.get('explication', '')}\nRéponse de l'élève : {given[:3000]}\n"
                  "Sois juste et bienveillant ; une formulation différente mais correcte est juste. "
                  'Réponds uniquement en JSON : {"score": <0 à 1>, "commentaire": "conseil court à l\'élève"}')
        try:
            raw = parse_json(self.llm([{"role": "user", "content": prompt}]))
        except Exception:  # noqa: BLE001 — correction ratée : l'élève compare avec le corrigé
            return 0.0, "correction automatique impossible : compare avec le corrigé type"
        score = _number(raw.get("score"))
        return (min(1.0, max(0.0, score)) if score is not None else 0.0), _clip(raw.get("commentaire"), 600)

    # -- amélioration
    def feedback(self, chapter_id: str, kind: str, text: str = "", rewrite: bool = True) -> dict[str, Any]:
        """Garde une remarque sur le cours ; le réécrit en en tenant compte (par défaut)."""
        if kind not in FEEDBACK_KINDS:
            raise TeacherError(f"remarque inconnue : {kind!r}")
        with self._lock:
            data = self._load(chapter_id)
            if data is None:
                raise TeacherError("cours introuvable")
            data.setdefault("notes", []).append({"genre": kind, "texte": _clip(text, 800), "date": self.now()})
            self._save(chapter_id, data)
            if not rewrite:
                return self._public(curriculum.chapter(chapter_id), data)
            return self.lesson(chapter_id, regenerate=True, simpler=kind == "difficile")

    def verify(self, chapter_id: str) -> dict[str, Any]:
        """Hermes relit les faits du cours (recherche web) ; ses remarques sont gardées avec le cours."""
        if self.verifier is None:
            raise TeacherError("Hermes Agent introuvable sur ce PC (vérification indisponible)")
        info = curriculum.chapter(chapter_id)
        data = self._load(chapter_id)
        if data is None:
            raise TeacherError("cours introuvable")
        lesson = data["lecon"]
        body = "\n".join([*(s["titre"] + " : " + s["texte"] for s in lesson["sections"]), *lesson["a_retenir"]])
        prompt = (f"Tu relis un cours de {info['matiere_nom']} pour une classe de {info['niveau_nom']} "
                  f"(programme de l'Éducation nationale, chapitre « {info['titre']} »). Vérifie les faits, dates, "
                  "définitions et formules avec une recherche web. Réponds en français : d'abord « Verdict : "
                  "correct » ou « Verdict : à corriger », puis la liste des erreurs avec la correction et la source "
                  f"(adresse), et si le contenu est conforme au programme.\n\nCOURS :\n{body[:6000]}")
        answer = _clip(self.verifier(prompt), 6000)
        if not re.search(r"verdict\s*:", answer, re.I):  # pas une relecture : rien n'est gardé
            raise TeacherError("Hermes n'a pas rendu de verdict : " + answer.splitlines()[0][:200] if answer
                               else "Hermes n'a rien répondu")
        ok = bool(re.search(r"verdict\s*:\s*\**\s*correct", answer, re.I))
        with self._lock:
            data = self._load(chapter_id) or data
            data["verification"] = {"date": self.now(), "correct": ok, "texte": answer}
            if not ok:
                data.setdefault("notes", []).append({"genre": "erreur",
                                                     "texte": "Relecture de Hermes : " + answer[:700],
                                                     "date": self.now()})
            self._save(chapter_id, data)
        return data["verification"]

    # -- suivi
    def overview(self, level: str, subject: str) -> dict[str, Any]:
        """Programme de l'année avec, pour chaque chapitre, cours préparé ou non et progression."""
        programme = curriculum.programme(level, subject)
        progress = self._progress()
        for term in programme["trimestres"]:
            for item in term["chapitres"]:
                item["prepare"] = self.has_lesson(item["id"])
                item["progression"] = progress.get(item["id"])
        done = [c for t in programme["trimestres"] for c in t["chapitres"]
                if (c.get("progression") or {}).get("statut") == "acquis"]
        programme["acquis"] = len(done)
        programme["prepares"] = sum(1 for t in programme["trimestres"] for c in t["chapitres"] if c["prepare"])
        programme["preparation"] = self.preparing.get(f"{level}/{subject}")
        return programme

    def prepare_all(self, level: str, subject: str) -> dict[str, Any]:
        """Prépare en arrière-plan tous les cours de l'année qui manquent (un à la fois)."""
        key = f"{level}/{subject}"
        todo = [c["id"] for c in curriculum.chapters(level, subject) if not self.has_lesson(c["id"])]
        state = self.preparing.get(key)
        if state and state.get("en_cours"):
            return state
        state = {"en_cours": bool(todo), "total": len(todo), "faits": 0, "erreurs": [], "debut": self.now()}
        self.preparing[key] = state

        def run() -> None:
            for chapter_id in todo:
                try:
                    self.lesson(chapter_id)
                    state["faits"] += 1
                except Exception as exc:  # noqa: BLE001 — un chapitre raté n'arrête pas les autres
                    state["erreurs"].append(f"{chapter_id} : {exc}")
            state["en_cours"] = False

        if todo:
            threading.Thread(target=run, name=f"prof-{key}", daemon=True).start()
        return state
