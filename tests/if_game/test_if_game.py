"""if_game : graine reproductible, le modèle propose / le code valide, pas d'échec punitif, sauvegarde locale."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.module_api import Event, load_manifest
from modules.if_game.module import IfGameModule
from modules.if_game.world import (
    MAX_ENERGY,
    World,
    act,
    parse_action,
    validate_proposal,
    view,
)

ROOT = Path(__file__).resolve().parents[2]


def play(seed: int, actions: list[str], propose=None) -> World:
    world = World.new(seed)
    for action in actions:
        act(world, action, propose)
    return world


def test_same_seed_same_world_without_model() -> None:
    route = ["nord", "regarder", "est", "ouest", "sud", "ouest"]
    a, b = play(7, route), play(7, route)
    assert a.to_dict() == b.to_dict()
    assert play(8, route).to_dict() != a.to_dict()  # autre graine, autre monde


@pytest.mark.parametrize("verb, expected", [
    ("N", ("aller", "nord")), ("aller vers le nord", ("aller", "nord")), ("Prendre la plume d'étoile",
                                                                          ("prendre", "plume d'etoile")),
    ("répondre Lumière", ("repondre", "lumiere")), ("parler à Fuma", ("parler", "fuma")), ("i", ("inventaire", "")),
    ("rm -rf /", ("inconnu", "rm -rf /")),
])
def test_actions_are_parsed_by_code(verb, expected) -> None:
    assert parse_action(verb) == expected


def test_model_proposal_is_validated() -> None:
    good = '{"name": "Jardin des lanternes", "description": "Des lanternes de papier flottent au ras de l\'herbe. ' \
           'Une odeur de thé chaud flotte dans l\'air.", "item": "lanterne bleue"}'
    assert validate_proposal(good, set())["name"] == "Jardin des lanternes"
    assert validate_proposal("<think>…</think>" + good, set()) is not None
    assert validate_proposal(good, {"Jardin des lanternes"}) is None  # nom déjà pris
    harsh = good.replace("thé chaud", "sang séché")
    assert validate_proposal(harsh, set()) is None  # ton du jeu : refusé
    assert validate_proposal('{"name": "X"}', set()) is None
    assert validate_proposal("pas du json", set()) is None


def test_accepted_proposal_is_used_and_refused_one_falls_back() -> None:
    def kind(prompt: str) -> str:
        assert "CALME" in prompt
        return json.dumps({"name": "Pont des nuages", "description": "Un pont de vapeur blanche relie deux "
                           "collines. Il tiède sous les pas.", "item": ""})
    world = play(3, ["nord"], kind)
    assert world.place.name == "Pont des nuages" and world.place.origin == "modèle local"
    assert world.place.exits["sud"] == "sanctuaire"  # le chemin du retour, posé par le code
    rude = play(3, ["nord"], lambda p: '{"name": "Arène", "description": "Un combat sanglant commence ici, '
                                       'les ennemis attaquent.", "item": "épée"}')
    assert rude.place.origin == "procédural" and rude.place.name == play(3, ["nord"]).place.name

    def broken(prompt: str) -> str:
        raise OSError("Hub arrêté")
    assert play(3, ["nord"], broken).place.origin == "procédural"


def test_no_punishing_failure() -> None:
    world = World.new(1)
    world.energy = 0
    assert "repos" in act(world, "nord") and world.here == "sanctuaire"  # pas de chute, une suggestion
    act(world, "repos")
    assert world.energy == MAX_ENERGY
    assert "Pas de chemin" in act(world, "bas")
    assert "ne comprennent pas" in act(world, "attaquer le dragon")


def test_riddle_gives_a_hint_then_restores_light() -> None:
    world = World.new(1)
    place = world.place
    place.riddle = {"question": "?", "answers": ["lune", "la lune"], "solved": False, "hint": "Indice : L."}
    world.energy = 3
    assert "Indice" in act(world, "répondre soleil") and world.energy == 3
    assert "illumine" in act(world, "répondre La Lune !") and world.energy == MAX_ENERGY
    assert world.riddles_solved == 1 and "Aucune inscription" in act(world, "répondre lune")


def test_items_and_inventory() -> None:
    world = World.new(1)
    assert "ramasse" in act(world, "prendre lanterne")
    assert world.inventory == ["lanterne tiède"] and world.place.items == []
    assert "pas de" in act(world, "prendre lanterne").lower()
    assert "lanterne tiède" in act(world, "inventaire")


def test_save_load_and_corrupted_save(tmp_path: Path) -> None:
    world = play(5, ["nord", "regarder"])
    path = tmp_path / "partie.json"
    world.save(path)
    assert World.load(path).to_dict() == world.to_dict()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["here"] = "nulle_part"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        World.load(path)


def test_dialogue_is_checked() -> None:
    world = World.new(2)
    assert "Inoue" in act(world, "parler à Inoue", talk=None)
    assert act(world, "parler à Fuma", talk=lambda p: "« Respire, le vent connaît le chemin. »") == \
        "Fuma : « Respire, le vent connaît le chemin. »"
    assert "Fuma" in act(world, "parler à Fuma", talk=lambda p: "Je vais te tuer.")  # refusé : réplique type


def test_module_commands_and_autosave(tmp_path: Path) -> None:
    settings = {"hub_api": "", "save": str(tmp_path / "p.json")}
    module = IfGameModule(load_manifest(ROOT / "modules" / "if_game"), settings)
    sent: list[Event] = []
    module.publish = sent.append  # type: ignore[method-assign]
    module.start()
    module.handle_event(Event("module.if_game.cmd.new", {"request_id": "1", "seed": 42}))
    assert sent[-1].payload["result"]["place"] == "Sanctuaire de l'Éther"
    module.handle_event(Event("module.if_game.cmd.act", {"request_id": "2", "text": "nord"}))
    result = sent[-1].payload["result"]
    assert result["turn"] == 1 and result["energy"] == MAX_ENERGY - 1 and result["origin"] == "procédural"
    assert (tmp_path / "p.json").is_file()
    restarted = IfGameModule(load_manifest(ROOT / "modules" / "if_game"), {"hub_api": "",
                                                                           "save": str(tmp_path / "p.json")})
    restarted.publish = sent.append  # type: ignore[method-assign]
    restarted.start()
    restarted.handle_event(Event("module.if_game.cmd.state", {"request_id": "3"}))
    assert sent[-1].payload["result"]["place"] == result["place"]  # la partie reprend où elle était
    restarted.handle_event(Event("module.if_game.cmd.danse", {"request_id": "4"}))
    assert sent[-1].payload["ok"] is False


def test_view_hides_the_riddle_answer() -> None:
    world = World.new(1)
    world.place.riddle = {"question": "Qui ?", "answers": ["lune"], "solved": False, "hint": "L"}
    shown = json.dumps(view(world), ensure_ascii=False)
    assert "Qui ?" in shown and "lune" not in shown
