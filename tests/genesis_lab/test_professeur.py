"""Le Professeur : programmes, cours, exercices corrigés, améliorations, simulations, sources, commandes du module.

Le modèle local, le web et Hermes sont remplacés par des doublures : aucun réseau, tout est écrit dans `tmp_path`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from modules.genesis_lab import curriculum
from modules.genesis_lab.sims import BUILTIN, BUILTIN_DIR, SimError, SimLibrary, extract_html, validate_html
from modules.genesis_lab.sources import hermes_verifier, wikipedia
from modules.genesis_lab.teacher import Teacher, TeacherError, clean_exercise, clean_schema, parse_json, public_exercise

CHAPTER = "4e/physique_chimie/5"

LESSON = {
    "titre": "Un cours", "objectifs": ["comprendre"], "prerequis": ["lire"],
    "sections": [{"titre": "Partie 1", "texte": "Explication."}, {"titre": "Partie 2", "texte": "Suite."}],
    "a_retenir": ["Point clé"], "exemple": {"enonce": "Énoncé", "solution": "Solution"},
    "vocabulaire": [{"mot": "atome", "definition": "constituant de la matière"}],
    "schema": {"type": "etapes", "titre": "Méthode", "etapes": ["lire", "calculer", "conclure"]},
    "exercices": [
        {"type": "qcm", "enonce": "Combien font 2 + 2 ?", "choix": ["3", "4", "5"], "reponse": 1,
         "explication": "2 + 2 = 4"},
        {"type": "nombre", "enonce": "Masse de 2 L d'eau (kg) ?", "reponse": 2, "unite": "kg",
         "explication": "1 L = 1 kg"},
        {"type": "court", "enonce": "Symbole de l'oxygène ?", "reponse": "O", "mots_cles": ["O"], "explication": "O"},
        {"type": "redaction", "enonce": "Explique la combustion.", "reponse": "Réaction avec le dioxygène.",
         "explication": "citer le dioxygène", "difficulte": 3},
        {"type": "qcm", "enonce": "Exercice cassé", "choix": ["a"], "reponse": 3},  # rejeté : un seul choix
    ],
    "pour_aller_plus_loin": "Lire plus.",
}


class FakeLlm:
    """Rend les réponses dans l'ordre ; garde les messages reçus."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def teacher(tmp_path: Path, *answers: str, **kw: Any) -> Teacher:
    return Teacher(tmp_path, llm=FakeLlm(*(answers or (json.dumps(LESSON),))), **kw)


# -- programmes
def test_programmes_cover_every_level_and_subject() -> None:
    levels = curriculum.levels()
    assert [n["id"] for n in levels] == ["cp", "ce1", "ce2", "cm1", "cm2", "6e", "5e", "4e", "3e", "2nde", "1re", "tle"]
    for level in levels:
        subjects = {m["id"] for m in level["matieres"]}
        assert "maths" in subjects and ("philosophie" if level["id"] == "tle" else "francais") in subjects
        for subject in level["matieres"]:
            programme = curriculum.programme(level["id"], subject["id"])
            items = [c for t in programme["trimestres"] for c in t["chapitres"]]
            assert len(items) == subject["chapitres"] >= 3
            assert [c["numero"] for c in items] == list(range(1, len(items) + 1))  # ordre gardé, rien de perdu
            assert len(programme["trimestres"]) == 3


def test_chapter_context_and_invalid_ids() -> None:
    info = curriculum.chapter("3e/maths/2")
    assert info["niveau_nom"] and info["matiere_nom"] == "Mathématiques" and info["precedent"] and info["suivant"]
    for bad in ("3e/maths/0", "3e/maths/99", "3e/latin/1", "../maths/1", "zz/maths/1", "3e/maths"):
        with pytest.raises(curriculum.CurriculumError):
            curriculum.chapter(bad)


def test_simulations_are_suggested_by_whole_words_and_subject() -> None:
    assert curriculum.suggest_simulations("Le système solaire", "physique_chimie") == ["systeme_solaire"]
    assert "gaz_parfait" not in curriculum.suggest_simulations("Le système solaire", "physique_chimie")  # « air »
    assert curriculum.suggest_simulations("Ce sont des fractions", "maths") == ["fractions"]  # « son » ≠ « sont »
    assert curriculum.suggest_simulations("Le cœur et la circulation", "francais") == []
    found = {s for c in curriculum.chapters("4e", "physique_chimie") for s in c["simulations"]}
    assert found and found <= set(BUILTIN)


