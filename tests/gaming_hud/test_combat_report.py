"""Bilans de combat tirés du journal : boss, clé Mythique+, morts, avec et sans journalisation avancée."""
import json
import os
from pathlib import Path

ME = "Player-1-AAA"
MATE = "Player-1-BBB"
BOSS = "Creature-0-1-2-3-4-200001-0000AAA"
ME_F, MATE_F, NPC_F = "0x511", "0x512", "0xa48"
ADV = ",".join(["Player-1-AAA", "0000000000000000", "100", "100", "0", "0", "0", "0", "0", "0", "0", "1", "2", "3",
                "2600", "0", "80"])


def line(ts, event, *fields):
    return f"11/23/2026 {ts}.000-5  {event}," + ",".join(str(f) for f in fields)


def fight_lines(advanced=False):
    adv = (ADV + ",") if advanced else ""
    return [
        line("20:00:00", "CHALLENGE_MODE_START", '"Autel des crochets"', 2700, 500, 8, "[9,10]"),
        line("20:00:05", "SPELL_DAMAGE", ME, '"Sakura-Hyjal"', ME_F, "0x0", BOSS, '"Gardien"', NPC_F, "0x0",
             5221, '"Griffure"', 1, adv + "9000", 0, 1, 0, 0, 0, "nil", "nil", "nil"),
        line("20:00:10", "ENCOUNTER_START", 3001, '"Nalorakk"', 8, 5, 2700),
        line("20:00:11", "SPELL_DAMAGE", ME, '"Sakura-Hyjal"', ME_F, "0x0", BOSS, '"Nalorakk"', NPC_F, "0x0",
             5221, '"Griffure"', 1, adv + "50000", 0, 1, 0, 0, 0, "nil", "nil", "nil"),
        line("20:00:12", "SWING_DAMAGE", MATE, '"Rok-Hyjal"', MATE_F, "0x0", BOSS, '"Nalorakk"', NPC_F, "0x0",
             adv + "20000", 0, 1, 0, 0, 0, "nil", "nil", "nil"),
        line("20:00:13", "SPELL_HEAL", MATE, '"Rok-Hyjal"', MATE_F, "0x0", ME, '"Sakura-Hyjal"', ME_F, "0x0",
             774, '"Récupération"', 8, adv + "12000", 2000, 0, "nil"),
        line("20:00:14", "SPELL_DAMAGE", BOSS, '"Nalorakk"', NPC_F, "0x0", ME, '"Sakura-Hyjal"', ME_F, "0x0",
             9999, '"Charge brutale"', 1, adv + "70000", 0, 1, 0, 0, 0, "nil", "nil", "nil"),
        line("20:00:15", "SPELL_INTERRUPT", ME, '"Sakura-Hyjal"', ME_F, "0x0", BOSS, '"Nalorakk"', NPC_F, "0x0",
             106839, '"Coup de crâne"', 1, 1234, '"Rugissement"', 1),
        line("20:00:16", "UNIT_DIED", "0000000000000000", "nil", "0x80000000", "0x80000000", ME, '"Sakura-Hyjal"',
             ME_F, "0x0", 0),
        line("20:00:30", "ENCOUNTER_END", 3001, '"Nalorakk"', 8, 5, 1, 20000),
        line("20:20:00", "CHALLENGE_MODE_END", 2700, 1, 8, 1200000, 250.5, 3200.1),
    ]


def build(tmp_path, advanced=False):
    from bestiary import parse_line
    from combat_report import ReportBuilder
    builder = ReportBuilder(str(tmp_path / "reports.json"))
    for raw in fight_lines(advanced):
        event, fields = parse_line(raw)
        builder.feed(event, fields, raw)
    return builder


def test_boss_and_key_reports_from_the_log(tmp_path) -> None:
    for advanced in (False, True):
        builder = build(tmp_path / ("adv" if advanced else "plain"), advanced)
        key, boss = builder.latest(2)
        assert boss["kind"] == "boss" and boss["name"] == "Nalorakk" and boss["success"]
        assert boss["duration"] == 20 and boss["keyLevel"] == 8 and boss["me"] == "Sakura"
        me = next(p for p in boss["players"] if p["name"] == "Sakura")
        mate = next(p for p in boss["players"] if p["name"] == "Rok")
        assert me["damage"] == 50000 and me["dps"] == 2500 and me["interrupts"] == 1 and me["deaths"] == 1
        assert mate["damage"] == 20000 and mate["healing"] == 10000          # sans le surplus de soins
        assert boss["deaths"][0]["hits"][-1] == {"spell": "Charge brutale", "from": "Nalorakk", "amount": 70000}
        assert boss["hurtMe"][0]["spell"] == "Charge brutale"
        assert key["kind"] == "clé" and key["duration"] == 1200 and key["bosses"][0]["name"] == "Nalorakk"
        assert next(p for p in key["players"] if p["name"] == "Sakura")["damage"] == 59000   # trash compris


def test_reports_are_saved_described_and_read_by_hermes(tmp_path) -> None:
    import combat_report
    import hermes_mcp
    builder = build(tmp_path)
    again = combat_report.ReportBuilder(builder.path)
    assert len(again.reports) == 2
    text = combat_report.describe(again.latest(2)[1])
    assert "Boss : Nalorakk +8" in text and "Mort : Sakura à 6 s" in text and "Charge brutale" in text

    class Game:
        reports_path = builder.path

    out = json.loads(hermes_mcp.call_tool(Game(), "wow_combat_reports", {"query": "nalorakk"})["content"][0]["text"])
    assert len(out["bilans"]) == 1 and "Nalorakk" in out["bilans"][0]


def test_bestiary_reader_feeds_the_reports(tmp_path) -> None:
    from bestiary import Bestiary
    from combat_report import ReportBuilder
    logs = tmp_path / "Logs"
    logs.mkdir()
    bestiary = Bestiary(str(tmp_path / "bestiary.json"), str(logs))
    builder = ReportBuilder(str(tmp_path / "reports.json"))
    bestiary.listeners.append(builder)
    (logs / "WoWCombatLog-112326_200000.txt").write_text("\n".join(fight_lines()) + "\n", encoding="utf-8")
    bestiary.read_logs_now()
    assert [r["kind"] for r in builder.latest(5)] == ["clé", "boss"]


def test_reports_tab_renders_without_cut_text(app, tmp_path) -> None:
    app.reports = build(tmp_path)
    app.active_tab = app.TABS.index("Bilans")
    for selected in (0, 1):
        app.state["report_selected"] = selected
        app.draw(app.test_ctx)
        app.screen.cut.clear()
        app.draw(app.test_ctx)
        assert app.screen.cut == []
    folder = os.environ.get("AETHERTWIN_SHOTS")
    if folder:
        import pygame
        Path(folder).mkdir(parents=True, exist_ok=True)
        pygame.image.save(app.screen, os.path.join(folder, "reports_tab.png"))
    from combat_report import ReportBuilder
    app.reports = ReportBuilder(str(tmp_path / "empty.json"))
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
