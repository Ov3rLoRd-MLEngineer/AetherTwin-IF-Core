"""Routine de la semaine : remises à zéro, liste à cocher, autres personnages, tâches perso, onglet et outil MCP."""
import calendar
import json
import os
from pathlib import Path

# lundi 23/11/2026 10:00 UTC
NOW = calendar.timegm((2026, 11, 23, 10, 0, 0))


def snap(name="Sakuranïchan", updated=NOW, weekly_reset=0, **extra):
    s = {
        "character": {"name": name, "realm": "Hyjal", "level": 80, "class": "Druide", "ilvl": 652, "region": "EU",
                      "updated": updated, "weeklyReset": weekly_reset, "dailyReset": 0},
        "vault": {"activities": [{"type": 3, "index": i, "threshold": t, "progress": 2}
                                 for i, t in ((1, 2), (2, 4), (3, 6))]
                  + [{"type": 1, "index": 1, "threshold": 1, "progress": 0}], "hasRewards": False},
        "currencies": [{"name": "Écu de l'aube", "weekly": 45, "weeklyMax": 90, "quantity": 120, "max": 0},
                       {"name": "Or de guerre", "weekly": 0, "weeklyMax": 0, "quantity": 5}],
        "quests": {"list": [{"title": "Proie : la traque", "freq": 2, "status": "incomplete", "zone": "Quel'Thalas"},
                            {"title": "Une journalière", "freq": 1, "status": "complete", "zone": ""},
                            {"title": "Campagne", "freq": 0, "status": "incomplete"}]},
        "lockouts": {"instances": [{"name": "Flèche du Vide", "difficulty": "Normal", "progress": 3, "total": 8,
                                    "expires": NOW + 3600, "isRaid": True}], "worldBosses": []},
        "mythicPlus": {"week": [{"level": 7, "completed": True}],
                       "keystone": {"name": "Autel des crochets", "level": 8}},
    }
    s.update(extra)
    return s


def test_reset_times_eu_fallback_and_addon_values() -> None:
    import routine
    daily, weekly = routine.next_resets({"region": "EU"}, NOW)
    assert time_utc(weekly) == (2026, 11, 25, 4) and time_utc(daily) == (2026, 11, 24, 4)
    _d, weekly_us = routine.next_resets({"region": "US"}, NOW)
    assert time_utc(weekly_us) == (2026, 11, 24, 15)
    # valeur de l'addon dépassée : avancée d'une semaine
    _d, weekly2 = routine.next_resets({"weeklyReset": NOW - 3600}, NOW)
    assert weekly2 == NOW - 3600 + routine.WEEK
    assert routine.format_delay(2 * 86400 + 5 * 3600) == "2 j 5 h"


def time_utc(stamp):
    import time
    t = time.gmtime(stamp)
    return (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour)


def test_checklist_from_the_addon_data() -> None:
    import routine
    items = routine.checklist(routine.summarize(snap(), NOW), NOW)
    labels = {i["label"]: i for i in items}
    assert labels["Raid : 1/3"]["detail"] == "prochain emplacement : 2/4" and labels["Raid : 1/3"]["done"] is False
    assert labels["Écu de l'aube : 45/90"]["done"] is False
    assert not any("Or de guerre" in i["label"] for i in items)           # pas de plafond : pas suivi
    assert labels["Proie : la traque"]["group"] == "Quêtes hebdomadaires"
    assert labels["Une journalière"]["done"] is True and "Campagne" not in labels
    assert labels["Flèche du Vide (Normal)"]["detail"] == "3/8 boss"
    assert any(i["label"].startswith("Clés cette semaine : 1") for i in items)


def test_progress_from_before_the_reset_is_not_counted() -> None:
    import routine
    old = routine.summarize(snap(updated=NOW - 6 * 86400), NOW)      # mardi précédent : avant le mercredi 04:00
    assert routine.outdated(old, NOW)
    items = {i["label"]: i for i in routine.checklist(old, NOW)}
    assert "Raid : 0/3" in items and "Écu de l'aube : 0/90" in items


def test_store_keeps_alts_tasks_and_unchecks_them_at_reset(tmp_path) -> None:
    import routine
    st = routine.RoutineStore(str(tmp_path / "routine.json"))
    assert st.record(snap(), NOW) and st.record(snap(name="Reroll", updated=NOW - 100), NOW)
    assert not st.record(snap(updated=NOW - 5000), NOW)                 # plus ancien que ce qu'on a : ignoré
    assert [s["name"] for s in st.others("Sakuranïchan-Hyjal")] == ["Reroll"]
    assert st.add_task("Commandes d'artisanat", "weekly") and st.add_task("Proie", "daily")
    assert not st.add_task("proie", "daily")                             # doublon
    task = st.tasks[0]
    key = "Sakuranïchan-Hyjal"
    st.toggle(key, task["id"], now=NOW)
    assert st.is_done(key, task, NOW)
    assert not st.is_done(key, task, NOW + 3 * 86400)                   # après la remise à zéro du mercredi
    again = routine.RoutineStore(str(tmp_path / "routine.json"))
    assert len(again.characters) == 2 and len(again.tasks) == 2
    data = routine.describe(again, key, NOW)
    assert data["remise_à_zéro"]["hebdomadaire_dans"] == "1 j 18 h"
    assert any("Reroll" in line for line in data["autres_personnages"])
    assert "60 minutes" in routine.plan_prompt(again, key, 60, NOW)
    again.remove_task(task["id"])
    assert len(again.tasks) == 1


def test_mcp_routine_tool_reads_without_writing(tmp_path) -> None:
    import hermes_mcp
    import routine

    class Game:
        routine_path = str(tmp_path / "routine.json")

        def snapshot(self):
            return snap(updated=routine.time.time())

    result = json.loads(hermes_mcp.call_tool(Game(), "wow_routine", {"minutes": 45})["content"][0]["text"])
    assert result["personnage"] == "Sakuranïchan-Hyjal" and result["temps_de_jeu_annoncé"] == "45 min"
    assert any("Écu" in line for line in result["à_faire"])
    assert not os.path.exists(tmp_path / "routine.json")


def test_week_tab_renders_without_cut_text(app) -> None:
    import time
    me = snap(name=app.test_ctx.character.name, updated=time.time())
    me["character"]["realm"] = app.test_ctx.character.realm
    app.routine.record(me, time.time())
    assert app.test_ctx.character.key in app.routine.characters
    app.routine.record(snap(name="Reroll", updated=time.time() - 8 * 86400), time.time())
    app.routine.add_task("Commandes d'artisanat de la semaine", "weekly")
    app.active_tab = app.TABS.index("Semaine")
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    folder = os.environ.get("AETHERTWIN_SHOTS")
    if folder:
        import pygame
        Path(folder).mkdir(parents=True, exist_ok=True)
        pygame.image.save(app.screen, os.path.join(folder, "week_tab.png"))


def test_week_widget_lists_what_is_left(app) -> None:
    import time

    from tabs_routine import draw_week_widget
    me = snap(name=app.test_ctx.character.name, updated=time.time())
    me["character"]["realm"] = app.test_ctx.character.realm
    app.routine.record(me, time.time())
    app.routine.add_task("Proie", "daily")
    app.screen.cut.clear()
    draw_week_widget(app, app.test_ctx, (20, 20, 300, 240))
    assert app.screen.cut == []
    assert "semaine" in [s.id for s in __import__("widgets_builtin").build_specs()]
