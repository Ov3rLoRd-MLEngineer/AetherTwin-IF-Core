-- HermesAssistant.lua  (v1.6)
-- Exporte dans HermesAssistantCharDB : personnage, équipement (avec infobulles), sacs,
-- quêtes, métiers + recettes, temps de jeu (/played), talents, grimoire, hauts faits,
-- collections du bataillon.
-- v1.5 : ne réécrit plus jamais de données vides (déconnexion / rechargement), nouvelles collectes
-- (monnaies, réputations, verrouillages, Grande Chambre forte, banques), analyses complètes
-- (hauts faits, statistiques, montures, mascottes, jouets, héritage, transmogrification) : /ha scan
-- RAPPEL : WoW n'écrit le fichier sur le disque qu'au /reload, /logout ou à la fermeture.
-- Option : /ha auto <minutes> déclenche un /reload automatique (prudent, voir plus bas).

local ADDON_NAME = ...
local A = {}

local MAX_ITEMS = 400
local MAX_QUESTS = 60
local MIN_AUTO_MINUTES = 2
local DEBOUNCE_SECONDS = 3
local TICK_SECONDS = 30
local PLAYED_REFRESH_SECONDS = 600

-- Emplacements d'équipement, dans l'ordre de la fenêtre de personnage
-- colonne gauche : tête, cou, épaules, dos, torse, chemise, tabard, poignets
-- colonne droite : mains, taille, jambes, pieds, anneau 1/2, bijou 1/2
-- bas : main droite, main gauche
local EQUIP_SLOTS = { 1, 2, 3, 15, 5, 4, 19, 9, 10, 6, 7, 8, 11, 12, 13, 14, 16, 17 }

local function Log(...)
    print("|cff33ff99[HermesAssistant]|r", ...)
end

-- Appel protégé : retourne les 5 premières valeurs, ou nil en cas d'erreur / fonction absente
local function try(fn, ...)
    if type(fn) ~= "function" then return nil end
    local ok, a, b, c, d, e, f, g, h = pcall(fn, ...)
    if ok then return a, b, c, d, e, f, g, h end
    return nil
end

local function round1(v)
    if type(v) ~= "number" then return 0 end
    return math.floor(v * 10 + 0.5) / 10
end

local function DB()
    HermesAssistantCharDB = HermesAssistantCharDB or {}
    return HermesAssistantCharDB
end


---------------------------------------------------------------------------
-- Utilitaires : chaînes compactes pour les grandes listes (champs ¦ / enregistrements ¶)
---------------------------------------------------------------------------
local FS, RS = "¦", "¶"

local function clean(v)
    if v == nil then return "" end
    if type(v) == "boolean" then return v and "1" or "0" end
    v = tostring(v)
    v = v:gsub("¦", " "):gsub("¶", " "):gsub("[\r\n\t]", " ")
    return v
end

local function join(...)
    local n = select("#", ...)
    local parts = {}
    for i = 1, n do parts[i] = clean((select(i, ...))) end
    return table.concat(parts, FS)
end

-- coupe à N octets sans laisser un caractère UTF-8 tronqué
local function trim(s, maxBytes)
    if type(s) ~= "string" then return "" end
    if #s <= maxBytes then return s end
    s = s:sub(1, maxBytes)
    s = s:gsub("[\192-\255][\128-\191]*$", "")
    return s
end

local function MarkScan(key)
    local db = DB()
    db.scanInfo = db.scanInfo or {}
    db.scanInfo[key] = time()
end

---------------------------------------------------------------------------
-- Spécialisation (plusieurs API possibles selon la version du jeu)
---------------------------------------------------------------------------
function A:GetSpecName()
    -- 1) index de spécialisation puis informations
    local apis = {
        { C_SpecializationInfo and C_SpecializationInfo.GetSpecialization,
          C_SpecializationInfo and C_SpecializationInfo.GetSpecializationInfo },
        { GetSpecialization, GetSpecializationInfo },
    }
    for _, pair in ipairs(apis) do
        local getIndex, getInfo = pair[1], pair[2]
        if getIndex and getInfo then
            local index = try(getIndex)
            if type(index) == "number" and index > 0 then
                local _, name = try(getInfo, index)
                if type(name) == "string" and name ~= "" then
                    return name
                end
            end
        end
    end
    -- 2) identifiant de spécialisation puis informations par identifiant
    local specID = (PlayerUtil and try(PlayerUtil.GetCurrentSpecID))
        or try(GetInspectSpecialization, "player")
    local byID = GetSpecializationInfoByID
        or (C_SpecializationInfo and C_SpecializationInfo.GetSpecializationInfoByID)
    if type(specID) == "number" and specID > 0 then
        local _, name = try(byID, specID)
        if type(name) == "string" and name ~= "" then return name end
    end
    -- 3) aide de l'interface
    if PlayerUtil and PlayerUtil.GetSpecName then
        local name = try(PlayerUtil.GetSpecName)
        if type(name) == "string" and name ~= "" then return name end
    end
    return ""
end

---------------------------------------------------------------------------
-- Collecte : personnage
---------------------------------------------------------------------------
function A:CollectCharacter()
    local name = try(UnitName, "player")
    if not name or name == "" then return nil end

    local race, raceFile = try(UnitRace, "player")
    local class, classFile = try(UnitClass, "player")

    local d = {
        name = name,
        titleName = try(UnitPVPName, "player") or name,   -- nom + titre, comme dans la fenêtre de personnage
        realm = try(GetRealmName) or "",
        level = try(UnitLevel, "player") or 1,
        race = race or "",
        raceFile = raceFile or "",
        class = class or "",
        classFile = classFile or "",
        faction = try(UnitFactionGroup, "player") or "",
        sex = try(UnitSex, "player") or 0,
        xp = try(UnitXP, "player") or 0,
        xpMax = try(UnitXPMax, "player") or 0,
        restedXP = try(GetXPExhaustion) or 0,
        money = try(GetMoney) or 0,
        zone = try(GetZoneText) or "",
        subzone = try(GetSubZoneText) or "",
        specialization = A:GetSpecName(),
        ilvl = 0,
        stats = {},
        updated = time(),
    }

    if d.specialization == "" then
        local prev = DB().characterData
        if prev and prev.name == name and type(prev.specialization) == "string" then
            d.specialization = prev.specialization
        end
    end

    -- Niveau d'objet équipé
    local _, equipped = try(GetAverageItemLevel)
    if type(equipped) == "number" then
        d.ilvl = round1(equipped)
    end

    -- Caractéristiques principales
    local statKeys = { "strength", "agility", "stamina", "intellect", "spirit" }
    for i, key in ipairs(statKeys) do
        local _, effective = try(UnitStat, "player", i)
        d.stats[key] = effective or 0
    end

    -- Armure et améliorations (critique, hâte, maîtrise, polyvalence)
    local _, armor = try(UnitArmor, "player")
    d.armor = armor or 0
    d.crit = round1(try(GetCritChance))
    d.haste = round1(try(GetHaste))
    d.mastery = round1(try(GetMasteryEffect))
    local vers = (try(GetCombatRatingBonus, CR_VERSATILITY_DAMAGE_DONE) or 0)
               + (try(GetVersatilityBonus, CR_VERSATILITY_DAMAGE_DONE) or 0)
    d.versatility = round1(vers)

    return d
end

