"""Version du jeu lue dans .build.info, faits de la base datés par patch."""
import time

HEADER = ("Branch!STRING:0|Active!DEC:1|Build Key!HEX:16|Version!STRING:0|Product!STRING:0\n")


def _install(tmp_path, rows, folder="_retail_"):
    (tmp_path / ".build.info").write_text(HEADER + "".join(rows), encoding="utf-8")
    game = tmp_path / folder
    game.mkdir()
    return str(game)


def test_build_info_picks_the_row_of_the_game_folder(tmp_path) -> None:
    import gameversion
    game = _install(tmp_path, ["eu|1|ab|1.15.8.123|wow_classic_era\n", "eu|1|cd|12.1.5.70961|wow\n"])
    info = gameversion.build_info(game)
    assert info == {"product": "wow", "version": "12.1.5.70961", "patch": "12.1.5", "flavor": "retail"}
    assert gameversion.flavor(str(tmp_path / "_forever_")) == "forever"
    assert gameversion.build_info(str(tmp_path / "nowhere" / "_retail_")) == {}
    assert gameversion.patch_of("12.0.7.68000") == "12.0.7"


def test_web_facts_are_stale_when_the_patch_changes_but_player_rules_never(tmp_path) -> None:
    from coach_knowledge import KnowledgeBase
    patch = {"now": "12.1.5"}
    kb = KnowledgeBase(str(tmp_path / "kb.json"), patch_fn=lambda: patch["now"])
    kb.add("build", "Farouche : stats", "Maîtrise > Critique", source="https://www.wowhead.com/fr/guide")
    kb.add("règle", "Touche des talents", "N", source="joueur", status="joueur")
    assert kb.entries[0]["patch"] == "12.1.5" and kb.stats()["à revérifier"] == 0
    patch["now"] = "12.2.0"
    assert kb.stats()["à revérifier"] == 1
    found = kb.search("Farouche stats")
    web = next(f for f in found if f["thème"] == "build")
    assert "patch changé : 12.1.5 → 12.2.0" in web["statut"] and web["version_du_jeu"] == "12.1.5"
    player = next(f for f in kb.search("touche talents") if f["thème"] == "règle")
    assert "revérifier" not in player["statut"]
    kb.set_status(kb.entries[0]["id"], "sourcé")                    # revérifié : daté du nouveau patch
    assert kb.entries[0]["patch"] == "12.2.0" and kb.stats()["à revérifier"] == 0
    kb.entries[0]["verified"] = time.time() - 50 * 86400
    assert kb.stale_reason(kb.entries[0]).startswith("vérifié il y a plus de")
