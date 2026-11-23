"""Module du Hub : le Professeur (programmes de l'Éducation nationale, CP à terminale) et le laboratoire de calcul.

Commandes reçues sur le bus (réponse sur `module.genesis_lab.result`, avec le même `request_id`) :

Professeur (voir `teacher.py`, `curriculum.py`, `sims.py`) :
    niveaux                {}                                         niveaux, matières, nombre de chapitres
    programme              {"niveau", "matiere"}                      année en trois trimestres, état des chapitres
    cours                  {"chapitre", "regenerer"?, "simple"?}      cours prêt, ou travail lancé (rédaction)
    exercices              {"chapitre", "difficulte"}                 nouvelle série (travail)
    corriger               {"chapitre", "reponses": {id: réponse}}    correction + progression (travail)
    remarque               {"chapitre", "genre", "texte"}             remarque gardée, cours réécrit (travail)
    verifier               {"chapitre"}                               relecture par Hermes (travail)
    preparer               {"niveau", "matiere"}                      prépare toute l'année en arrière-plan
    travail                {"cle"}                                    état d'un travail (résultat quand il est fini)
    simulations            {}                                         bibliothèque + demandes au Claude Code local
    creer_simulation       {"sujet", "niveau"?, "details"?, "chapitre"?, "moteur": "local" | "claude"}
    ouvrir_claude          {}                                         ouvre le Claude Code local (nouvelle console)
    supprimer_simulation   {"id"}

Laboratoire (inchangé) :
    compute   {"tool": "chem.molar_mass_g_mol", "args": {"formula": "H2O"}}
    exercise  {"domain": "astro"}  ·  answer {"domain", "level", "seed", "given"}  ·  progress {}

Les rédactions par le modèle local prennent de quelques secondes à plusieurs minutes : elles tournent en
arrière-plan (« travaux ») et le tableau de bord en suit l'état. Seuls les outils de la liste blanche `TOOLS`
peuvent être appelés par `compute`.

Configuration (section `genesis_lab` de `config/local.yaml`), tout est facultatif :

    profile: "data/genesis_lab/eleve.json"   # progression du laboratoire ; son dossier reçoit aussi les cours
    hub_api: "http://127.0.0.1:5750"          # modèle local et base de connaissances, par le Hub
    model: ""                                 # vide = modèle par défaut du Hub
    code_model: ""                            # modèle qui programme les simulations (vide = `model`)
    wikipedia: true                           # sources lues sur fr.wikipedia.org (robots.txt, délai, cache)
    hermes: true                              # « Faire vérifier » par Hermes Agent s'il est installé
    claude_local_dir: ""                      # dossier du Claude Code local (demandes de simulations)
    claude_local_launcher: ""                 # son lanceur (.bat), ouvert d'un clic, jamais lu
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.module_api import Event, Health, Manifest, ModuleBase
from modules.genesis_lab import astro, bio, chem, curriculum
from modules.genesis_lab.sims import BUILTIN, SimError, SimLibrary
from modules.genesis_lab.teacher import Teacher, TeacherError
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


def hub_llm(hub_api: str, model: str = "", timeout_s: float = 300.0, think: bool | None = None,
            num_ctx: int | None = None) -> Callable[[list[dict[str, str]]], str]:
    """Fabrique un appel au modèle local **par le Hub** (API compatible OpenAI), jamais directement.

    `think=False` coupe le raisonnement des modèles qui en ont un (réponse JSON directe, bien plus rapide) ;
    `num_ctx` fixe la taille du contexte (cours avec sources : 16 k)."""
    def call(messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {"model": model or None, "messages": messages}
        if think is not None:
            payload["think"] = think
        if num_ctx:
            payload["num_ctx"] = num_ctx
        request = urllib.request.Request(hub_api.rstrip("/") + "/v1/chat/completions",  # noqa: S310
                                         data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 — API locale du Hub
            data = json.loads(response.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"])
    return call


def relevant(hit: dict[str, Any]) -> bool:
    """Passage assez proche de la question : mêmes seuils que l'assistant du Hub (mesurés le 17/11 : sujets
    couverts 0,70 à 0,81 en vecteurs, hors sujet 0,55 à 0,61). Sans score, le passage est gardé."""
    score = hit.get("score")
    if not isinstance(score, int | float):
        return True
    return float(score) >= (0.65 if hit.get("mode") == "vecteurs" else 0.6)


def hub_search(hub_api: str, k: int = 3, timeout_s: float = 60.0) -> Callable[[str], list[dict[str, str]]]:
    """Recherche de sources dans la base de connaissances **du Hub** (`/knowledge/search`), hors sujet écartés."""
    def search(query: str) -> list[dict[str, str]]:
        url = f"{hub_api.rstrip('/')}/knowledge/search?{urllib.parse.urlencode({'q': query, 'k': k})}"
        with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310 — API locale du Hub
            data = json.loads(response.read().decode("utf-8"))
        return [{"title": str(h.get("title", "")), "url": str(h.get("url", "")), "license": str(h.get("license", "")),
                 "text": str(h.get("text", ""))}
                for h in data.get("hits", []) if isinstance(h, dict) and relevant(h)]
    return search


def _flag(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "non", "no", "off")


class Jobs:
    """Travaux en arrière-plan (rédactions du modèle local), suivis par clé ; un seul à la fois par clé."""

    KEEP_S = 3600

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self.now = now
        self.items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, key: str, label: str, work: Callable[[], Any]) -> dict[str, Any]:
        with self._lock:
            self._prune()
            job = self.items.get(key)
            if job and job["en_cours"]:
                return self.view(key)
            job = {"cle": key, "libelle": label, "en_cours": True, "debut": self.now(), "fin": None,
                   "resultat": None, "erreur": ""}
            self.items[key] = job

        def run() -> None:
            try:
                job["resultat"] = work()
            except Exception as exc:  # noqa: BLE001 — l'erreur est rendue à l'élève, le module continue
                job["erreur"] = str(exc) or type(exc).__name__
            job["fin"] = self.now()
            job["en_cours"] = False

        threading.Thread(target=run, name=f"prof-{key}", daemon=True).start()
        return self.view(key)

    def view(self, key: str) -> dict[str, Any]:
        job = self.items.get(key)
        if job is None:
            raise ValueError("travail inconnu (terminé depuis longtemps ou jamais lancé)")
        return {**job, "duree": round((job["fin"] or self.now()) - job["debut"], 1)}

    def running(self) -> list[dict[str, Any]]:
        return [self.view(k) for k, job in list(self.items.items()) if job["en_cours"]]

    def _prune(self) -> None:
        limit = self.now() - self.KEEP_S
        for key in [k for k, j in self.items.items() if not j["en_cours"] and (j["fin"] or 0) < limit]:
            self.items.pop(key, None)


class GenesisLabModule(ModuleBase):
    """Le Professeur et le laboratoire de calcul, pilotés par le bus."""

    def __init__(self, manifest: Manifest, config: dict[str, Any] | None = None) -> None:
        super().__init__(manifest, config)
        self.tutor: Tutor | None = None
        self.teacher: Teacher | None = None
        self.sims: SimLibrary | None = None
        self.jobs = Jobs()
        self.requests = 0
        self.errors = 0
        self._verifier_ready = False

    def start(self) -> None:
        profile = Path(str(self.config.get("profile") or "data/genesis_lab/eleve.json"))
        data_dir = profile.parent
        llm = search = coder = web = None
        hub = str(self.config.get("hub_api") or "")
        model = str(self.config.get("model") or "")
        if hub:
            llm = hub_llm(hub, model)
            search = hub_search(hub)  # une recherche ratée n'empêche pas la correction
            coder = hub_llm(hub, str(self.config.get("code_model") or model), timeout_s=1800, think=False,
                            num_ctx=16384)
            if _flag(self.config.get("wikipedia")):
                from modules.genesis_lab.sources import wikipedia
                web = wikipedia(data_dir / "web", journal=data_dir / "web" / "journal.jsonl")
        self.tutor = Tutor(profile, llm=llm, search=search)
        writer = hub_llm(hub, model, timeout_s=1800, think=False, num_ctx=16384) if hub else None
        self.teacher = Teacher(data_dir, llm=writer, search=search, web=web)
        claude_dir = str(self.config.get("claude_local_dir") or "")
        launcher = str(self.config.get("claude_local_launcher") or "")
        self.sims = SimLibrary(data_dir, coder=coder, claude_dir=Path(claude_dir) if claude_dir else None,
                               claude_launcher=Path(launcher) if launcher else None)

    def stop(self) -> None:
        self.tutor = self.teacher = self.sims = None

    def health(self) -> Health:
        with_llm = bool(self.teacher and self.teacher.llm)
        busy = len(self.jobs.running())
        return Health(ok=True, degraded=not with_llm,
                      detail=("Professeur avec modèle local" if with_llm else
                              "Professeur sans LLM (cours déjà préparés seulement)")
                             + f" ; {busy} travail(aux) en cours ; {len(TOOLS)} outils de calcul ; "
                               f"{self.requests} demandes, {self.errors} erreurs")

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        self.requests += 1
        try:
            result = self._run(command, payload)
            reply = {"request_id": payload.get("request_id"), "command": command, "ok": True, "result": result}
        except (ValueError, KeyError, TypeError, OSError) as exc:  # demande invalide : erreur rendue, on continue
            self.errors += 1
            reply = {"request_id": payload.get("request_id"), "command": command, "ok": False,
                     "error": f"{type(exc).__name__}: {exc}"}
        self.publish(Event(f"module.{self.name}.result", reply, source=self.name))

    # -- Professeur
    def _verifier(self) -> None:
        """Hermes n'est cherché qu'au premier « Faire vérifier » (le démarrage reste instantané)."""
        if self.teacher is None:
            raise ValueError("module non démarré")
        if not self._verifier_ready and _flag(self.config.get("hermes")):
            from modules.genesis_lab.sources import hermes_verifier
            self.teacher.verifier = hermes_verifier()
        self._verifier_ready = True

    def _lesson_view(self, chapter_id: str) -> dict[str, Any]:
        if self.teacher is None or self.sims is None:
            raise ValueError("module non démarré")
        lesson = self.teacher.lesson(chapter_id)
        created = self.sims.for_chapter(chapter_id)
        lesson["simulations"] = [{"id": s, "titre": BUILTIN.get(s, {}).get("titre", s)}
                                 for s in lesson["chapitre"]["simulations"]]
        lesson["simulations"] += [{"id": s["id"], "titre": s["titre"]} for s in created]
        return lesson

    def _professor(self, command: str, payload: dict[str, Any]) -> Any:
        teacher, sims = self.teacher, self.sims
        if teacher is None or sims is None:
            raise ValueError("module non démarré")
        chapter_id = str(payload.get("chapitre", ""))
        if command == "niveaux":
            return {"niveaux": curriculum.levels(), "modele": bool(teacher.llm)}
        if command == "programme":
            return teacher.overview(str(payload.get("niveau", "")), str(payload.get("matiere", "")))
        if command == "travail":
            job = self.jobs.view(str(payload.get("cle", "")))
            return job
        if command == "cours":
            curriculum.chapter(chapter_id)  # identifiant vérifié tout de suite
            regenerate, simpler = bool(payload.get("regenerer")), bool(payload.get("simple"))
            if teacher.has_lesson(chapter_id) and not regenerate and not simpler:
                return {"pret": True, "cours": self._lesson_view(chapter_id)}

            def write() -> dict[str, Any]:
                teacher.lesson(chapter_id, regenerate=regenerate or simpler, simpler=simpler)
                return self._lesson_view(chapter_id)
            return {"pret": False, "travail": self.jobs.start(f"cours:{chapter_id}", "Rédaction du cours", write)}
        if command == "exercices":
            curriculum.chapter(chapter_id)
            difficulty = int(payload.get("difficulte") or 2)
            return {"travail": self.jobs.start(f"exercices:{chapter_id}", "Nouveaux exercices",
                                               lambda: teacher.more_exercises(chapter_id, difficulty))}
        if command == "corriger":
            curriculum.chapter(chapter_id)
            answers = payload.get("reponses")
            if not isinstance(answers, dict) or not answers:
                raise TeacherError("aucune réponse à corriger")
            return {"travail": self.jobs.start(f"corriger:{chapter_id}", "Correction",
                                               lambda: teacher.grade(chapter_id, answers))}
        if command == "remarque":
            curriculum.chapter(chapter_id)
            kind, text = str(payload.get("genre", "")), str(payload.get("texte", ""))

            def improve() -> dict[str, Any]:
                teacher.feedback(chapter_id, kind, text, rewrite=bool(payload.get("reecrire", True)))
                return self._lesson_view(chapter_id)
            return {"travail": self.jobs.start(f"cours:{chapter_id}", "Amélioration du cours", improve)}
        if command == "verifier":
            curriculum.chapter(chapter_id)
            self._verifier()
            if teacher.verifier is None:
                raise TeacherError("Hermes Agent introuvable sur ce PC : vérification indisponible")
            return {"travail": self.jobs.start(f"verifier:{chapter_id}", "Relecture par Hermes",
                                               lambda: teacher.verify(chapter_id))}
        if command == "preparer":
            if teacher.llm is None:
                raise TeacherError("modèle local indisponible : le Hub doit être joignable")
            return teacher.prepare_all(str(payload.get("niveau", "")), str(payload.get("matiere", "")))
        if command == "simulations":
            return {"simulations": sims.list(), "demandes_claude": sims.collect_claude(),
                    "claude_local": sims.claude_available(),
                    "claude_lanceur": bool(sims.claude_launcher and sims.claude_launcher.is_file()),
                    "modele": bool(sims.coder),
                    "travaux": [j for j in self.jobs.running() if j["cle"].startswith("simulation:")]}
        if command == "creer_simulation":
            subject = str(payload.get("sujet", "")).strip()
            level, details = str(payload.get("niveau", "")), str(payload.get("details", ""))
            if chapter_id:
                curriculum.chapter(chapter_id)
            if str(payload.get("moteur", "local")) == "claude":
                return {"demande": sims.ask_claude(subject, level, details, chapter_id)}
            if not subject:
                raise SimError("sujet vide")
            if sims.coder is None:
                raise SimError("modèle local indisponible (le Hub ne répond pas)")
            return {"travail": self.jobs.start(f"simulation:{subject[:40]}", f"Simulation « {subject[:60]} »",
                                               lambda: sims.generate(subject, level, details, chapter_id))}
        if command == "ouvrir_claude":
            return sims.open_claude()
        if command == "supprimer_simulation":
            return sims.delete(str(payload.get("id", "")))
        raise ValueError(f"commande inconnue : {command!r}")

    def _run(self, command: str, payload: dict[str, Any]) -> Any:
        if command == "compute":
            return compute(str(payload.get("tool", "")), payload.get("args"))
        if self.tutor is None or self.teacher is None:
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
        return self._professor(command, payload)
