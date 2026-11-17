"""Professeur adaptatif (session guidée scriptée, LLM factice) et module genesis_lab dans le Hub."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.daemon import Daemon
from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
from core.llm_router import LlmError, LlmRouter
from core.module_api import Event, load_manifest
from modules.genesis_lab import astro, chem
from modules.genesis_lab.module import TOOLS, GenesisLabModule, compute
from modules.genesis_lab.tutor import Tutor, check_answer, make_exercise

MODULE_DIR = Path(__file__).resolve().parents[2] / "modules" / "genesis_lab"


# --------------------------------------------------------------------------- exercices
def test_exercises_are_reproducible_and_answered_by_the_code() -> None:
    assert make_exercise("chem", 1, 7) == make_exercise("chem", 1, 7)  # même graine : même exercice
    assert len({make_exercise("astro", 2, seed).question for seed in range(12)}) > 1  # d'autres graines : variété
    for domain in ("bio", "astro", "chem"):
        for level in (1, 2, 3):
            exercise = make_exercise(domain, level, 3)
            assert exercise.domain == domain and exercise.level == level and exercise.question and exercise.method
            assert check_answer(exercise, exercise.answer)  # la réponse calculée est acceptée par le correcteur
            assert "answer" not in exercise.to_dict() and "method" not in exercise.to_dict()
    with pytest.raises(ValueError, match="domaine inconnu"):
        make_exercise("alchimie", 1, 0)


def test_answers_are_checked_with_a_tolerance() -> None:
    kepler = make_exercise("astro", 2, 1)
    assert check_answer(kepler, kepler.answer * 1.005) and not check_answer(kepler, kepler.answer * 1.05)
    assert check_answer(kepler, str(kepler.answer).replace(".", ",")) and not check_answer(kepler, "beaucoup")
    protein = make_exercise("bio", 2, 1)
    assert check_answer(protein, f" {str(protein.answer).lower()} ") and not check_answer(protein, "MMMMM")


# --------------------------------------------------------------------------- session guidée scriptée
def test_guided_session(tmp_path: Path) -> None:
    """Scénario complet : évaluation du niveau, exercices, montée puis descente de niveau, reprise le lendemain."""
    prompts: list[str] = []

    def llm(messages: list[dict[str, str]]) -> str:
        prompts.append(messages[0]["content"])
        return "Bravo, continue ainsi."  # le modèle « oublie » de rappeler la valeur

    def search(query: str) -> list[dict[str, str]]:
        return [{"title": "Cours : " + query, "url": "https://exemple.invalid/cours", "snippet": "…"},
                {"title": "sans adresse", "url": ""}]

    profile = tmp_path / "eleve.json"
    tutor = Tutor(profile, llm=llm, search=search, seed=42)

    # 1. évaluation : l'élève réussit la question facile et la moyenne, rate la difficile -> niveau 2
    questions = tutor.placement_questions("chem")
    assert [q.level for q in questions] == [1, 2, 3]
    assert tutor.submit_placement("chem", [questions[0].answer, questions[1].answer, "je ne sais pas"]) == 2

    # 2. deux réussites d'affilée -> niveau 3
    first = tutor.next_exercise("chem")
    assert first.level == 2
    result = tutor.answer(first, first.answer)
    assert result["correct"] and result["level_after"] == 2
    second = tutor.next_exercise("chem")
    assert second != first
    result = tutor.answer(second, second.answer)
    assert result["correct"] and result["level_before"] == 2 and result["level_after"] == 3

    # 3. deux échecs d'affilée -> retour au niveau 2 ; la correction contient toujours la valeur calculée
    hard = tutor.next_exercise("chem")
    assert hard.level == 3
    wrong = tutor.answer(hard, 99)
    assert not wrong["correct"] and wrong["expected"] == hard.answer and str(hard.answer) in wrong["explanation"]
    assert wrong["explanation"].startswith("Bravo")  # texte du modèle, complété par le garde-fou
    assert wrong["sources"] == [{"title": "Cours : " + hard.topic, "url": "https://exemple.invalid/cours"}]
    assert tutor.answer(tutor.next_exercise("chem"), 99)["level_after"] == 2

    # 4. le modèle reçoit la réponse calculée et la consigne de niveau, jamais l'inverse
    assert "calculée par le programme" in prompts[-1] and "ne la recalcule pas" in prompts[-1]
    assert "avancé" in prompts[-1] and str(hard.answer) in prompts[-2]

    # 5. le lendemain : la progression a été mémorisée
    later = Tutor(profile, seed=42)
    progress = later.progress()
    assert progress["chem"] == {"level": 2, "level_name": "intermédiaire", "done": 4, "correct": 2}
    assert progress["bio"]["done"] == 0 and later.level("astro") == 1
    assert json.loads(profile.read_text(encoding="utf-8"))["levels"] == {"chem": 2}


def test_tutor_works_without_llm_and_survives_failures(tmp_path: Path) -> None:
    tutor = Tutor(tmp_path / "p.json")
    exercise = tutor.next_exercise("astro")
    result = tutor.answer(exercise, exercise.answer)
    assert result["explanation"].startswith("La réponse est juste.") and result["sources"] == []

    def broken_llm(messages: list[dict[str, str]]) -> str:
        raise OSError("modèle indisponible")

    def broken_search(query: str) -> list[dict[str, str]]:
        raise OSError("réseau coupé")

    fragile = Tutor(tmp_path / "q.json", llm=broken_llm, search=broken_search)
    exercise = fragile.next_exercise("bio")
    result = fragile.answer(exercise, "faux")
    assert not result["correct"] and str(exercise.answer) in result["explanation"] and result["sources"] == []


def test_explanation_with_numbers_the_code_did_not_provide_is_rejected(tmp_path: Path) -> None:
    """Constat réel du 17/11 : le modèle invente des calculs intermédiaires faux. Son texte est alors écarté."""
    exercise = make_exercise("astro", 2, 5)  # « … à 0.39 unités astronomiques … » -> 89.0 jours
    assert exercise.answer == 89.0
    calls: list[list[dict[str, str]]] = []

    def inventive(messages: list[dict[str, str]]) -> str:
        calls.append(messages)
        return "La racine de 0.059319 donne 0.2436 an, soit 89.0 jours."

    result = Tutor(tmp_path / "a.json", llm=inventive).answer(exercise, 100)
    assert len(calls) == 2 and "0.059319" in calls[1][-1]["content"]  # une seconde chance, avec le reproche précis
    assert result["explanation"].startswith("La réponse attendue est 89.0 jours.")  # puis l'explication type
    assert "0.059319" not in result["explanation"]

    def corrected(messages: list[dict[str, str]]) -> str:
        return ("La racine de 0.059319 donne 89.0 jours." if len(messages) == 1
                else "Avec la 3ᵉ loi de Kepler, à 0,39 unité astronomique on trouve 89,0 jours et non 100.")

    kept = Tutor(tmp_path / "b.json", llm=corrected).answer(exercise, 100)["explanation"]
    assert kept.startswith("Avec la 3ᵉ loi") and "La réponse attendue" not in kept  # « 89,0 » vaut « 89.0 »


def test_number_guard_helpers() -> None:
    from modules.genesis_lab.tutor import foreign_numbers, numbers_in

    assert numbers_in("à 0,39 UA : 89.0 jours, T² = a³") == [0.39, 89.0]
    assert foreign_numbers("la 3ᵉ loi, 2 fois, 89,0 jours", [89.0]) == []  # petits entiers toujours admis
    assert foreign_numbers("soit 88.9 jours", [89.0]) == [] and foreign_numbers("soit 95 jours", [89.0]) == ["95"]
    assert foreign_numbers("3.5 fois", [89.0]) == ["3.5"]  # un décimal n'est pas un « petit entier »


def test_corrupt_profile_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("{ cassé", encoding="utf-8")
    assert Tutor(path).level("chem") == 1


# --------------------------------------------------------------------------- outils et module
def test_only_whitelisted_tools_can_be_called() -> None:
    assert compute("chem.molar_mass_g_mol", {"formula": "H2O"}) == pytest.approx(18.015)
    assert compute("astro.pc_to_ly", {"value_pc": 1.0}) == pytest.approx(astro.pc_to_ly(1.0))
    assert compute("bio.find_orfs", {"sequence": "ATGGCCTAA", "min_aa": 1})[0]["protein"] == "MA"
    for name in ("os.system", "chem.__dict__", "builtins.eval", "chem.ATOMIC_MASS", "", "bio"):
        with pytest.raises(ValueError, match="outil inconnu"):
            compute(name, {})
    with pytest.raises(ValueError, match="arguments invalides"):
        compute("chem.molar_mass_g_mol", {"formule": "H2O"})
    with pytest.raises(ValueError, match="dictionnaire"):
        compute("chem.molar_mass_g_mol", ["H2O"])  # type: ignore[arg-type]
    assert all("." in name and callable(fn) for name, fn in TOOLS.items())


@pytest.fixture
def module(tmp_path: Path):
    lab = GenesisLabModule(load_manifest(MODULE_DIR), {"profile": str(tmp_path / "eleve.json")})
    events: list[Event] = []
    lab.publish = events.append
    lab.start()
    yield lab, events
    lab.stop()


def test_module_answers_compute_requests_and_reports_errors(module) -> None:
    lab, events = module
    lab.handle_event(Event("module.genesis_lab.cmd.compute", {
        "request_id": "a1", "tool": "chem.ph_weak_acid", "args": {"concentration_mol_l": 0.1, "ka": 1.8e-5}}))
    assert events[-1].topic == "module.genesis_lab.result"
    assert events[-1].payload["ok"] and events[-1].payload["request_id"] == "a1"
    assert events[-1].payload["result"] == pytest.approx(chem.ph_weak_acid(0.1, 1.8e-5))
    lab.handle_event(Event("module.genesis_lab.cmd.compute", {"request_id": "a2", "tool": "os.system", "args": {}}))
    assert events[-1].payload == {"request_id": "a2", "command": "compute", "ok": False,
                                  "error": "ValueError: outil inconnu : 'os.system'"}
    lab.handle_event(Event("module.genesis_lab.cmd.compute",
                           {"tool": "chem.molar_mass_g_mol", "args": {"formula": "Zz"}}))
    assert not events[-1].payload["ok"] and "élément inconnu" in events[-1].payload["error"]
    lab.handle_event(Event("module.genesis_lab.cmd.danse", {}))
    assert not events[-1].payload["ok"]
    lab.handle_event(Event("process.started", {"name": "x"}))  # événement étranger : ignoré
    health = lab.health()
    assert health.ok and health.degraded and "4 demandes, 3 erreurs" in health.detail and "sans LLM" in health.detail


def test_module_exercise_flow_never_sends_the_answer_with_the_question(module) -> None:
    lab, events = module
    lab.handle_event(Event("module.genesis_lab.cmd.exercise", {"request_id": "e1", "domain": "astro"}))
    sent = events[-1].payload["result"]
    assert sent["question"] and "answer" not in sent and "method" not in sent
    expected = make_exercise("astro", sent["level"], sent["seed"]).answer
    lab.handle_event(Event("module.genesis_lab.cmd.answer", {"request_id": "e2", "domain": "astro",
                                                            "level": sent["level"], "seed": sent["seed"],
                                                            "given": expected}))
    assert events[-1].payload["result"]["correct"] is True and events[-1].payload["result"]["expected"] == expected
    lab.handle_event(Event("module.genesis_lab.cmd.progress", {"request_id": "e3"}))
    assert events[-1].payload["result"]["astro"]["done"] == 1
    lab.handle_event(Event("module.genesis_lab.cmd.exercise", {"domain": "alchimie"}))
    assert not events[-1].payload["ok"]


def test_module_runs_inside_the_real_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bout en bout : le module dans son processus répond à une demande de calcul envoyée sur le bus."""
    config = tmp_path / "local.yaml"
    config.write_text(json.dumps({"genesis_lab": {"profile": str(tmp_path / "eleve.json")}}), encoding="utf-8")
    monkeypatch.setenv("AETHERTWIN_CONFIG", str(config))

    def ollama_stopped(method: str, url: str, body: dict | None, timeout_s: float) -> dict:
        raise LlmError("arrêté pour le test")

    daemon = Daemon(MODULE_DIR.parent, monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    seen: list[Event] = []
    daemon.bus.subscribe("module.genesis_lab", seen.append)
    daemon.start()
    try:
        daemon.activate("genesis_lab")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and not any(e.topic.endswith(".started") for e in seen):
            time.sleep(0.05)
        daemon.bus.publish(Event("module.genesis_lab.cmd.compute", {
            "request_id": "kepler", "tool": "astro.orbital_period_s", "args": {"semi_major_axis_m": astro.AU_M}}))
        while time.monotonic() < deadline and not any(e.topic.endswith(".result") for e in seen):
            time.sleep(0.05)
        result = next(e.payload for e in seen if e.topic.endswith(".result"))
        assert result["ok"] and result["request_id"] == "kepler"
        assert result["result"] / 86_400 == pytest.approx(365.2569, abs=0.01)  # une année, calculée dans le module
    finally:
        daemon.stop()
