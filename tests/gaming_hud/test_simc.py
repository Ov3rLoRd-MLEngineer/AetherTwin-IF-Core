"""Profil SimulationCraft construit depuis l'addon, résultat Raidbots collé."""

SNAP = {
    "character": {"name": "Sakuranïchan", "realm": "Hyjal", "region": "EU", "level": 48, "classFile": "DRUID",
                  "raceFile": "NightElf", "specialization": "Farouche"},
    "talents": {"loadout": "CcGADBD3hSPCL9Y9gz68Wc"},
    "professions": [{"name": "Ingénierie", "level": 2}, {"name": "Enchantement", "level": 44}],
    "equipment": [
        {"slot": "1", "id": "153771", "name": "Heaume de la pluie printanière", "ilvl": "17",
         "itemString": "item:153771::::::::48:103::17:1:9370:1:9:47:::::"},
        {"slot": "16", "id": "1", "name": "Bâton", "ilvl": "20",
         "itemString": "item:200000:6643:192985::::::48:103::3:2:1:2:0:::::"},
        {"slot": "4", "id": "45", "name": "Chemise", "itemString": "item:45::::::::48:103:::0:0:::::"},
    ],
}


def test_item_string_is_decoded() -> None:
    import simc
    item = simc.parse_item_string("item:153771::::::::48:103::17:1:9370:1:9:47:::::")
    assert item["id"] == 153771 and item["spec"] == 103 and item["context"] == 17
    assert item["bonus"] == [9370] and item["mods"] == {9: 47}
    assert simc.parse_item_string("bidule") is None


def test_profile_has_the_simulationcraft_fields() -> None:
    import simc
    text = simc.profile(SNAP)
    lines = text.splitlines()
    assert 'druid="Sakuranïchan"' in lines and "spec=feral" in lines and "race=night_elf" in lines
    assert "level=48" in lines and "region=eu" in lines and "server=hyjal" in lines and "role=attack" in lines
    assert "professions=engineering=2/enchanting=44" in lines and "talents=CcGADBD3hSPCL9Y9gz68Wc" in lines
    assert "head=,id=153771,bonus_id=9370,drop_level=47,context=17" in lines
    assert "main_hand=,id=200000,enchant_id=6643,gem_id=192985,bonus_id=1/2,context=3" in lines
    assert not any(line.startswith("shirt=") for line in lines)
    assert simc.profile({}) == ""


def test_raidbots_result_detection() -> None:
    import simc
    page = "Droptimizer - Sakuranïchan\nhttps://www.raidbots.com/simbot/report/abcDEF123\nBottes +3,2 %"
    assert simc.looks_like_result(page) and simc.report_link(page) == "https://www.raidbots.com/simbot/report/abcDEF123"
    assert not simc.looks_like_result("bonjour")


def test_pasted_result_goes_to_the_knowledge_base(app, monkeypatch) -> None:
    import clipboard
    page = ("Droptimizer - Sakuranïchan - https://www.raidbots.com/simbot/report/abcDEF123\n"
            "1. Bottes du Néant +3,2 % (Nalorakk)\n2. Anneau +2,1 %")
    monkeypatch.setattr(clipboard, "get_text", lambda: page)
    asked = []
    app.ask_assistant = lambda title, context, **kw: asked.append(context)
    app.paste_raidbots_result()
    entry = app.knowledge.entries[0]
    assert entry["topic"] == "équipement" and entry["status"] == "joueur"
    assert entry["source"] == "https://www.raidbots.com/simbot/report/abcDEF123"
    assert asked and "Bottes du Néant" in asked[0]
    copied = []
    monkeypatch.setattr(clipboard, "set_text", lambda text: copied.append(text))
    app._open_url = lambda url: copied.append(url)
    app.last_snapshot = SNAP
    app.copy_simc_profile()
    assert copied[0].startswith("# Sakuranïchan") and copied[1].startswith("https://www.raidbots.com/")
    app.active_tab = 0
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
