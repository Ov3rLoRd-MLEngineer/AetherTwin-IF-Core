"""Addon HermesAssistant (Lua) : compilé à chaque lancement des tests (on le modifie sans pouvoir lancer WoW), et
sa collecte Mythique+ exécutée contre de fausses API du jeu."""
from __future__ import annotations

from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

ADDON = (Path(__file__).resolve().parents[2] / "modules" / "gaming_hud" / "addon" / "HermesAssistant"
         / "HermesAssistant.lua")

LOAD = "local f, e = load(...) if f then return f, '' end return false, e"

# Fausses API du jeu : juste assez pour charger le fichier et appeler CollectMythicPlus.
FAKE_GAME = """
local frame = { RegisterEvent = function() end, SetScript = function() end }
CreateFrame = function() return frame end
SlashCmdList = {}
C_Timer = { After = function() end, NewTicker = function() return {} end }
InCombatLockdown = function() return false end
GetTime = function() return 0 end
C_ChallengeMode = {
  GetOverallDungeonScore = function() return 2735 end,
  GetMapTable = function() return { 501, 502 } end,
  GetMapUIInfo = function(id) return ({ [501] = "Cavernes", [502] = "Prieuré" })[id] end,
}
C_MythicPlus = {
  GetOwnedKeystoneChallengeMapID = function() return 502 end,
  GetOwnedKeystoneLevel = function() return 12 end,
  GetSeasonBestAffixScoreInfoForMap = function(id)
    if id == 501 then return { { level = 11, overTime = false }, { level = 9, overTime = true } }, 310 end
    return nil, 0
  end,
  GetRunHistory = function() return { { mapChallengeModeID = 501, level = 11, completed = true } } end,
}
"""


def test_addon_compiles() -> None:
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    chunk, error = lua.execute(LOAD, ADDON.read_text(encoding="utf-8"))
    assert chunk is not None, error


def test_mythic_plus_collection_on_fake_game_api() -> None:
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(FAKE_GAME)
    addon = {}
    # « A » est une variable locale du fichier : on la rend en fin de chargement pour l'appeler
    chunk, error = lua.execute(LOAD, ADDON.read_text(encoding="utf-8") + "\nreturn A\n")
    assert chunk is not None, error
    a = chunk("HermesAssistant", lua.table_from(addon))  # un addon WoW reçoit (nom, table privée)
    out, complete = a.CollectMythicPlus(a)
    assert complete is True and out.score == 2735
    assert out.keystone.name == "Prieuré" and out.keystone.level == 12
    assert out.dungeons[1].name == "Cavernes" and out.dungeons[1].level == 11 and out.dungeons[1].inTime is True
    assert out.dungeons[2].level == 0 and out.week[1].completed is True


BANK_GAME = """
local frame = { RegisterEvent = function() end, SetScript = function() end }
CreateFrame = function() return frame end
SlashCmdList = {}
C_Timer = { After = function() end, NewTicker = function() return {} end }
time = os.time
GetTime = function() return 0 end
InCombatLockdown = function() return false end
local contents = {
  [6] = { { itemID = 2589, hyperlink = "|cff|Hitem:2589|h[Étoffe de lin]|h|r", stackCount = 20, quality = 1 },
          { itemID = 2589, hyperlink = "|cff|Hitem:2589|h[Étoffe de lin]|h|r", stackCount = 5, quality = 1 } },
  [7] = { { itemID = 19019, hyperlink = "[Thunderfury]", stackCount = 1, quality = 5 } },
  [-1] = { { itemID = 7, hyperlink = "[Caillou]", stackCount = 3, quality = 0 } },
  [-3] = {},
}
C_Container = {
  GetContainerNumSlots = function(bag) return contents[bag] and #contents[bag] or 0 end,
  GetContainerItemInfo = function(bag, slot) return contents[bag] and contents[bag][slot] end,
}
"""

NEW_BANK = BANK_GAME + """
Enum = { BankType = { Character = 0, Account = 2 }, BagIndex = { CharacterBankTab_1 = 6, CharacterBankTab_2 = 7 } }
C_Bank = {
  CanViewBank = function() return true end,
  FetchPurchasedBankTabData = function(t) if t == 0 then return { { name = "Minerais" }, { name = "" } } end end,
}
"""