# -- cours
def test_lesson_is_written_once_and_never_shows_answers(tmp_path: Path) -> None:
    prof = teacher(tmp_path)
    lesson = prof.lesson(CHAPTER)
    exercises = lesson["lecon"]["exercices"]
    assert len(exercises) == 4  # l'exercice cassé est écarté
    assert all("reponse" not in e and "explication" not in e for e in exercises)
    assert lesson["lecon"]["schema"]["type"] == "etapes"
    assert prof.lesson(CHAPTER)["version"] == 1 and len(prof.llm.calls) == 1  # relu, pas réécrit
    assert (tmp_path / "cours" / "4e" / "physique_chimie" / "5.json").is_file()
    prompt = prof.llm.calls[0][1]["content"]
    assert "4e" in prompt and "Éducation nationale" in prompt and "collège" in prompt


def test_lesson_needs_a_model_and_retries_bad_json(tmp_path: Path) -> None:
    with pytest.raises(TeacherError):
        Teacher(tmp_path).lesson(CHAPTER)
    prof = teacher(tmp_path, "pas de JSON ici", json.dumps(LESSON))
    assert prof.lesson(CHAPTER)["lecon"]["titre"] == "Un cours"
    assert "Réponse refusée" in prof.llm.calls[1][-1]["content"]
    with pytest.raises(TeacherError):
        teacher(tmp_path / "b", json.dumps({**LESSON, "exercices": []})).lesson(CHAPTER)


def test_grading_by_code_and_by_model_updates_progress(tmp_path: Path) -> None:
    prof = teacher(tmp_path, json.dumps(LESSON))
    prof.lesson(CHAPTER)
    prof.llm.answers = ['{"score": 0.9, "commentaire": "Bien vu"}']
    result = prof.grade(CHAPTER, {"e1": 1, "e2": "2,0 kg", "e3": " o ",
                                  "e4": "Le combustible réagit avec le dioxygène"})
    by_id = {r["id"]: r for r in result["resultats"]}
    assert all(r["juste"] for r in by_id.values()) and by_id["e4"]["commentaire"] == "Bien vu"
    assert by_id["e1"]["attendu"] == "4" and by_id["e2"]["attendu"] == "2 kg"
    assert result["progression"]["statut"] == "acquis" and result["progression"]["difficulte"] == 2
    prof.llm.answers = ['{"score": 0, "commentaire": "Non"}']
    wrong = prof.grade(CHAPTER, {"e1": 0, "e2": "3", "e3": "N"})
    assert wrong["taux"] == 0 and wrong["progression"]["statut"] == "à revoir"
    assert prof.overview("4e", "physique_chimie")["prepares"] == 1
    with pytest.raises(TeacherError):
        prof.grade(CHAPTER, {"inconnu": 1})


def test_feedback_is_kept_and_used_to_rewrite(tmp_path: Path) -> None:
    prof = teacher(tmp_path)
    prof.lesson(CHAPTER)
    rewritten = prof.feedback(CHAPTER, "difficile", "trop de mots savants")
    assert rewritten["version"] == 2 and rewritten["simple"] and rewritten["notes"][0]["genre"] == "difficile"
    assert "trop de mots savants" in prof.llm.calls[-1][1]["content"]
    with pytest.raises(TeacherError):
        prof.feedback(CHAPTER, "inconnu")


def test_more_exercises_and_hermes_verification(tmp_path: Path) -> None:
    verdicts: list[str] = []
    prof = teacher(tmp_path,
                   verifier=lambda prompt: verdicts.append(prompt) or "Verdict : à corriger. 2 + 2 = 4, pas 5.")
    prof.lesson(CHAPTER)
    prof.llm.answers = [json.dumps({"exercices": [LESSON["exercices"][0], LESSON["exercices"][1]]})]
    serie = prof.more_exercises(CHAPTER, difficulty=3)
    assert serie["difficulte"] == 3 and [e["id"] for e in serie["exercices"]] == ["s2e1", "s2e2"]
    assert prof.grade(CHAPTER, {"s2e1": 1})["taux"] == 1
    check = prof.verify(CHAPTER)
    assert check["correct"] is False and "Explication." in verdicts[0]
    assert prof.lesson(CHAPTER)["notes"][-1]["genre"] == "erreur"
    with pytest.raises(TeacherError):
        Teacher(tmp_path / "x").verify(CHAPTER)


