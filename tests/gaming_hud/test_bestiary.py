"""Bestiaire : journal de combat (fichier) lu par l'appli, butin relevé par l'addon 1.9, onglet."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pygame
import pytest

from tests.gaming_hud.test_addon_lua import ADDON, LOAD, lupa  # noqa: F401  (lupa : test ignoré s'il manque)

ME = 'Player-1390-0ABC,"Sakuranïchan-Nerzhul-EU",0x511,0x0'
BOAR = 'Creature-0-3767-0-1-1125-000ABC,"Sanglier, des rochers",0x10a48,0x0'
WOLF = 'Creature-0-3767-0-1-525-000DEF,"Loup gris",0x10a48,0x0'
BOAR_ADV = "Creature-0-3767-0-1-1125-000ABC,0000000000000000,80,500,0,0,0,0,0,50,100,0,123.4,567.8,2112,1.2,12"
STAMP = "11/23/2026 20:15:03.123-1  "

LINES = [
    f"{STAMP}SPELL_DAMAGE,{ME},{BOAR},8921,\"Éclat lunaire\",0x40,{BOAR_ADV},45,-1,64,0,0,0,nil,nil,nil",
    f"{STAMP}SPELL_CAST_SUCCESS,{BOAR},{ME},3385,\"Charge, sanglier\",0x1,{BOAR_ADV}",
    f"{STAMP}SPELL_CAST_SUCCESS,{BOAR},{ME},3385,\"Charge, sanglier\",0x1,{BOAR_ADV}",
    f"{STAMP}SPELL_CAST_SUCCESS,{WOLF},Creature-0-1-0-1-99-1,\"Autre\",0xa48,0x0,1,\"Morsure\",0x1",
    f"{STAMP}PARTY_KILL,{ME},{BOAR},0",
    f"{STAMP}UNIT_DIED,0000000000000000,nil,0x80000000,0x80000000,{BOAR},0",
    f"{STAMP}UNIT_DIED,0000000000000000,nil,0x80000000,0x80000000,{WOLF},0",   # pas engagé : pas compté
]


def test_parse_line_keeps_commas_inside_names() -> None:
    from bestiary import npc_id, parse_line

    event, fields = parse_line(LINES[1])
    assert event == "SPELL_CAST_SUCCESS" and fields[2] == "Sanglier, des rochers" and fields[10] == "Charge, sanglier"
    assert npc_id(fields[1]) == 1125 and npc_id("Player-1-2") is None and npc_id("Pet-0-1-2-3-4-5") is None


def test_combat_log_kills_abilities_and_stats(tmp_path: Path) -> None:
    from bestiary import Bestiary

    logs = tmp_path / "Logs"
    logs.mkdir()
    log = logs / "WoWCombatLog-112326_201500.txt"
    log.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    store = Bestiary(str(tmp_path / "bestiary.json"), str(logs))
    store.data["created"] = 0           # le fichier est « récent » : lu depuis le début
    store.read_logs_now()
    boar = store.data["creatures"]["1125"]
    assert boar["kills"] == 1 and boar["name"] == "Sanglier, des rochers"
    assert boar["spells"]["3385"] == {"name": "Charge, sanglier", "count": 2}
    assert boar["hp"] == 500 and boar["power"] == 100 and boar["level"] == 12 and boar["maps"] == {"2112": 3}
    assert "525" not in store.data["creatures"] or not store.data["creatures"]["525"].get("kills")

    # le fichier grossit : seule la suite est lue ; une ligne coupée attend la lecture suivante
    with open(log, "a", encoding="utf-8") as f:
        f.write(LINES[0] + "\n" + LINES[4].replace("000ABC", "000ABD") + "\n" + STAMP + "SPELL_DAM")
    store.read_logs_now()
    assert store.data["creatures"]["1125"]["kills"] == 2
    store.set_note(1125, "Charge : s'écarter")

    again = Bestiary(str(tmp_path / "bestiary.json"), str(logs))   # nouveau lancement
    again.read_logs_now()
    assert again.data["creatures"]["1125"]["kills"] == 2 and again.note(1125) == "Charge : s'écarter"


def test_old_logs_are_not_replayed(tmp_path: Path) -> None:
    from bestiary import Bestiary

    logs = tmp_path / "Logs"
    logs.mkdir()
    old = logs / "WoWCombatLog-010126_100000.txt"
    old.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    os.utime(old, (time.time() - 86400, time.time() - 86400))
    store = Bestiary(str(tmp_path / "bestiary.json"), str(logs))
    store.read_logs_now()
    assert store.data["creatures"] == {}


def test_entries_merge_the_addon_loot() -> None:
    from bestiary import merge_entry

    addon = {"name": "Sanglier des rochers", "lvl": 11, "lvlMax": 13, "class": "elite", "ctype": "Bête",
             "zones": {"Elwynn": 3, "Marche de l'Ouest": 1}, "loots": 4, "money": 1000,
             "items": {"769": {"name": "Morceau de sanglier", "q": 1, "n": 3, "c": 5}}}
    e = merge_entry("1125", {"kills": 5, "hp": 500, "spells": {"3385": {"name": "Charge", "count": 2}}}, addon, "")
    assert e["name"] == "Sanglier des rochers" and e["rank"] == "Élite" and e["levelMax"] == 13
    assert e["zones"][0] == "Elwynn" and e["avgMoney"] == 250 and e["loot"][0]["rate"] == 0.75


BEAST_GAME = """
local frame = { RegisterEvent = function() end, SetScript = function() end }
CreateFrame = function() return frame end
SlashCmdList = {}
C_Timer = { After = function() end, NewTicker = function() return {} end }
time = os.time
GetTime = function() return 0 end
InCombatLockdown = function() return false end
strsplit = function(sep, s)
  local out = {}
  for part in (s .. sep):gmatch("(.-)" .. sep) do out[#out + 1] = part end
  return table.unpack(out)
end
local BOAR = "Creature-0-3767-0-1-1125-000ABC"
UnitExists = function() return true end
UnitIsPlayer = function() return false end
UnitGUID = function() return BOAR end
UnitName = function() return "Sanglier" end
UnitLevel = function() return 12 end
UnitClassification = function() return "elite" end
UnitCreatureType = function() return "Bête" end
UnitCreatureFamily = function() return "Sanglier" end
UnitHealthMax = function() return 500 end
UnitPowerMax = function() return 0 end
C_Map = { GetBestMapForUnit = function() return 37 end, GetMapInfo = function() return { name = "Elwynn" } end }
local loot = {
  { type = 1, link = "|cff|Hitem:769::|h[Morceau de sanglier]|h|r", sources = { BOAR, 2 } },
  { type = 2, sources = { BOAR, 125 } },
}
GetNumLootItems = function() return #loot end
GetLootSlotType = function(i) return loot[i].type end
GetLootSlotLink = function(i) return loot[i].link end
GetLootSlotInfo = function(i) return nil, "Morceau de sanglier", 2, nil, 1 end
GetLootSourceInfo = function(i) return table.unpack(loot[i].sources) end
"""


def test_addon_notes_creatures_and_loot() -> None:
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(BEAST_GAME)
    chunk, error = lua.execute(LOAD, ADDON.read_text(encoding="utf-8") + "\nreturn A\n")
    assert chunk is not None, error
    a = chunk("HermesAssistant", lua.table_from({}))
    a.NoteCreature(a, "target")
    a.NoteCreature(a, "target")          # même créature : une seule fiche, une seule visite
    a.NoteLoot(a)
    a.NoteLoot(a)                        # fenêtre de butin rouverte : le corps n'est compté qu'une fois
    boar = lua.globals().HermesAssistantCharDB.bestiary[1125]
    assert boar.name == "Sanglier" and boar.lvl == 12 and boar["class"] == "elite" and boar.hp == 500
    assert boar.zones["Elwynn"] == 1 and boar.loots == 1 and boar.money == 125
    item = boar["items"][769]
    assert item.n == 1 and item.c == 2 and item.name == "Morceau de sanglier"


def test_battle_net_creature_image(tmp_path: Path) -> None:
    from tests.gaming_hud.test_collections_media import CollectionsBnet
    from tests.gaming_hud.test_market import client

    assert client(tmp_path, CollectionsBnet()).creature_image(2671).endswith("npc_2671.jpg")


@pytest.mark.parametrize("filled", [True, False])
def test_bestiary_tab_renders(app, tmp_path: Path, filled: bool) -> None:
    from bestiary import Bestiary
    from media import MediaStore

    image = pygame.Surface((400, 400))
    image.fill((60, 40, 40))
    pygame.image.save(image, str(tmp_path / "npc.png"))

    class FakeApi:
        def configured(self):
            return True

        def creature_image(self, cid):
            return str(tmp_path / "npc.png")

    app.media = MediaStore(FakeApi())
    app.bestiary = Bestiary(str(tmp_path / "bestiary.json"), None)
    if filled:
        app.bestiary.data["creatures"] = {
            "1125": {"name": "Sanglier, des rochers", "kills": 7, "hp": 500, "level": 12, "maps": {"37": 3},
                     "spells": {str(i): {"name": f"Aptitude {i}", "count": 10 - i} for i in range(1, 9)}},
            "525": {"name": "Loup gris", "kills": 0}}
        app.bestiary.set_addon({"1125": {"name": "Sanglier des rochers", "lvl": 11, "lvlMax": 13, "class": "elite",
                                         "ctype": "Bête", "family": "Sanglier", "zones": {"Forêt d'Elwynn": 3},
                                         "loots": 6, "money": 3456,
                                         "items": {str(700 + i): {"name": f"Objet {i}", "q": i % 5, "n": 6 - i % 6,
                                                                  "c": 2} for i in range(10)}}})
        app.bestiary.set_note(1125, "Charge : s'écarter")
    app.active_tab = app.TABS.index("Bestiaire")
    app.draw(app.test_ctx)
    if filled:
        for _ in range(60):
            if app.media.state("npc:1125") == "prête":
                break
            time.sleep(0.05)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    if filled:
        assert app.inputs["bestiary_note"] == "Charge : s'écarter"
    if os.environ.get("AETHERTWIN_SHOTS"):
        pygame.image.save(app.screen, str(Path(os.environ["AETHERTWIN_SHOTS"]) / f"bestiary_{filled}.png"))