OLD_BANK = BANK_GAME + """
Enum = { BagIndex = { Bank = -1, Reagentbank = -3 } }
"""


def _bank(game: str):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(game)
    chunk, error = lua.execute(LOAD, ADDON.read_text(encoding="utf-8") + "\nreturn A\n")
    assert chunk is not None, error
    a = chunk("HermesAssistant", lua.table_from({}))
    a.ScanCharacterBank(a)
    return lua.globals().HermesAssistantCharDB.characterBank


def test_character_bank_with_tabs() -> None:
    bank = _bank(NEW_BANK)
    assert bank.tabs[1].name == "Minerais" and bank.tabs[2].name == "Onglet 2"
    linen = bank.tabs[1]["items"][1]
    assert linen.id == 2589 and linen.count == 25 and linen.name == "Étoffe de lin"
    assert bank.tabs[2]["items"][1].id == 19019


def test_character_bank_before_tabs() -> None:
    bank = _bank(OLD_BANK)
    assert bank.tabs[1].name == "Banque" and bank.tabs[1]["items"][1].id == 7
    assert bank.tabs[2] is None   # banque de composants vide : pas d'onglet


WAY_GAME = """
local frame = { RegisterEvent = function() end, SetScript = function() end }
CreateFrame = function() return frame end
SlashCmdList = {}
C_Timer = { After = function() end, NewTicker = function() return {} end }
GetTime = function() return 0 end
InCombatLockdown = function() return false end
strtrim = function(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
LOGS = {}
print = function(...) local t = {...} LOGS[#LOGS + 1] = table.concat(t, " ", 2) end
WAYPOINT = nil
UiMapPoint = { CreateFromCoordinates = function(map, x, y) return { map = map, x = x, y = y } end }
C_Map = {
  GetBestMapForUnit = function() return 37 end,
  GetMapInfo = function(id) return ({ [37] = { name = "Forêt d'Elwynn" }, [2112] = { name = "Valdrakken" } })[id] end,
  SetUserWaypoint = function(p) WAYPOINT = p end,
}
C_SuperTrack = { SetSuperTrackedUserWaypoint = function() end }
C_QuestLog = {
  GetNumQuestLogEntries = function() return 3, 2 end,
  GetMaxNumQuestsCanAccept = function() return 35 end,
  GetAllCompletedQuestIDs = function() return { 1, 2 } end,
  GetInfo = function(i)
    return ({ { isHeader = true, title = "Elwynn" }, { questID = 10, title = "Loups" },
              { questID = 11, title = "Ailleurs" } })[i]
  end,
  GetQuestsOnMap = function(map) return { { questID = 10, x = 0.4537, y = 0.6012 } } end,
  GetNextWaypoint = function(id) if id == 11 then return 2112, 0.5, 0.25 end end,
  IsFailed = function() return false end,
  ReadyForTurnIn = function() return false end,
  GetQuestObjectives = function() return {} end,
  GetQuestWatchType = function() return nil end,
}
"""


def _way_addon():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(WAY_GAME)
    chunk, error = lua.execute(LOAD, ADDON.read_text(encoding="utf-8") + "\nreturn A\n")
    assert chunk is not None, error
    return lua, chunk("HermesAssistant", lua.table_from({}))


def test_quests_carry_their_coordinates() -> None:
    _lua, a = _way_addon()
    quests = a.CollectQuests(a)
    here, other = quests.list[1], quests.list[2]
    assert here.way.map == 37 and here.way.x == 45.4 and here.way.y == 60.1 and here.way.zone == "Forêt d'Elwynn"
    assert other.way.map == 2112 and other.way.x == 50 and other.way.y == 25


def test_way_command_sets_a_game_waypoint() -> None:
    lua, _a = _way_addon()
    g = lua.globals()
    g.SlashCmdList.HERMESASSISTANT("way 45,3 60.1 Loups")
    assert g.WAYPOINT.map == 37 and abs(g.WAYPOINT.x - 0.453) < 1e-9 and abs(g.WAYPOINT.y - 0.601) < 1e-9
    g.SlashCmdList.HERMESASSISTANT("way #2112 50 25")
    assert g.WAYPOINT.map == 2112 and "Valdrakken" in g.LOGS[len(g.LOGS)]
    g.SlashCmdList.HERMESASSISTANT("way nulle part")
    assert "Usage" in g.LOGS[len(g.LOGS)]