function A:CollectProfessions()
    local list = {}
    local p1, p2, archaeology, fishing, cooking = try(GetProfessions)
    local indices = { p1, p2, archaeology, fishing, cooking }
    for i = 1, 5 do
        local idx = indices[i]
        if idx then
            local name, _, skill, maxSkill = try(GetProfessionInfo, idx)
            if name then
                list[#list + 1] = { name = name, level = skill or 0, max = maxSkill or 0 }
            end
        end
    end
    return list
end

---------------------------------------------------------------------------
-- Collecte : équipement + infobulles
---------------------------------------------------------------------------
local function hexColor(c)
    if type(c) ~= "table" or type(c.r) ~= "number" then return "ffffff" end
    return string.format("%02x%02x%02x",
        math.floor(c.r * 255 + 0.5), math.floor((c.g or 1) * 255 + 0.5), math.floor((c.b or 1) * 255 + 0.5))
end

-- Lignes de l'infobulle d'un objet équipé : { {l = gauche, r = droite, c = "rrggbb"}, ... }
function A:GetTooltipLines(slot)
    local lines = {}

    -- 1) API moderne
    if C_TooltipInfo and C_TooltipInfo.GetInventoryItem then
        local data = try(C_TooltipInfo.GetInventoryItem, "player", slot)
        if type(data) == "table" and type(data.lines) == "table" then
            if TooltipUtil and TooltipUtil.SurfaceArgs then pcall(TooltipUtil.SurfaceArgs, data) end
            for _, line in ipairs(data.lines) do
                if TooltipUtil and TooltipUtil.SurfaceArgs then pcall(TooltipUtil.SurfaceArgs, line) end
                local l, r = line.leftText, line.rightText
                if type(l) ~= "string" then l = "" end
                if type(r) ~= "string" then r = "" end
                if l ~= "" or r ~= "" then
                    lines[#lines + 1] = { l = l, r = r, c = hexColor(line.leftColor) }
                    if #lines >= 40 then break end
                end
            end
        end
    end
    if #lines > 0 then return lines end

    -- 2) Repli : lecture d'une infobulle cachée
    pcall(function()
        local tip = A.scanTip
        if not tip then
            tip = CreateFrame("GameTooltip", "HermesAssistantScanTip", UIParent, "GameTooltipTemplate")
            A.scanTip = tip
        end
        tip:SetOwner(UIParent, "ANCHOR_NONE")
        tip:ClearLines()
        tip:SetInventoryItem("player", slot)
        for i = 1, tip:NumLines() do
            local left = _G["HermesAssistantScanTipTextLeft" .. i]
            local right = _G["HermesAssistantScanTipTextRight" .. i]
            local l = left and left:GetText() or ""
            local r = right and right:GetText() or ""
            if type(l) ~= "string" then l = "" end
            if type(r) ~= "string" then r = "" end
            if l ~= "" or r ~= "" then
                local cr, cg, cb = 1, 1, 1
                if left then cr, cg, cb = left:GetTextColor() end
                lines[#lines + 1] = { l = l, r = r, c = hexColor({ r = cr, g = cg, b = cb }) }
                if #lines >= 40 then break end
            end
        end
    end)
    return lines
end

function A:CollectEquipment(force)
    local out = {}
    A.tooltipCache = A.tooltipCache or {}
    local level = try(UnitLevel, "player") or 0

    for _, slot in ipairs(EQUIP_SLOTS) do
        local link = try(GetInventoryItemLink, "player", slot)
        if type(link) == "string" then
            local itemString = link:match("|H(item:[^|]*)|h")
            local itemID = itemString and tonumber(itemString:match("^item:(%d+)"))
            if itemID then
                -- L'infobulle ne change que si l'objet ou le niveau change : on la met en cache
                local key = itemString .. "@" .. level
                local cached = A.tooltipCache[slot]
                if force or not cached or cached.key ~= key then
                    cached = { key = key, lines = A:GetTooltipLines(slot) }
                    A.tooltipCache[slot] = cached
                end

                local ilvl
                if ItemLocation and C_Item and C_Item.GetCurrentItemLevel then
                    local loc = try(ItemLocation.CreateFromEquipmentSlot, ItemLocation, slot)
                    if loc then ilvl = try(C_Item.GetCurrentItemLevel, loc) end
                end
                if not ilvl then ilvl = (try(GetDetailedItemLevelInfo, link)) end

                local cur, max = try(GetInventoryItemDurability, slot)
                out[#out + 1] = {
                    slot = slot,
                    id = itemID,
                    name = link:match("%[(.-)%]") or "",
                    itemString = itemString,   -- sert à fabriquer le lien Wowhead (id, bonus, gemmes, enchant)
                    quality = try(GetInventoryItemQuality, "player", slot) or 1,
                    ilvl = ilvl or 0,
                    icon = try(GetInventoryItemTexture, "player", slot),
                    durability = cur,
                    maxDurability = max,
                    tooltip = cached.lines,
                }
            end
        else
            A.tooltipCache[slot] = nil
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Collecte : sacs et quêtes
---------------------------------------------------------------------------
function A:CollectInventory()
    local inv = { capacity = 0, used = 0, items = {} }
    if not C_Container then return inv end

    local instant = (C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    local lastBag = NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4
    local byId = {}

    for bag = 0, lastBag do
        local slots = try(C_Container.GetContainerNumSlots, bag) or 0
        local free = try(C_Container.GetContainerNumFreeSlots, bag) or 0
        inv.capacity = inv.capacity + slots
        inv.used = inv.used + (slots - free)

        for slot = 1, slots do
            local info = try(C_Container.GetContainerItemInfo, bag, slot)
            if info and info.itemID then
                local entry = byId[info.itemID]
                if not entry then
                    local itemName = ""
                    if info.hyperlink then
                        itemName = info.hyperlink:match("%[(.-)%]") or ""
                    end
                    local itemType = (select(2, try(instant, info.itemID))) or ""
                    entry = {
                        id = info.itemID,
                        name = itemName,
                        count = 0,
                        type = itemType,
                        quality = info.quality or 0,
                    }
                    byId[info.itemID] = entry
                    inv.items[#inv.items + 1] = entry
                end
                entry.count = entry.count + (info.stackCount or 1)
            end
        end
    end

    table.sort(inv.items, function(a, b) return (a.name or "") < (b.name or "") end)
    while #inv.items > MAX_ITEMS do
        table.remove(inv.items)
    end
    return inv
end

function A:CollectQuests()
    local out = { count = 0, max = 35, valid = false, list = {} }
    if not (C_QuestLog and C_QuestLog.GetNumQuestLogEntries) then return out end

    local numEntries, numQuests = try(C_QuestLog.GetNumQuestLogEntries)
    if numEntries == nil then return out end   -- API pas prête : on garde l'ancien journal
    out.valid = true
    out.count = numQuests or 0
    out.max = try(C_QuestLog.GetMaxNumQuestsCanAccept) or 35

    if not A.completedAt or (GetTime() - A.completedAt) > 120 then
        local done = try(C_QuestLog.GetAllCompletedQuestIDs)
        A.completedTotal = type(done) == "table" and #done or (A.completedTotal or 0)
        A.completedAt = GetTime()
    end
    out.completedTotal = A.completedTotal or 0

    local superID = C_SuperTrackedQuest and try(C_SuperTrackedQuest.GetSuperTrackedQuestID)
    local zone = ""
    for i = 1, numEntries do
        if #out.list >= MAX_QUESTS then break end
        local info = try(C_QuestLog.GetInfo, i)
        if info then
            if info.isHeader then
                zone = info.title or ""
            elseif info.questID and not info.isHidden then
                local id = info.questID
                local status = "incomplete"
                if try(C_QuestLog.IsFailed, id) then
                    status = "failed"
                elseif try(C_QuestLog.ReadyForTurnIn, id) then
                    status = "complete"
                end

                local objectives = {}
                local objs = try(C_QuestLog.GetQuestObjectives, id)
                if type(objs) == "table" then
                    for _, o in ipairs(objs) do
                        if o.text and o.text ~= "" then
                            objectives[#objectives + 1] = {
                                text = o.text, done = o.finished and true or false,
                                have = o.numFulfilled or 0, need = o.numRequired or 0, kind = o.type or "",
                            }
                        end
                    end
                end

                local rewards = {}
                local nRewards = try(GetNumQuestLogRewards, id) or 0
                for k = 1, math.min(nRewards, 4) do
                    local name, _, count, quality = try(GetQuestLogRewardInfo, k, id)
                    if name then rewards[#rewards + 1] = { name = name, count = count or 1, quality = quality or 1 } end
                end

                out.list[#out.list + 1] = {
                    id = id,
                    title = info.title or "",
                    level = info.level or info.questLevel or 0,
                    zone = zone,
                    status = status,
                    task = info.isTask and true or false,
                    freq = info.frequency or 0,
                    tracked = try(C_QuestLog.GetQuestWatchType, id) ~= nil,
                    focus = (superID ~= nil and superID == id),
                    rewardXP = try(GetQuestLogRewardXP, id) or 0,
                    rewardMoney = try(GetQuestLogRewardMoney, id) or 0,
                    rewards = rewards,
                    objectives = objectives,
                }
            end
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Talents, grimoire, hauts faits, collections du bataillon, recettes
-- (collectes "paresseuses" : refaites seulement quand un événement les invalide)
---------------------------------------------------------------------------
function A:CollectTalents()
    local out = { points = 0, nodes = {}, loadout = "", hero = "" }
    if not (C_ClassTalents and C_Traits) then return out end
    local configID = try(C_ClassTalents.GetActiveConfigID)
    if not configID then return out end
    local config = try(C_Traits.GetConfigInfo, configID)
    if type(config) ~= "table" or type(config.treeIDs) ~= "table" then return out end

    local spellName = (C_Spell and C_Spell.GetSpellName) or GetSpellInfo
    for _, treeID in ipairs(config.treeIDs) do
        local nodeIDs = try(C_Traits.GetTreeNodes, treeID)
        for _, nodeID in ipairs(type(nodeIDs) == "table" and nodeIDs or {}) do
            if #out.nodes >= 150 then break end
            local node = try(C_Traits.GetNodeInfo, configID, nodeID)
            if type(node) == "table" and node.isVisible and (node.currentRank or 0) > 0 then
                local entryID = node.activeEntry and node.activeEntry.entryID
                local entry = entryID and try(C_Traits.GetEntryInfo, configID, entryID)
                local def = entry and entry.definitionID and try(C_Traits.GetDefinitionInfo, entry.definitionID)
                local spellID = def and (def.overriddenSpellID or def.spellID)
                out.nodes[#out.nodes + 1] = {
                    id = nodeID,
                    spellID = spellID or 0,
                    name = spellID and (try(spellName, spellID)) or "",
                    rank = node.currentRank,
                    maxRank = node.maxRanks or 1,
                    x = node.posX or 0,
                    y = node.posY or 0,
                }
                out.points = out.points + node.currentRank
            end
        end
    end
    table.sort(out.nodes, function(a, b)
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)

    local loadout = try(C_Traits.GenerateImportString, configID)
    if type(loadout) == "string" then out.loadout = loadout end
    local heroID = try(C_ClassTalents.GetActiveHeroTalentSpec)
    if heroID and C_Traits.GetSubTreeInfo then
        local sub = try(C_Traits.GetSubTreeInfo, configID, heroID)
        if type(sub) == "table" and type(sub.name) == "string" then out.hero = sub.name end
    end
    return out, #out.nodes > 0
end

function A:CollectSpellbook()
    local out = {}
    if not (C_SpellBook and C_SpellBook.GetNumSpellBookSkillLines) then return out end
    local bank = (Enum and Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Player) or 0
    local spellType = Enum and Enum.SpellBookItemType and Enum.SpellBookItemType.Spell
    local lineCount = try(C_SpellBook.GetNumSpellBookSkillLines) or 0

    for i = 1, lineCount do
        local line = try(C_SpellBook.GetSpellBookSkillLineInfo, i)
        if type(line) == "table" and not line.shouldHide and not line.offSpecID then
            local spells = {}
            local first = (line.itemIndexOffset or 0) + 1
            for index = first, first + (line.numSpellBookItems or 0) - 1 do
                local item = try(C_SpellBook.GetSpellBookItemInfo, index, bank)
                if type(item) == "table" and item.spellID and (not spellType or item.itemType == spellType) then
                    local name = item.name
                    if type(name) ~= "string" or name == "" then
                        name = try(C_SpellBook.GetSpellBookItemName, index, bank)
                    end
                    if type(name) == "string" and name ~= "" and #spells < 150 then
                        spells[#spells + 1] = { id = item.spellID, name = name, passive = item.isPassive and true or false }
                    end
                end
            end
            if #spells > 0 then
                out[#out + 1] = { name = line.name or "", spells = spells }
            end
        end
    end
    return out, #out > 0
end

function A:CollectAchievements()
    local out = { points = 0, completed = 0, total = 0, categories = {}, recent = {} }
    out.points = try(GetTotalAchievementPoints) or 0
    local total, completed = try(GetNumCompletedAchievements)
    out.total, out.completed = total or 0, completed or 0

    local categories = try(GetCategoryList)
    for _, id in ipairs(type(categories) == "table" and categories or {}) do
        local title, parentID = try(GetCategoryInfo, id)
        if title and (parentID == -1 or parentID == false or parentID == nil) then
            local numItems, numCompleted = try(GetCategoryNumAchievements, id, true)
            if (numItems or 0) > 0 and #out.categories < 30 then
                out.categories[#out.categories + 1] = { id = id, name = title, total = numItems, completed = numCompleted or 0 }
            end
        end
    end

    local a, b, c, d, e = try(GetLatestCompletedAchievements)
    for _, id in ipairs({ a, b, c, d, e }) do
        if id then
            local _, name, points, done, month, day, year, description = try(GetAchievementInfo, id)
            if name then
                local date = ""
                if month and day and year then
                    date = string.format("%02d/%02d/%d", day, month, year < 100 and 2000 + year or year)
                end
                out.recent[#out.recent + 1] = { id = id, name = name, points = points or 0,
                                                date = date, description = description or "" }
            end
        end
    end
    return out, (out.points > 0 or out.total > 0)
end

function A:CollectCollections()
    local out = {
        mounts = { total = 0, collected = 0, list = {} },
        pets = { total = 0, owned = 0 },
        toys = { total = 0, collected = 0 },
        heirlooms = { total = 0, known = 0 },
        warbandMoney = 0,
    }

    if C_MountJournal and C_MountJournal.GetMountIDs then
        local ids = try(C_MountJournal.GetMountIDs)
        for _, mountID in ipairs(type(ids) == "table" and ids or {}) do
            -- GetMountInfoByID renvoie 13 valeurs : on garde le résultat complet
            local r = { pcall(C_MountJournal.GetMountInfoByID, mountID) }
            if r[1] then
                local hidden, collected = r[11], r[12]
                if not hidden then
                    out.mounts.total = out.mounts.total + 1
                    if collected then
                        out.mounts.collected = out.mounts.collected + 1
                        if #out.mounts.list < 800 then
                            out.mounts.list[#out.mounts.list + 1] = { id = mountID, spellID = r[3] or 0, name = r[2] or "" }
                        end
                    end
                end
            end
        end
        table.sort(out.mounts.list, function(a, b) return (a.name or "") < (b.name or "") end)
    end

    if C_PetJournal and C_PetJournal.GetNumPets then
        local numPets, numOwned = try(C_PetJournal.GetNumPets)
        out.pets.total, out.pets.owned = numPets or 0, numOwned or 0
    end

    if C_ToyBox then
        out.toys.total = try(C_ToyBox.GetNumTotalDisplayedToys) or 0
        out.toys.collected = try(C_ToyBox.GetNumLearnedDisplayedToys) or 0
    end

    if C_Heirloom and C_Heirloom.GetHeirloomItemIDs then
        local ids = try(C_Heirloom.GetHeirloomItemIDs)
        for _, itemID in ipairs(type(ids) == "table" and ids or {}) do
            out.heirlooms.total = out.heirlooms.total + 1
            if try(C_Heirloom.PlayerHasHeirloom, itemID) then out.heirlooms.known = out.heirlooms.known + 1 end
        end
    end

    if C_Bank and C_Bank.FetchDepositedMoney and Enum and Enum.BankType then
        out.warbandMoney = try(C_Bank.FetchDepositedMoney, Enum.BankType.Account) or 0
    end
    return out, out.mounts.total > 0
end

-- Recettes : lues quand la fenêtre d'un métier est ouverte (l'API n'existe pas autrement)
function A:ScanRecipes()
    if not (C_TradeSkillUI and C_TradeSkillUI.GetBaseProfessionInfo) then return end
    if try(C_TradeSkillUI.IsTradeSkillLinked) or try(C_TradeSkillUI.IsTradeSkillGuild) then return end
    local base = try(C_TradeSkillUI.GetBaseProfessionInfo)
    local profession = type(base) == "table" and base.professionName
    if type(profession) ~= "string" or profession == "" then return end

    local basicType = Enum and Enum.CraftingReagentType and Enum.CraftingReagentType.Basic
    local itemName = (C_Item and C_Item.GetItemNameByID) or GetItemInfo
    local ids = try(C_TradeSkillUI.GetAllRecipeIDs)
    local list = {}
    for _, recipeID in ipairs(type(ids) == "table" and ids or {}) do
        if #list >= 400 then break end
        local info = try(C_TradeSkillUI.GetRecipeInfo, recipeID)
        if type(info) == "table" and info.learned and type(info.name) == "string" then
            local mats = {}
            local schematic = try(C_TradeSkillUI.GetRecipeSchematic, recipeID, false)
            if type(schematic) == "table" and type(schematic.reagentSlotSchematics) == "table" then
                for _, slot in ipairs(schematic.reagentSlotSchematics) do
                    if slot.reagentType == basicType and type(slot.reagents) == "table" and #slot.reagents > 0 then
                        local itemIDs = {}
                        for _, reagent in ipairs(slot.reagents) do
                            if reagent.itemID then itemIDs[#itemIDs + 1] = reagent.itemID end
                        end
                        if #itemIDs > 0 then
                            local n = try(itemName, itemIDs[1])
                            mats[#mats + 1] = { ids = itemIDs, quantity = slot.quantityRequired or 1,
                                                name = type(n) == "string" and n or "" }
                        end
                    end
                end
            end
            list[#list + 1] = { id = recipeID, name = info.name, mats = mats }
        end
    end
    if #list > 0 then
        local db = DB()
        db.recipes = db.recipes or {}
        db.recipes[profession] = { updated = time(), list = list }
    end
end

---------------------------------------------------------------------------
-- Monnaies, réputations, verrouillages, Grande Chambre forte (collectes légères)
---------------------------------------------------------------------------
function A:CollectCurrencies()
    local out = {}
    if not (C_CurrencyInfo and C_CurrencyInfo.GetCurrencyListSize) then return out end
    local size = try(C_CurrencyInfo.GetCurrencyListSize) or 0
    local group = ""
    for i = 1, size do
        local info = try(C_CurrencyInfo.GetCurrencyListInfo, i)
        if type(info) == "table" then
            if info.isHeader then
                group = info.name or ""
            elseif not info.isTypeUnused and info.name then
                local id = info.currencyTypesID
                if not id then
                    local link = try(C_CurrencyInfo.GetCurrencyListLink, i)
                    if type(link) == "string" then id = tonumber(link:match("currency:(%d+)")) end
                end
                out[#out + 1] = {
                    id = id or 0, name = info.name, group = group,
                    quantity = info.quantity or 0, max = info.maxQuantity or 0,
                    weekly = info.quantityEarnedThisWeek or 0, weeklyMax = info.maxWeeklyQuantity or 0,
                    total = info.totalEarned or 0,
                }
            end
        end
    end
    return out, #out > 0
end

function A:CollectFactions()
    local out = {}
    if not (C_Reputation and C_Reputation.GetNumFactions) then return out end
    local count = try(C_Reputation.GetNumFactions) or 0
    local group = ""
    for i = 1, count do
        local d = try(C_Reputation.GetFactionDataByIndex, i)
        if type(d) == "table" and d.name then
            if d.isHeader and not d.isHeaderWithRep then
                group = d.name
            else
                local entry = { id = d.factionID or 0, name = d.name, group = group, kind = "normal",
                                reaction = d.reaction or 0, atWar = d.atWarWith and true or false,
                                cur = 0, max = 1, label = "" }
                if C_Reputation.IsMajorFaction and try(C_Reputation.IsMajorFaction, d.factionID) then
                    local m = C_MajorFactions and try(C_MajorFactions.GetMajorFactionData, d.factionID)
                    if type(m) == "table" then
                        entry.kind = "renown"
                        entry.cur = m.renownReputationEarned or 0
                        entry.max = m.renownLevelThreshold or 1
                        entry.label = "Renom " .. tostring(m.renownLevel or 0)
                    end
                else
                    local f = C_GossipInfo and try(C_GossipInfo.GetFriendshipReputation, d.factionID)
                    if type(f) == "table" and (f.friendshipFactionID or 0) > 0 then
                        entry.kind = "friend"
                        entry.cur = (f.standing or 0) - (f.reactionThreshold or 0)
                        entry.max = math.max(1, (f.nextThreshold or (f.standing or 0) + 1) - (f.reactionThreshold or 0))
                        entry.label = f.reaction or ""
                    else
                        entry.cur = (d.currentStanding or 0) - (d.currentReactionThreshold or 0)
                        entry.max = math.max(1, (d.nextReactionThreshold or 1) - (d.currentReactionThreshold or 0))
                        entry.label = _G["FACTION_STANDING_LABEL" .. tostring(d.reaction or 0)] or ""
                    end
                end
                out[#out + 1] = entry
            end
        end
    end
    return out, #out > 0
end

function A:CollectLockouts()
    local out = { instances = {}, worldBosses = {} }
    local count = try(GetNumSavedInstances) or 0
    for i = 1, count do
        -- GetSavedInstanceInfo renvoie 13 valeurs : on garde le résultat complet
        local r = { pcall(GetSavedInstanceInfo, i) }
        if r[1] and r[6] then   -- verrouillé
            local bosses = {}
            for j = 1, (r[12] or 0) do
                local b = { pcall(GetSavedInstanceEncounterInfo, i, j) }
                if b[1] and b[2] then bosses[#bosses + 1] = { name = b[2], killed = b[4] and true or false } end
            end
            out.instances[#out.instances + 1] = {
                name = r[2], id = r[3], expires = time() + (r[4] or 0), difficulty = r[11] or "",
                isRaid = r[9] and true or false, players = r[10] or 0,
                progress = r[13] or 0, total = r[12] or 0, bosses = bosses,
            }
        end
    end
    local worldCount = try(GetNumSavedWorldBosses) or 0
    for i = 1, worldCount do
        local name, id, reset = try(GetSavedWorldBossInfo, i)
        if name then out.worldBosses[#out.worldBosses + 1] = { name = name, id = id or 0, expires = time() + (reset or 0) } end
    end
    return out, true
end

function A:CollectVault()
    local out = { activities = {}, canClaim = false, hasRewards = false }
    if not (C_WeeklyRewards and C_WeeklyRewards.GetActivities) then return out end
    local acts = try(C_WeeklyRewards.GetActivities)
    for _, a in ipairs(type(acts) == "table" and acts or {}) do
        out.activities[#out.activities + 1] = {
            type = a.type or 0, index = a.index or 0, threshold = a.threshold or 0,
            progress = a.progress or 0, level = a.level or 0, id = a.id or 0,
        }
    end
    out.canClaim = try(C_WeeklyRewards.CanClaimRewards) and true or false
    out.hasRewards = try(C_WeeklyRewards.HasAvailableRewards) and true or false
    return out, #out.activities > 0
end

---------------------------------------------------------------------------
-- Banques (lues quand elles sont ouvertes) et journal d'événements
---------------------------------------------------------------------------
local function ScanBags(bagIDs)
    local byId, list = {}, {}
    for _, bag in ipairs(bagIDs) do
        local slots = try(C_Container.GetContainerNumSlots, bag) or 0
        for slot = 1, slots do
            local info = try(C_Container.GetContainerItemInfo, bag, slot)
            if info and info.itemID then
                local e = byId[info.itemID]
                if not e then
                    e = { id = info.itemID, name = info.hyperlink and info.hyperlink:match("%[(.-)%]") or "",
                          count = 0, quality = info.quality or 0, type = "" }
                    byId[info.itemID] = e
                    list[#list + 1] = e
                end
                e.count = e.count + (info.stackCount or 1)
            end
        end
    end
    table.sort(list, function(a, b) return (a.name or "") < (b.name or "") end)
    return list
end

function A:ScanWarbandBank()
    if not (C_Bank and C_Container and Enum and Enum.BankType) then return end
    local bankType = Enum.BankType.Account
    if not try(C_Bank.CanViewBank, bankType) then return end
    local tabData = try(C_Bank.FetchPurchasedBankTabData, bankType)
    if type(tabData) ~= "table" or #tabData == 0 then return end
    local tabs = {}
    for idx, t in ipairs(tabData) do
        local bagID = (Enum.BagIndex and Enum.BagIndex["AccountBankTab_" .. idx]) or (12 + idx)
        tabs[#tabs + 1] = { name = t.name or ("Onglet " .. idx), items = ScanBags({ bagID }) }
    end
    DB().warbandBank = { updated = time(), money = try(C_Bank.FetchDepositedMoney, bankType) or 0, tabs = tabs }
end

function A:ScanGuildBankTab()
    if type(GetCurrentGuildBankTab) ~= "function" then return end
    local tab = try(GetCurrentGuildBankTab)
    if not tab then return end
    local byId, list = {}, {}
    for slot = 1, 98 do
        local link = try(GetGuildBankItemLink, tab, slot)
        if type(link) == "string" then
            local id = tonumber(link:match("item:(%d+)"))
            if id then
                local _, count, _, _, quality = try(GetGuildBankItemInfo, tab, slot)
                local e = byId[id]
                if not e then
                    e = { id = id, name = link:match("%[(.-)%]") or "", count = 0, quality = quality or 1, type = "" }
                    byId[id] = e
                    list[#list + 1] = e
                end
                e.count = e.count + (count or 1)
            end
        end
    end
    table.sort(list, function(a, b) return (a.name or "") < (b.name or "") end)
    local db = DB()
    db.guildBank = db.guildBank or { tabs = {} }
    db.guildBank.guild = (try(GetGuildInfo, "player")) or db.guildBank.guild or ""
    db.guildBank.money = try(GetGuildBankMoney) or db.guildBank.money or 0
    db.guildBank.tabs[tab] = { name = (try(GetGuildBankTabInfo, tab)) or ("Onglet " .. tab), items = list, updated = time() }
    db.guildBank.updated = time()
end

function A:AddLog(kind, text)
    local db = DB()
    db.log = db.log or {}
    db.log[#db.log + 1] = { t = time(), kind = kind, text = text }
    while #db.log > 300 do table.remove(db.log, 1) end
end

---------------------------------------------------------------------------
-- Analyses complètes, découpées en petits morceaux (une portion par image : aucun à-coup)
-- /ha scan  [hautsfaits|statistiques|montures|mascottes|jouets|heritage|transmog|ensembles]
---------------------------------------------------------------------------
function A:RunChunked(total, perChunk, stepFn, doneFn)
    local index = 0
    local function chunk()
        if InCombatLockdown() then C_Timer.After(3, chunk) return end
        local last = math.min(index + perChunk, total)
        for k = index + 1, last do pcall(stepFn, k) end
        index = last
        if index < total then C_Timer.After(0, chunk) else pcall(doneFn) end
    end
    if total <= 0 then pcall(doneFn) else chunk() end
end

function A:ScanAchievements(done)
    local cats = try(GetCategoryList)
    if type(cats) ~= "table" then return done() end
    local catRows, lists = {}, {}
    for _, id in ipairs(cats) do
        local title, parentID = try(GetCategoryInfo, id)
        local total, completed = try(GetCategoryNumAchievements, id, false)
        catRows[#catRows + 1] = join(id, title, type(parentID) == "number" and parentID or -1, total or 0, completed or 0)
    end
    A:RunChunked(#cats, 3, function(i)
        local id = cats[i]
        local n = try(GetCategoryNumAchievements, id, false) or 0
        local out = {}
        for j = 1, n do
            local aid, name, points, completed, month, day, year, desc = try(GetAchievementInfo, id, j)
            if aid and name then
                local date = ""
                if completed and month and day and year then
                    date = string.format("%02d/%02d/%d", day, month, year < 100 and 2000 + year or year)
                end
                out[#out + 1] = join(aid, name, points or 0, completed and 1 or 0, date, trim(desc, 140))
            end
        end
        lists[id] = table.concat(out, RS)
    end, function()
        DB().achv = { updated = time(), cats = table.concat(catRows, RS), list = lists }
        MarkScan("achievements")
        done()
    end)
end

function A:ScanStatistics(done)
    local cats = try(GetStatisticsCategoryList)
    if type(cats) ~= "table" then return done() end
    local catRows, lists = {}, {}
    for _, id in ipairs(cats) do
        local title, parentID = try(GetCategoryInfo, id)
        catRows[#catRows + 1] = join(id, title, type(parentID) == "number" and parentID or -1)
    end
    A:RunChunked(#cats, 4, function(i)
        local id = cats[i]
        local n = try(GetCategoryNumAchievements, id, false) or 0
        local out = {}
        for j = 1, n do
            local sid, name = try(GetAchievementInfo, id, j)
            if sid and name then
                out[#out + 1] = join(sid, name, try(GetStatistic, sid) or "--")
            end
        end
        lists[id] = table.concat(out, RS)
    end, function()
        DB().stats = { updated = time(), cats = table.concat(catRows, RS), list = lists }
        MarkScan("statistics")
        done()
    end)
end

function A:ScanMounts(done)
    local ids = C_MountJournal and try(C_MountJournal.GetMountIDs)
    if type(ids) ~= "table" then return done() end
    local rows = {}
    A:RunChunked(#ids, 30, function(i)
        local mountID = ids[i]
        local r = { pcall(C_MountJournal.GetMountInfoByID, mountID) }
        if r[1] and not r[11] then   -- pas masquée
            local extra = { pcall(C_MountJournal.GetMountInfoExtraByID, mountID) }
            rows[#rows + 1] = join(mountID, r[3], r[2], r[12], r[7], r[8],
                trim(extra[1] and extra[4] or "", 160), trim(extra[1] and extra[3] or "", 200))
        end
    end, function()
        DB().mounts = { updated = time(), list = table.concat(rows, RS) }
        MarkScan("mounts")
        done()
    end)
end

function A:ScanPets(done)
    if not (C_PetJournal and C_PetJournal.GetNumPets) then return done() end
    local numPets = try(C_PetJournal.GetNumPets) or 0
    local species = {}
    A:RunChunked(numPets, 40, function(i)
        local r = { pcall(C_PetJournal.GetPetInfoByIndex, i) }
        if r[1] and r[3] then
            local sid = r[3]
            local sp = species[sid]
            if not sp then
                sp = { id = sid, name = r[9] or "", owned = 0, level = 0, rarity = 0, ptype = r[11] or 0,
                       creature = r[12] or 0, source = trim(r[13] or "", 160), desc = trim(r[14] or "", 220),
                       battle = r[16] and 1 or 0 }
                species[sid] = sp
            end
            if r[4] then
                sp.owned = sp.owned + 1
                sp.level = math.max(sp.level, r[6] or 0)
                if r[2] then
                    local st = { pcall(C_PetJournal.GetPetStats, r[2]) }
                    if st[1] and type(st[6]) == "number" then sp.rarity = math.max(sp.rarity, st[6]) end
                end
            end
        end
    end, function()
        local rows = {}
        for _, sp in pairs(species) do
            rows[#rows + 1] = join(sp.id, sp.name, sp.owned, sp.level, sp.rarity, sp.ptype, sp.creature,
                                   sp.source, sp.desc, sp.battle)
        end
        DB().pets = { updated = time(), list = table.concat(rows, RS) }
        MarkScan("pets")
        done()
    end)
end

function A:ScanToys(done)
    if not C_ToyBox then return done() end
    local n = try(C_ToyBox.GetNumTotalDisplayedToys) or 0
    local rows = {}
    A:RunChunked(n, 40, function(i)
        local itemID = try(C_ToyBox.GetToyFromIndex, i)
        if itemID and itemID > 0 then
            local _, name, _, _, _, quality = try(C_ToyBox.GetToyInfo, itemID)
            rows[#rows + 1] = join(itemID, name, PlayerHasToy and PlayerHasToy(itemID), quality or 1)
        end
    end, function()
        DB().toys = { updated = time(), list = table.concat(rows, RS) }
        MarkScan("toys")
        done()
    end)
end

function A:ScanHeirlooms(done)
    local ids = C_Heirloom and try(C_Heirloom.GetHeirloomItemIDs)
    if type(ids) ~= "table" then return done() end
    local rows = {}
    A:RunChunked(#ids, 40, function(i)
        local itemID = ids[i]
        local name, equipLoc, _, _, _, source = try(C_Heirloom.GetHeirloomInfo, itemID)
        rows[#rows + 1] = join(itemID, name, try(C_Heirloom.PlayerHasHeirloom, itemID), equipLoc, trim(source, 120))
    end, function()
        DB().heirlooms = { updated = time(), list = table.concat(rows, RS) }
        MarkScan("heirlooms")
        done()
    end)
end

function A:ScanTransmog(done)
    local TC = C_TransmogCollection
    if not TC then return done() end
    local instant = (C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    local catRows, work, items = {}, {}, {}

    -- étape 1 : catégories et apparences obtenues
    A:RunChunked(29, 1, function(cat)
        local name, isWeapon = try(TC.GetCategoryInfo, cat)
        if type(name) == "string" and name ~= "" then
            catRows[#catRows + 1] = join(cat, name, isWeapon and 1 or 0,
                try(TC.GetCategoryCollectedCount, cat) or 0, try(TC.GetCategoryTotal, cat) or 0)
            local apps = try(TC.GetCategoryAppearances, cat)
            for _, app in ipairs(type(apps) == "table" and apps or {}) do
                if app.isCollected and app.visualID then work[#work + 1] = { cat, app.visualID } end
            end
        end
    end, function()
        -- étape 2 : un objet représentatif par apparence obtenue
        A:RunChunked(#work, 25, function(i)
            local cat, visualID = work[i][1], work[i][2]
            local sources = try(TC.GetAppearanceSources, visualID, cat)
            if type(sources) == "table" and #sources > 0 then
                local pick = sources[1]
                for _, src in ipairs(sources) do
                    if src.isCollected then pick = src break end
                end
                local itemID = pick.itemID
                local _, _, _, equipLoc, _, classID, subClassID = try(instant, itemID)
                items[cat] = items[cat] or {}
                items[cat][#items[cat] + 1] = join(pick.sourceID, itemID, pick.name, pick.quality or 1,
                                                   classID, subClassID, equipLoc)
            end
        end, function()
            local packed = {}
            for cat, list in pairs(items) do packed[cat] = table.concat(list, RS) end
            local previous = DB().transmog
            DB().transmog = { updated = time(), cats = table.concat(catRows, RS), items = packed,
                              sets = previous and previous.sets or "", setsUpdated = previous and previous.setsUpdated or 0 }
            MarkScan("transmog")
            done()
        end)
    end)
end

function A:ScanSets(done)
    local sets = C_TransmogSets and try(C_TransmogSets.GetAllSets)
    if type(sets) ~= "table" then return done() end
    local rows = {}
    A:RunChunked(#sets, 25, function(i)
        local set = sets[i]
        local apps = try(C_TransmogSets.GetSetPrimaryAppearances, set.setID)
        local total, have = 0, 0
        for _, a in ipairs(type(apps) == "table" and apps or {}) do
            total = total + 1
            if a.collected then have = have + 1 end
        end
        rows[#rows + 1] = join(set.setID, set.name, trim(set.label or set.description or "", 80),
                               set.classMask or 0, set.expansionID or 0, have, total)
    end, function()
        local db = DB()
        db.transmog = db.transmog or { updated = time(), cats = "", items = {} }
        db.transmog.sets = table.concat(rows, RS)
        db.transmog.setsUpdated = time()
        MarkScan("sets")
        done()
    end)
end

local SCAN_ORDER = {
    achievements = "ScanAchievements", statistiques = "ScanStatistics", montures = "ScanMounts",
    mascottes = "ScanPets", jouets = "ScanToys", heritage = "ScanHeirlooms",
    transmog = "ScanTransmog", ensembles = "ScanSets",
}
local SCAN_SEQUENCE = { "achievements", "statistiques", "montures", "mascottes", "jouets", "heritage", "transmog", "ensembles" }

function A:StartScans(which)
    if A.scanning then Log("Analyse déjà en cours.") return end
    local queue = {}
    for _, key in ipairs(SCAN_SEQUENCE) do
        if not which or which == "" or which == "tout" or which == key then queue[#queue + 1] = key end
    end
    if #queue == 0 then
        Log("Analyses possibles : tout, achievements, statistiques, montures, mascottes, jouets, heritage, transmog, ensembles")
        return
    end
    A.scanning = true
    local i = 0
    local function nextTask()
        i = i + 1
        if i > #queue then
            A.scanning = false
            Log("Analyse terminée. Tapez /ha save pour envoyer les résultats à l'application.")
            return
        end
        local fn = A[SCAN_ORDER[queue[i]]]
        if type(fn) ~= "function" then return nextTask() end
        if not pcall(fn, A, nextTask) then nextTask() end   -- erreur : on passe à la suivante
    end
    Log("Analyse en cours (découpée pour ne pas gêner le jeu)...")
    nextTask()
end

function A:ScansStale()
    local db = DB()
    if db.settings and db.settings.autoScan == false then return false end
    local last = db.scanInfo and db.scanInfo.achievements
    return (not last) or (time() - last) > 3 * 86400
end

local LAZY = {
    talents = "CollectTalents",
    spellbook = "CollectSpellbook",
    achievements = "CollectAchievements",
    collections = "CollectCollections",
    currencies = "CollectCurrencies",
    factions = "CollectFactions",
    lockouts = "CollectLockouts",
    vault = "CollectVault",
}
A.dirty = { talents = true, spellbook = true, achievements = true, collections = true,
            currencies = true, factions = true, lockouts = true, vault = true }

local EVENT_DIRTY = {
    PLAYER_TALENT_UPDATE = { "talents", "spellbook" },
    TRAIT_CONFIG_UPDATED = { "talents" },
    PLAYER_SPECIALIZATION_CHANGED = { "talents", "spellbook" },
    ACTIVE_PLAYER_SPECIALIZATION_CHANGED = { "talents", "spellbook" },
    SPELLS_CHANGED = { "spellbook" },
    PLAYER_LEVEL_UP = { "talents", "spellbook" },
    ACHIEVEMENT_EARNED = { "achievements" },
    NEW_MOUNT_ADDED = { "collections" },
    NEW_PET_ADDED = { "collections" },
    NEW_TOY_ADDED = { "collections" },
    HEIRLOOMS_UPDATED = { "collections" },
    CURRENCY_DISPLAY_UPDATE = { "currencies" },
    UPDATE_FACTION = { "factions" },
    MAJOR_FACTION_RENOWN_LEVEL_CHANGED = { "factions" },
    UPDATE_INSTANCE_INFO = { "lockouts" },
    WEEKLY_REWARDS_UPDATE = { "vault" },
}

function A:RefreshLazy()
    local db = DB()
    for key, method in pairs(LAZY) do
        if A.dirty[key] then
            local ok, result, complete = pcall(self[method], self)
            if ok and result then
                db[key] = result
                -- résultat vide ou incomplet (données pas encore chargées) : on réessaiera
                A.dirty[key] = not complete
            end
        end
    end
end

---------------------------------------------------------------------------
-- Temps de jeu (/played) : demandé sans afficher le message dans le chat
---------------------------------------------------------------------------
function A:RestoreChat()
    for _, cf in ipairs(A.chatMuted or {}) do
        pcall(cf.RegisterEvent, cf, "TIME_PLAYED_MSG")
    end
    A.chatMuted = nil
end

function A:RequestPlayed()
    if type(RequestTimePlayed) ~= "function" then return end
    if not A.chatMuted then
        A.chatMuted = {}
        for i = 1, (NUM_CHAT_WINDOWS or 10) do
            local cf = _G["ChatFrame" .. i]
            if cf and cf.UnregisterEvent then
                pcall(cf.UnregisterEvent, cf, "TIME_PLAYED_MSG")
                A.chatMuted[#A.chatMuted + 1] = cf
            end
        end
        C_Timer.After(5, function() A:RestoreChat() end)   -- filet de sécurité
    end
    pcall(RequestTimePlayed)
end

function A:OnPlayed(total, levelTime)
    if type(total) == "number" and type(levelTime) == "number" then
        DB().played = { total = total, level = levelTime, updated = time() }
    end
    if A.chatMuted then
        C_Timer.After(0.5, function() A:RestoreChat() end)
    end
end

---------------------------------------------------------------------------
-- Instantané dans la base (mémoire ; écrit sur disque au /reload)
---------------------------------------------------------------------------
function A:Snapshot(force)
    -- Jamais pendant un chargement / une déconnexion : les API renvoient alors du vide
    -- et écraseraient les bonnes données déjà enregistrées.
    if not A.worldReady then return false end
    if InCombatLockdown() and not force then return false end

    local ok, char = pcall(self.CollectCharacter, self)
    if not ok or not char then return false end

    local db = DB()
    db.characterData = char

    -- Chaque section n'est remplacée que si la nouvelle lecture est valide
    local ok2, prof = pcall(self.CollectProfessions, self)
    if ok2 and prof and #prof > 0 then db.professions = prof end
    local ok3, inv = pcall(self.CollectInventory, self)
    if ok3 and inv and inv.capacity > 0 then db.inventory = inv end
    local ok4, quests = pcall(self.CollectQuests, self)
    if ok4 and quests and quests.valid then db.quests = quests end
    local ok5, equip = pcall(self.CollectEquipment, self, force)
    if ok5 and equip and #equip > 0 then db.equipment = equip end
    self:RefreshLazy()

    db.settings = db.settings or { autoMinutes = 0 }
    return true
end

---------------------------------------------------------------------------
-- Empreinte du contenu : sert à ne recharger l'UI que si quelque chose a changé
-- (le temps de jeu n'en fait pas partie : il changerait à chaque minute)
function A:Signature()
    local db = DB()
    local c = db.characterData or {}
    local parts = {
        tostring(c.name), tostring(c.level), tostring(c.xp), tostring(c.money),
        tostring(c.zone), tostring(c.subzone), tostring(c.specialization), tostring(c.ilvl),
    }
    local inv = db.inventory
    if inv then
        parts[#parts + 1] = tostring(inv.used)
        for _, it in ipairs(inv.items or {}) do
            parts[#parts + 1] = it.id .. ":" .. it.count
        end
    end
    local q = db.quests
    if q then
        for _, quest in ipairs(q.list or {}) do
            local done = 0
            for _, o in ipairs(quest.objectives or {}) do
                if o.done then done = done + 1 end
            end
            parts[#parts + 1] = quest.id .. ":" .. quest.status .. ":" .. done
        end
    end
    for _, p in ipairs(db.professions or {}) do
        parts[#parts + 1] = p.name .. ":" .. p.level
    end
    for _, it in ipairs(db.equipment or {}) do
        parts[#parts + 1] = it.slot .. ":" .. it.id .. ":" .. tostring(it.ilvl)
    end
    parts[#parts + 1] = "t" .. tostring(db.talents and db.talents.points)
    parts[#parts + 1] = "a" .. tostring(db.achievements and db.achievements.points)
    parts[#parts + 1] = "m" .. tostring(db.collections and db.collections.mounts and db.collections.mounts.collected)
    for name, rec in pairs(db.recipes or {}) do
        parts[#parts + 1] = "r" .. name .. #(rec.list or {})
    end
    return table.concat(parts, "|")
end

---------------------------------------------------------------------------
-- Rechargement automatique optionnel (/ha auto <minutes>)
---------------------------------------------------------------------------
function A:CanReloadSafely()
    if InCombatLockdown() then return false end
    if UnitIsDeadOrGhost("player") then return false end
    if UnitOnTaxi("player") then return false end
    if IsInInstance() then return false end
    if (GetUnitSpeed("player") or 0) > 0 then return false end   -- seulement à l'arrêt
    if try(UnitCastingInfo, "player") or try(UnitChannelInfo, "player") then return false end
    return true
end

function A:AutoSyncTick()
    local db = DB()
    local minutes = (db.settings and db.settings.autoMinutes) or 0
    if minutes < MIN_AUTO_MINUTES then return end
    if (GetTime() - A.loadedAt) < minutes * 60 then return end
    if not A:CanReloadSafely() then return end

    if not A:Snapshot() then return end
    local sig = A:Signature()
    if sig == db.diskSig then return end   -- rien de nouveau depuis la dernière écriture

    db.diskSig = sig
    Log("Synchronisation automatique (rechargement de l'interface)...")
    ReloadUI()
end

---------------------------------------------------------------------------
-- Événements
---------------------------------------------------------------------------
A.loadedAt = GetTime()
A.pending = false
A.worldReady = false

function A:ScheduleSnapshot()
    if A.pending then return end
    A.pending = true
    C_Timer.After(DEBOUNCE_SECONDS, function()
        A.pending = false
        A:Snapshot()
    end)
end

function A:ScheduleRecipeScan()
    if A.recipePending then return end
    A.recipePending = true
    C_Timer.After(1.5, function()
        A.recipePending = false
        pcall(A.ScanRecipes, A)
        A:ScheduleSnapshot()
    end)
end

function A:ScheduleBankScan(guild)
    local key = guild and "guildPending" or "bankPending"
    if A[key] then return end
    A[key] = true
    C_Timer.After(1.2, function()
        A[key] = false
        if not A.worldReady then return end
        pcall(guild and A.ScanGuildBankTab or A.ScanWarbandBank, A)
    end)
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("PLAYER_LEAVING_WORLD")
frame:RegisterEvent("PLAYER_LOGOUT")

-- Événements facultatifs : certains n'existent pas selon la version du jeu
local optionalEvents = {
    "BAG_UPDATE_DELAYED", "QUEST_LOG_UPDATE", "PLAYER_MONEY", "PLAYER_XP_UPDATE",
    "PLAYER_LEVEL_UP", "ZONE_CHANGED_NEW_AREA", "ZONE_CHANGED",
    "PLAYER_SPECIALIZATION_CHANGED", "SKILL_LINES_CHANGED", "PLAYER_EQUIPMENT_CHANGED",
    "PLAYER_TALENT_UPDATE", "TIME_PLAYED_MSG", "TRAIT_CONFIG_UPDATED",
    "ACTIVE_PLAYER_SPECIALIZATION_CHANGED", "SPELLS_CHANGED", "ACHIEVEMENT_EARNED",
    "NEW_MOUNT_ADDED", "NEW_PET_ADDED", "NEW_TOY_ADDED", "HEIRLOOMS_UPDATED",
    "TRADE_SKILL_LIST_UPDATE", "TRADE_SKILL_SHOW",
    "CURRENCY_DISPLAY_UPDATE", "UPDATE_FACTION", "MAJOR_FACTION_RENOWN_LEVEL_CHANGED",
    "UPDATE_INSTANCE_INFO", "WEEKLY_REWARDS_UPDATE",
    "QUEST_WATCH_LIST_CHANGED", "SUPER_TRACKING_CHANGED", "QUEST_TURNED_IN", "PLAYER_DEAD",
    "BANKFRAME_OPENED", "BANKFRAME_CLOSED", "GUILDBANKFRAME_OPENED", "GUILDBANKBAGSLOTS_CHANGED",
}
for _, ev in ipairs(optionalEvents) do
    pcall(frame.RegisterEvent, frame, ev)
end

frame:SetScript("OnEvent", function(_, event, arg1, arg2, arg3)
    if event == "ADDON_LOADED" then
        if arg1 == ADDON_NAME then
            local db = DB()
            db.settings = db.settings or {}
            db.settings.autoMinutes = db.settings.autoMinutes or 0
            if db.settings.autoScan == nil then db.settings.autoScan = true end
            if db.settings.combatLog == nil then db.settings.combatLog = false end
        end
    elseif event == "PLAYER_LEAVING_WORLD" or event == "PLAYER_LOGOUT" then
        -- On fige tout : les données restent celles du dernier bon instantané
        A.worldReady = false
    elseif event == "TIME_PLAYED_MSG" then
        A:OnPlayed(arg1, arg2)
    elseif event == "PLAYER_ENTERING_WORLD" then
        C_Timer.After(2, function()
            A.worldReady = true
            A:Snapshot()
            pcall(RequestRaidInfo)
        end)
        C_Timer.After(4, function() A:RequestPlayed() end)
        C_Timer.After(3, function()
            -- Mode Focus de l'appli : le journal de combat (fichier Logs/WoWCombatLog*.txt) lui sert à savoir
            -- quand vous êtes en combat. Activé seulement si vous l'avez demandé : /ha combatlog on
            local db = DB()
            if db.settings and db.settings.combatLog and type(LoggingCombat) == "function" then
                pcall(LoggingCombat, true)
            end
        end)
        C_Timer.After(45, function()
            if A.worldReady and not InCombatLockdown() and not IsInInstance() and A:ScansStale() then A:StartScans() end
        end)
    elseif event == "TRADE_SKILL_LIST_UPDATE" or event == "TRADE_SKILL_SHOW" then
        A:ScheduleRecipeScan()
    elseif event == "BANKFRAME_OPENED" then
        A.bankOpen = true
        A:ScheduleBankScan(false)
    elseif event == "BANKFRAME_CLOSED" then
        A.bankOpen = false
    elseif event == "GUILDBANKFRAME_OPENED" or event == "GUILDBANKBAGSLOTS_CHANGED" then
        A:ScheduleBankScan(true)
    else
        if event == "PLAYER_DEAD" then
            A:AddLog("death", "Mort")
        elseif event == "QUEST_TURNED_IN" then
            local title = (C_QuestLog and try(C_QuestLog.GetTitleForQuestID, arg1)) or ("Quête " .. tostring(arg1))
            local text = "Quête rendue : " .. title
            if type(arg2) == "number" and arg2 > 0 then text = text .. " (+" .. arg2 .. " XP)" end
            A:AddLog("quest", text)
        elseif event == "ACHIEVEMENT_EARNED" then
            local _, name = try(GetAchievementInfo, arg1)
            if name then A:AddLog("achievement", "Haut fait : " .. name) end
        elseif event == "PLAYER_LEVEL_UP" then
            A:AddLog("level", "Niveau " .. tostring(arg1))
            C_Timer.After(2, function() A:RequestPlayed() end)
        elseif event == "BAG_UPDATE_DELAYED" and A.bankOpen then
            A:ScheduleBankScan(false)
        end
        for _, key in ipairs(EVENT_DIRTY[event] or {}) do
            A.dirty[key] = true
        end
        A:ScheduleSnapshot()
    end
end)

C_Timer.NewTicker(TICK_SECONDS, function() A:AutoSyncTick() end)
C_Timer.NewTicker(PLAYED_REFRESH_SECONDS, function() A:RequestPlayed() end)

---------------------------------------------------------------------------
-- Commandes : /ha, /hermes
---------------------------------------------------------------------------
SLASH_HERMESASSISTANT1 = "/hermes"
SLASH_HERMESASSISTANT2 = "/ha"
SlashCmdList["HERMESASSISTANT"] = function(msg)
    msg = strtrim(msg or "")
    local cmd, arg = msg:match("^(%S*)%s*(.-)$")
    cmd = (cmd or ""):lower()

    if cmd == "save" or cmd == "sync" then
        for key in pairs(A.dirty) do A.dirty[key] = true end
        pcall(RequestRaidInfo)
        A:Snapshot(true)
        Log("Données enregistrées, rechargement de l'interface pour écrire le fichier...")
        ReloadUI()

    elseif cmd == "auto" then
        local db = DB()
        db.settings = db.settings or {}
        local value = (arg or ""):lower()
        if value == "off" or value == "0" then
            db.settings.autoMinutes = 0
            Log("Synchronisation automatique désactivée.")
        else
            local minutes = tonumber(value)
            if not minutes or minutes < MIN_AUTO_MINUTES then
                Log("Usage : /ha auto <minutes> (minimum " .. MIN_AUTO_MINUTES .. ") ou /ha auto off")
            else
                db.settings.autoMinutes = math.floor(minutes)
                Log("Synchronisation automatique toutes les " .. db.settings.autoMinutes ..
                    " min (hors combat, hors instance, personnage à l'arrêt, seulement si quelque chose a changé).")
            end
        end

    elseif cmd == "combatlog" then
        local db = DB()
        db.settings = db.settings or {}
        local value = (arg or ""):lower()
        if value == "on" or value == "off" then
            db.settings.combatLog = (value == "on")
            if type(LoggingCombat) == "function" then pcall(LoggingCombat, db.settings.combatLog) end
            Log(db.settings.combatLog
                and "Journal de combat activé (dossier Logs de WoW) : l'appli s'en sert pour le mode Focus."
                or "Journal de combat désactivé.")
        else
            Log("Journal de combat : " .. ((db.settings.combatLog and "activé") or "désactivé")
                .. " — /ha combatlog on | off")
        end

    elseif cmd == "scan" then
        A:StartScans((arg or ""):lower())

    elseif cmd == "debug" then
        A:Snapshot(true)
        local db = DB()
        Log("Spécialisation : '" .. tostring(A:GetSpecName()) .. "'")
        local equip = db.equipment or {}
        local withTip = 0
        for _, it in ipairs(equip) do
            if it.tooltip and #it.tooltip > 0 then withTip = withTip + 1 end
        end
        Log(string.format("Équipement : %d objets, %d avec infobulle", #equip, withTip))
        Log("Temps de jeu : " .. (db.played and (db.played.total .. " s") or "pas encore reçu"))
        -- diagnostic de la spécialisation : ce que renvoie chaque API
        local csi = C_SpecializationInfo
        Log("Spéc. C_SpecializationInfo.GetSpecialization = " .. tostring(csi and try(csi.GetSpecialization)))
        Log("Spéc. GetSpecialization = " .. tostring(try(GetSpecialization)))
        Log("Spéc. PlayerUtil.GetCurrentSpecID = " .. tostring(PlayerUtil and try(PlayerUtil.GetCurrentSpecID)))
        Log(string.format("Talents : %d points / grimoire : %d onglets / hauts faits : %s pts / montures : %s",
            db.talents and db.talents.points or 0, #(db.spellbook or {}),
            tostring(db.achievements and db.achievements.points),
            tostring(db.collections and db.collections.mounts and db.collections.mounts.collected)))
        local info = db.scanInfo or {}
        Log(string.format("Analyses : hauts faits %s / montures %s / mascottes %s / transmog %s (tapez /ha scan)",
            info.achievements and "ok" or "non", info.mounts and "ok" or "non",
            info.pets and "ok" or "non", info.transmog and "ok" or "non"))
        Log(string.format("Monnaies : %d / réputations : %d / verrouillages : %d / Chambre forte : %d activités",
            #(db.currencies or {}), #(db.factions or {}),
            db.lockouts and #(db.lockouts.instances or {}) or 0, db.vault and #(db.vault.activities or {}) or 0))
        local recipeCount = 0
        for _, rec in pairs(db.recipes or {}) do recipeCount = recipeCount + #(rec.list or {}) end
        Log("Recettes enregistrées : " .. recipeCount .. " (ouvrez la fenêtre d'un métier pour les importer)")
        A:RequestPlayed()

    elseif cmd == "" then
        A:Snapshot(true)
        local db = DB()
        local d = db.characterData
        if d then
            Log(string.format("%s (%s) - Niveau %s %s %s - %s",
                d.titleName or d.name or "?", d.realm or "?", d.level or "?", d.class or "", d.specialization or "", d.faction or ""))
            local inv, q = db.inventory, db.quests
            Log(string.format("Sacs : %s/%s emplacements - Quêtes : %s - Métiers : %s - Objets équipés : %s",
                inv and inv.used or 0, inv and inv.capacity or 0,
                q and #(q.list or {}) or 0, #(db.professions or {}), #(db.equipment or {})))
            local minutes = (db.settings and db.settings.autoMinutes) or 0
            Log(minutes > 0 and ("Sync auto : toutes les " .. minutes .. " min")
                or "Sync auto désactivée (/ha auto 5 pour l'activer, /ha save pour forcer l'écriture)")
        else
            Log("Aucune donnée de personnage.")
        end
    else
        Log("Commandes : /ha | /ha save | /ha scan | /ha combatlog on|off | /ha auto <minutes> | /ha auto off | /ha debug")
    end
end