def test_sources_come_from_local_base_and_wikipedia(tmp_path: Path) -> None:
    pages = {"Combustion": {"title": "Combustion", "url": "https://fr.wikipedia.org/wiki/Combustion",
                            "text": "x" * 500}}
    prof = teacher(tmp_path, '{"articles": ["Combustion", "Inexistant"]}', json.dumps(LESSON),
                   search=lambda q: [{"title": "Quantité de matière", "url": "", "text": "mole et masse molaire"},
                                     {"title": "Tension électrique", "url": "", "text": "passage"}],
                   web=lambda t: pages.get(t))
    lesson = prof.lesson(CHAPTER)
    assert [s["title"] for s in lesson["sources"]] == ["Tension électrique", "Combustion"]  # hors sujet écarté
    assert [s["origine"] for s in lesson["sources"]] == ["base locale", "Wikipédia"]
    assert "CC BY-SA" in lesson["sources"][1]["license"]
    assert "[2] Combustion" in prof.llm.calls[1][1]["content"]


def test_local_passages_must_share_words_with_the_chapter() -> None:
    from modules.genesis_lab.teacher import on_topic

    ohm = "L'électricité tension, intensité, loi d'Ohm"
    assert not on_topic({"title": "Quantité de matière", "text": "La mole, unité de quantité de matière"}, ohm)
    assert on_topic({"title": "Potentiel hydrogène", "text": "Un acide fort, une base faible"}, "Acide-base, pH")
    assert on_topic({"title": "Tension électrique", "text": ""}, ohm)


