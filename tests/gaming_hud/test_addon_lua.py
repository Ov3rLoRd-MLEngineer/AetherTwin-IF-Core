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