def test_schema_and_exercise_cleaning() -> None:
    curve = clean_schema({"type": "fonction", "expression": "x² - 2*x", "xmin": -2, "xmax": 4})
    assert curve and curve["expression"] == "x^2 - 2*x"
    assert clean_schema({"type": "fonction", "expression": "__import__('os')"}) is None
    assert clean_schema({"type": "inconnu"}) is None
    assert clean_schema({"type": "cycle", "etapes": ["seul"]}) is None
    assert clean_exercise({"type": "qcm", "enonce": "?", "choix": ["a", "b"], "reponse": "b"}, "e1")["reponse"] == 1
    assert clean_exercise({"type": "nombre", "enonce": "?", "reponse": "douze"}, "e1") is None
    assert "reponse" not in public_exercise({"id": "e1", "reponse": 3, "explication": "…"})
    assert parse_json('<think>…</think> ```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}


# -- simulations
def test_builtin_simulations_pass_the_checks() -> None:
    assert len(BUILTIN) == 10
    for sim in BUILTIN:
        html = (BUILTIN_DIR / f"{sim}.html").read_text(encoding="utf-8")
        assert validate_html(html) and 'lang="fr"' in html


@pytest.mark.parametrize("bad", [
    '<script>fetch("/health")</script>', '<script src="x.js"></script>', '<iframe src="/"></iframe>',
    '<script>new WebSocket("ws://x")</script>', '<script>eval("1")</script>', '<img src="https://evil.example/x.png">',
    '<script>localStorage.x = 1</script>', '<script>import("./m.js")</script>', '<script>location.href = "/"</script>',
])
def test_unsafe_pages_are_refused(bad: str) -> None:
    with pytest.raises(SimError):
        validate_html(f"<!doctype html><html><body><canvas></canvas><script>1</script>{bad}</body></html>")


def test_page_checks_size_and_drawing() -> None:
    with pytest.raises(SimError):
        validate_html("<!doctype html><html><script>1</script><p>pas de dessin</p></html>")
    with pytest.raises(SimError):
        validate_html("<!doctype html><html><canvas></canvas><script>" + "x" * 400_000 + "</script></html>")
    ok = validate_html('<!doctype html><html><script>document.createElementNS("http://www.w3.org/2000/svg","svg")</script></html>')
    assert ok
    assert extract_html("Voici :\n```html\n<!doctype html><html>a</html>\n```\nFin") == "<!doctype html><html>a</html>"


GOOD_PAGE = '<!doctype html><html lang="fr"><body><canvas id="c"></canvas><script>let t = 0;</script></body></html>'


def test_local_model_writes_a_simulation_after_one_correction(tmp_path: Path) -> None:
    coder = FakeLlm('<!doctype html><html><canvas></canvas><script>fetch("x")</script></html>',
                    f"```html\n{GOOD_PAGE}\n```")
    library = SimLibrary(tmp_path, coder=coder)
    sim = library.generate("La photosynthèse", "5e", "lumière et CO2", chapter=CHAPTER)
    assert sim["id"] == "la_photosynthese" and sim["origine"] == "modèle local"
    assert "accès réseau" in coder.calls[1][-1]["content"]
    assert library.path("la_photosynthese").read_text(encoding="utf-8") == GOOD_PAGE
    assert [s["id"] for s in library.for_chapter(CHAPTER)] == ["la_photosynthese"]
    assert library.generate("La photosynthèse")["id"] == "la_photosynthese_2"
    library.delete("la_photosynthese")
    with pytest.raises(SimError):
        library.delete("coeur")
    with pytest.raises(SimError):
        SimLibrary(tmp_path, coder=FakeLlm("rien")).generate("Les volcans")


def test_feedback_rounds_improve_a_simulation_and_can_be_undone(tmp_path: Path) -> None:
    v2 = GOOD_PAGE.replace("let t = 0", "let t = 2")
    v3 = GOOD_PAGE.replace("let t = 0", "let t = 3")
    coder = FakeLlm(GOOD_PAGE, f"```html\n{v2}\n```", "<html>sans dessin</html>", v3)
    reviewer = FakeLlm("<think>…</think>1. La nouvelle lune doit être entre la Terre et le Soleil.")
    library = SimLibrary(tmp_path, coder=coder, reviewer=reviewer)
    sim_id = library.generate("Les phases de la Lune", "CM2")["id"]
    review = library.review(sim_id)
    assert review["retour"].startswith("1. La nouvelle lune") and review["rien"] is False
    assert GOOD_PAGE in reviewer.calls[0][-1]["content"]  # le Professeur lit le code
    with pytest.raises(SimError, match="vide"):
        library.improve(sim_id, "  ")
    assert library.improve(sim_id, "Nouvelle lune mal placée")["version"] == 2
    assert library.path(sim_id).read_text(encoding="utf-8") == v2
    assert GOOD_PAGE in coder.calls[1][-1]["content"]  # le codeur reçoit la page actuelle et le retour
    third = library.improve(sim_id, "Le curseur ne fait rien")  # un refus, puis une page acceptable
    assert third["version"] == 3 and "ni canvas ni SVG" in coder.calls[3][-1]["content"]
    assert "Nouvelle lune mal placée" in coder.calls[2][1]["content"]  # les retours précédents sont rappelés
    listed = next(s for s in library.list() if s["id"] == sim_id)
    assert listed["version"] == 3 and listed["retours"] == ["Nouvelle lune mal placée", "Le curseur ne fait rien"]
    assert library.undo(sim_id)["version"] == 2
    assert library.path(sim_id).read_text(encoding="utf-8") == v2
    library.undo(sim_id)
    with pytest.raises(SimError, match="précédente"):
        library.undo(sim_id)
    library.delete(sim_id)
    assert not list((tmp_path / "simulations" / "versions").glob("*"))


def test_a_builtin_simulation_is_never_overwritten(tmp_path: Path) -> None:
    from modules.genesis_lab.sims import BUILTIN_DIR
    before = (BUILTIN_DIR / "systeme_solaire.html").read_bytes()
    library = SimLibrary(tmp_path, coder=FakeLlm(GOOD_PAGE), reviewer=FakeLlm("Rien à corriger."))
    assert library.review("systeme_solaire")["rien"] is True
    copy = library.improve("systeme_solaire", "Ajoute les lunes de Jupiter")
    assert copy["id"] != "systeme_solaire" and copy["base"] == "systeme_solaire"
    assert (BUILTIN_DIR / "systeme_solaire.html").read_bytes() == before
    with pytest.raises(SimError):
        library.undo("systeme_solaire")


@pytest.mark.parametrize("bad", ["../secret", "..\\x", "a/b", "", "X" * 60, "coeur.html"])
def test_simulation_ids_are_confined(tmp_path: Path, bad: str) -> None:
    with pytest.raises(SimError):
        SimLibrary(tmp_path).path(bad)


def test_claude_code_local_requests_and_import(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    claude.mkdir()
    launcher = claude / "Lanceur.bat"
    launcher.write_text("@echo off\nset SECRET=ne_pas_lire\n", encoding="utf-8")
    spawned: list[Any] = []
    library = SimLibrary(tmp_path / "data", claude_dir=claude, claude_launcher=launcher,
                         spawner=lambda args, **kw: spawned.append((args, kw)))
    request = library.ask_claude("Le cycle de l'eau", "CM1", "évaporation, condensation", CHAPTER)
    brief = (claude / "professeur" / "demandes" / f"{request['id']}.md").read_text(encoding="utf-8")
    assert "professeur/simulations/le_cycle_de_l_eau.html" in brief and "AUCUNE ressource externe" in brief
    assert request["consigne"].startswith("Lis professeur/demandes/")
    assert library.collect_claude()[0]["statut"] == "en attente"
    (claude / "professeur" / "simulations" / "le_cycle_de_l_eau.html").write_text(GOOD_PAGE, encoding="utf-8")
    assert library.collect_claude()[0]["statut"] == "importée"
    assert any(s["origine"] == "Claude Code local" and s["chapitre"] == CHAPTER for s in library.list())
    bad = library.ask_claude("Mauvaise page")
    (claude / "professeur" / "simulations" / f"{bad['id']}.html").write_text(
        "<!doctype html><html><canvas></canvas><script>fetch('https://x.example')</script></html>", encoding="utf-8")
    refused = {s["id"]: s for s in library.collect_claude()}[bad["id"]]
    assert refused["statut"] == "refusée" and "réseau" in refused["raison"]
    assert library.open_claude() == {"ouvert": True}
    assert spawned[0][0][-1] == str(launcher) and spawned[0][1]["cwd"] == str(claude)
    with pytest.raises(SimError):
        SimLibrary(tmp_path).ask_claude("x")
    with pytest.raises(SimError):
        SimLibrary(tmp_path, claude_launcher=claude / "absent.bat").open_claude()


# -- sources
def test_wikipedia_reads_only_wiki_pages_politely(tmp_path: Path) -> None:
    asked: list[str] = []

    def fetch(url: str) -> Any:
        asked.append(url)
        if "Inconnu" in url:
            raise RuntimeError("404")
        return SimpleNamespace(title="Cycle de l'eau — Wikipédia", text="eau " * 200)

    read = wikipedia(tmp_path, fetcher=SimpleNamespace(fetch=fetch))
    page = read("Cycle de l'eau")
    assert page and page["title"] == "Cycle de l'eau" and asked[0].startswith("https://fr.wikipedia.org/wiki/Cycle_de_l")
    assert read("Inconnu") is None and read("a|b") is None and read("") is None


def test_hermes_verifier_uses_safe_toolsets_only() -> None:
    seen: list[list[str]] = []

    def runner(args: list[str], **kw: Any) -> Any:
        seen.append(args)
        return SimpleNamespace(stdout=b"Verdict : correct", stderr=b"", returncode=0)

    ask = hermes_verifier("hermes.exe", runner=runner)
    assert ask is not None and ask("relis") == "Verdict : correct"
    args = seen[0]
    assert args[:3] == ["hermes.exe", "-z", "relis"] and "-s" not in args
    assert "terminal" not in args[args.index("-t") + 1] and "web" in args[args.index("-t") + 1]
    assert args[args.index("--reasoning") + 1] == "medium"  # « high » est refusé par Qwen (essai réel du 23/11)
    empty = hermes_verifier("hermes.exe",
                            runner=lambda a, **k: SimpleNamespace(stdout=b"", stderr=b"boom", returncode=1))
    with pytest.raises(RuntimeError):
        empty("x")
    provider_error = (b"custom returned a server error on all 3 attempts\n\nProvider said: HTTP 500\n"
                      b"Your request was not processed.")
    failing = hermes_verifier("hermes.exe", runner=lambda a, **k: SimpleNamespace(stdout=provider_error, stderr=b"",
                                                                                  returncode=0))
    with pytest.raises(RuntimeError, match="hermes logs"):
        failing("x")  # essai réel du 23/11 : l'erreur n'est plus prise pour une relecture


def test_an_answer_without_verdict_leaves_the_lesson_untouched(tmp_path: Path) -> None:
    prof = teacher(tmp_path, verifier=lambda prompt: "Je n'ai pas pu lire le cours.")
    prof.lesson(CHAPTER)
    with pytest.raises(TeacherError, match="verdict"):
        prof.verify(CHAPTER)
    lesson = prof.lesson(CHAPTER)
    assert lesson["notes"] == [] and lesson["verification"] is None
    prof.verifier = lambda prompt: "**Verdict : correct** — conforme au programme."
    assert prof.verify(CHAPTER)["correct"] is True


# -- module et API
def test_off_topic_local_passages_are_not_used_as_sources() -> None:
    from modules.genesis_lab.module import relevant

    assert not relevant({"score": 0.558, "mode": "vecteurs"})  # « Loi des gaz parfaits » pour la loi d'Ohm (réel)
    assert relevant({"score": 0.72, "mode": "vecteurs"}) and relevant({"score": 0.61, "mode": "mots"})
    assert relevant({"title": "sans score"})


@pytest.fixture
def lab(tmp_path: Path):
    from core.module_api import load_manifest
    from modules.genesis_lab.module import GenesisLabModule

    module = GenesisLabModule(load_manifest(Path("modules/genesis_lab")), {"profile": str(tmp_path / "eleve.json")})
    module.start()
    yield module
    module.stop()


def wait(lab: Any, job: dict[str, Any]) -> dict[str, Any]:
    for _ in range(200):
        state = lab._run("travail", {"cle": job["cle"]})
        if not state["en_cours"]:
            return state
        time.sleep(0.02)
    raise AssertionError("travail sans fin")


def test_module_commands_end_to_end(lab: Any, tmp_path: Path) -> None:
    assert len(lab._run("niveaux", {})["niveaux"]) == 12
    assert lab._run("programme", {"niveau": "cm2", "matiere": "maths"})["matiere_nom"] == "Mathématiques"
    started = lab._run("cours", {"chapitre": CHAPTER})
    assert started["pret"] is False and "modèle local" in wait(lab, started["travail"])["erreur"]
    lab.teacher.llm = FakeLlm(json.dumps(LESSON))
    ready = wait(lab, lab._run("cours", {"chapitre": CHAPTER})["travail"])["resultat"]
    assert ready["lecon"]["titre"] == "Un cours" and ready["simulations"]
    assert lab._run("cours", {"chapitre": CHAPTER})["pret"] is True
    graded = wait(lab, lab._run("corriger", {"chapitre": CHAPTER, "reponses": {"e1": 1}})["travail"])["resultat"]
    assert graded["taux"] == 1
    sims = lab._run("simulations", {})
    assert len(sims["simulations"]) == 10 and sims["claude_local"] is False and sims["modele"] is False
    with pytest.raises(ValueError):
        lab._run("cours", {"chapitre": "../../x"})
    with pytest.raises(ValueError):
        lab._run("creer_simulation", {"sujet": "x", "moteur": "claude"})
    with pytest.raises(ValueError):
        lab._run("commande_inconnue", {})
    assert (tmp_path / "cours" / "4e" / "physique_chimie" / "5.json").is_file()  # tout reste dans tmp_path


def test_api_serves_simulations_in_a_sandbox(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from core.api import create_app
    from core.daemon import Daemon
    from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
    from core.llm_router import LlmRouter
    from tests.core.test_daemon import ollama_stopped

    (tmp_path / "modules").mkdir()
    client = TestClient(create_app(Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()),
                                          process_names=lambda: set(), llm=LlmRouter(transport=ollama_stopped))))
    page = client.get("/prof/sims/coeur")
    assert page.status_code == 200 and "<canvas" in page.text
    head = page.text.split("<title>")[0]
    assert "AetherTwin : pause et taille du cadre" in head  # pause commune, placée avant les scripts de la page
    csp = page.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp and "default-src 'none'" in csp and "connect-src" not in csp
    assert client.get("/prof/sims/..%2Fsims").status_code == 404
    assert client.get("/prof/sims/inconnue").status_code == 404
    dashboard = client.get("/")
    assert "frame-src 'self'" in dashboard.headers["content-security-policy"]
    assert "/static/professeur.js" in dashboard.text
    script = client.get("/static/professeur.js")
    assert script.status_code == 200 and "eval(" not in script.text and "new Function" not in script.text


def test_builtin_sims_scripts_parse() -> None:
    """Chaque script des simulations intégrées se compile (une erreur de syntaxe = une page figée sans message)."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js absent")
    from modules.genesis_lab.sims import BUILTIN_DIR, HUB_TOOLS

    checker = ("const fs=require('fs');const bad=[];for(const f of JSON.parse(process.argv[1])){"
               r"const html=fs.readFileSync(f,'utf8');for(const m of html.matchAll(/<script>([\s\S]*?)<\/script>/g)){"
               "try{new Function(m[1])}catch(e){bad.push(f+': '+e.message)}}}console.log(JSON.stringify(bad))")
    files = [str(path) for path in sorted(BUILTIN_DIR.glob("*.html"))]
    tools = BUILTIN_DIR.parent / "_hub_tools_check.html"
    tools.write_text(HUB_TOOLS, encoding="utf-8")
    try:
        done = subprocess.run([node, "-e", checker, json.dumps([*files, str(tools)])], capture_output=True,  # noqa: S603
                              text=True, encoding="utf-8", timeout=60, check=False)
    finally:
        tools.unlink()
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == []
