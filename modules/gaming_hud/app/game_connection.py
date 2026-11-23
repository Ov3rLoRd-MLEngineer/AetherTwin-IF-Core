"""
Connexion aux données WoW via les SavedVariables (addon HermesAssistant)
"""
import glob
import os
import time

from config import WoWConfig
from lua_parser import parse_lua_file, LuaParseError


def _format_age(seconds):
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {(seconds % 3600) // 60} min"


def _as_list(value):
    """Un tableau Lua {a, b, c} est parsé en {1: a, 2: b, 3: c} : on le remet en liste."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        keys = sorted(k for k in value if isinstance(k, int))
        return [value[k] for k in keys]
    return []


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _dict_list(value):
    """Tableau Lua de tables -> liste de dict."""
    return [_as_dict(v) for v in _as_list(value)]


FS, RS = "\u00a6", "\u00b6"   # séparateurs ¦ (champs) et ¶ (enregistrements) des listes compactes de l'addon


def _records(value, width=0):
    """Chaîne compacte 'a¦b¦c¶d¦e¦f' -> [[a, b, c], [d, e, f]] (complétée à `width` champs)."""
    if not isinstance(value, str) or not value:
        return []
    rows = []
    for record in value.split(RS):
        if not record:
            continue
        fields = record.split(FS)
        fields += [""] * (width - len(fields))
        rows.append(fields)
    return rows


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_achv(raw):
    raw = _as_dict(raw)
    cats = [{"id": _int(f[0]), "name": f[1], "parent": _int(f[2], -1), "total": _int(f[3]), "done": _int(f[4])}
            for f in _records(raw.get("cats"), 5)]
    lists = {}
    for key, value in _as_dict(raw.get("list")).items():
        lists[str(key)] = [{"id": _int(f[0]), "name": f[1], "points": _int(f[2]), "done": f[3] == "1",
                            "date": f[4], "desc": f[5]} for f in _records(value, 6)]
    return {"updated": raw.get("updated", 0), "cats": cats, "list": lists}


def _normalize_stats(raw):
    raw = _as_dict(raw)
    cats = [{"id": _int(f[0]), "name": f[1], "parent": _int(f[2], -1)} for f in _records(raw.get("cats"), 3)]
    lists = {str(k): [{"id": _int(f[0]), "name": f[1], "value": f[2]} for f in _records(v, 3)]
             for k, v in _as_dict(raw.get("list")).items()}
    return {"updated": raw.get("updated", 0), "cats": cats, "list": lists}


def _normalize_mounts(raw):
    raw = _as_dict(raw)
    return {"updated": raw.get("updated", 0),
            "list": [{"id": _int(f[0]), "spellID": _int(f[1]), "name": f[2], "collected": f[3] == "1",
                      "sourceType": _int(f[4]), "favorite": f[5] == "1", "source": f[6], "desc": f[7]}
                     for f in _records(raw.get("list"), 8)]}


def _normalize_pets(raw):
    raw = _as_dict(raw)
    return {"updated": raw.get("updated", 0),
            "list": [{"id": _int(f[0]), "name": f[1], "owned": _int(f[2]), "level": _int(f[3]),
                      "rarity": _int(f[4]), "type": _int(f[5]), "creature": _int(f[6]), "source": f[7],
                      "desc": f[8], "battle": f[9] == "1"} for f in _records(raw.get("list"), 10)]}


def _normalize_toys(raw):
    raw = _as_dict(raw)
    return {"updated": raw.get("updated", 0),
            "list": [{"id": _int(f[0]), "name": f[1], "owned": f[2] == "1", "quality": _int(f[3], 1)}
                     for f in _records(raw.get("list"), 4)]}


def _normalize_heirlooms(raw):
    raw = _as_dict(raw)
    return {"updated": raw.get("updated", 0),
            "list": [{"id": _int(f[0]), "name": f[1], "owned": f[2] == "1", "slot": f[3], "source": f[4]}
                     for f in _records(raw.get("list"), 5)]}


def _normalize_transmog(raw):
    raw = _as_dict(raw)
    cats = [{"id": _int(f[0]), "name": f[1], "weapon": f[2] == "1", "collected": _int(f[3]), "total": _int(f[4])}
            for f in _records(raw.get("cats"), 5)]
    items = {str(cat): [{"source": _int(f[0]), "id": _int(f[1]), "name": f[2], "quality": _int(f[3], 1),
                         "classID": _int(f[4]), "subClassID": _int(f[5]), "equipLoc": f[6]}
                        for f in _records(value, 7)]
             for cat, value in _as_dict(raw.get("items")).items()}
    sets = [{"id": _int(f[0]), "name": f[1], "label": f[2], "classMask": _int(f[3]), "expansion": _int(f[4]),
             "have": _int(f[5]), "total": _int(f[6])} for f in _records(raw.get("sets"), 7)]
    return {"updated": raw.get("updated", 0), "setsUpdated": raw.get("setsUpdated", 0),
            "cats": cats, "items": items, "sets": sets}


def _normalize_bank(raw):
    """Banque de bataillon : {updated, money, tabs: [{name, items}]}"""
    raw = _as_dict(raw)
    return {"updated": raw.get("updated", 0), "money": raw.get("money", 0),
            "tabs": [{"name": _as_dict(t).get("name", ""), "items": _dict_list(_as_dict(t).get("items"))}
                     for t in _as_list(raw.get("tabs"))]}


def _normalize_guild_bank(raw):
    """Banque de guilde : tabs indexés par numéro d'onglet."""
    raw = _as_dict(raw)
    tabs = []
    for key, tab in sorted(_as_dict(raw.get("tabs")).items(), key=lambda kv: _int(kv[0])):
        tab = _as_dict(tab)
        tabs.append({"index": _int(key), "name": tab.get("name", ""), "updated": tab.get("updated", 0),
                     "items": _dict_list(tab.get("items"))})
    return {"guild": raw.get("guild", ""), "money": raw.get("money", 0), "updated": raw.get("updated", 0), "tabs": tabs}


def _normalize_bestiary(raw):
    """Bestiaire de l'addon (1.9) : {id de créature (texte): fiche}, objets et zones en dictionnaires."""
    out = {}
    for key, entry in _as_dict(raw).items():
        entry = _as_dict(entry)
        if not entry or not _int(key):
            continue
        entry = dict(entry)
        entry["items"] = {str(_int(i)): _as_dict(v) for i, v in _as_dict(entry.get("items")).items() if _int(i)}
        entry["zones"] = {str(z): _int(n) for z, n in _as_dict(entry.get("zones")).items()}
        out[str(_int(key))] = entry
    return out


def _normalize_lockouts(raw):
    raw = _as_dict(raw)
    instances = []
    for inst in _dict_list(raw.get("instances")):
        inst["bosses"] = _dict_list(inst.get("bosses"))
        instances.append(inst)
    return {"instances": instances, "worldBosses": _dict_list(raw.get("worldBosses"))}


def _normalize_vault(raw):
    raw = _as_dict(raw)
    return {"activities": _dict_list(raw.get("activities")), "canClaim": bool(raw.get("canClaim")),
            "hasRewards": bool(raw.get("hasRewards"))}


def _normalize_mythic(raw):
    """Mythique+ (addon 1.7) : cote, clé en poche, meilleurs résultats par donjon, clés de la semaine."""
    raw = _as_dict(raw)
    key = _as_dict(raw.get("keystone"))
    return {"score": _int(raw.get("score")),
            "keystone": {"name": str(key.get("name", "")), "level": _int(key.get("level"))} if key.get("level") else None,
            "dungeons": [{"name": str(d.get("name", "")), "level": _int(d.get("level")), "score": _int(d.get("score")),
                          "inTime": bool(d.get("inTime"))} for d in _dict_list(raw.get("dungeons"))],
            "week": [{"name": str(r.get("name", "")), "level": _int(r.get("level")), "completed": bool(r.get("completed"))}
                     for r in _dict_list(raw.get("week"))]}


def _normalize_talents(raw):
    raw = _as_dict(raw)
    return {
        "points": raw.get("points", 0),
        "loadout": raw.get("loadout", "") if isinstance(raw.get("loadout"), str) else "",
        "hero": raw.get("hero", ""),
        "nodes": _dict_list(raw.get("nodes")),
    }


def _normalize_spellbook(raw):
    return [{"name": _as_dict(line).get("name", ""), "spells": _dict_list(_as_dict(line).get("spells"))}
            for line in _as_list(raw)]


def _normalize_achievements(raw):
    raw = _as_dict(raw)
    return {
        "points": raw.get("points", 0), "completed": raw.get("completed", 0), "total": raw.get("total", 0),
        "categories": _dict_list(raw.get("categories")), "recent": _dict_list(raw.get("recent")),
    }


def _normalize_collections(raw):
    raw = _as_dict(raw)
    mounts = _as_dict(raw.get("mounts"))
    return {
        "mounts": {"total": mounts.get("total", 0), "collected": mounts.get("collected", 0),
                   "list": _dict_list(mounts.get("list"))},
        "pets": {"total": _as_dict(raw.get("pets")).get("total", 0), "owned": _as_dict(raw.get("pets")).get("owned", 0)},
        "toys": {"total": _as_dict(raw.get("toys")).get("total", 0), "collected": _as_dict(raw.get("toys")).get("collected", 0)},
        "heirlooms": {"total": _as_dict(raw.get("heirlooms")).get("total", 0), "known": _as_dict(raw.get("heirlooms")).get("known", 0)},
        "warbandMoney": raw.get("warbandMoney", 0),
    }


def _normalize_recipes(raw):
    """{métier: {"updated": t, "list": [{id, name, mats: [{ids: [...], quantity, name}]}]}}"""
    out = {}
    for profession, record in _as_dict(raw).items():
        record = _as_dict(record)
        recipes = []
        for recipe in _dict_list(record.get("list")):
            recipe["mats"] = [dict(m, ids=[i for i in _as_list(m.get("ids"))]) for m in _dict_list(recipe.get("mats"))]
            recipes.append(recipe)
        out[str(profession)] = {"updated": record.get("updated", 0), "list": recipes}
    return out


class GameConnection:
    """Lit le fichier SavedVariables de l'addon HermesAssistant"""

    def __init__(self, wow_path=None):
        self.wow_path = wow_path or WoWConfig.WOW_PATH
        self.account_path = os.path.join(self.wow_path, "WTF", "Account")
        self.file_path = None
        self.file_mtime = 0.0
        self.data = {}          # infos du personnage (compatibilité avec l'ancienne version)
        self.snapshot = {}      # toutes les données normalisées
        self.last_error = ""
        self._parsed_path = None
        self._parsed_mtime = None
        self.last_refresh_result = ""

        if self.is_connected():
            print(f"Dossier WTF trouvé : {self.account_path}")
        else:
            print(f"Dossier WTF introuvable : {self.account_path}")

    def set_path(self, wow_path):
        """Re-pointe la connexion sur un autre dossier _retail_ (sans redémarrer)."""
        self.wow_path = wow_path
        self.account_path = os.path.join(wow_path, "WTF", "Account")
        self.file_path = None
        self.file_mtime = 0.0
        self._parsed_path = None
        self._parsed_mtime = None
        self.last_error = ""

    def is_connected(self):
        return os.path.isdir(self.account_path)

    def find_saved_variables_file(self):
        """Fichier HermesAssistant.lua le plus récent (compte ou personnage)."""
        if not self.is_connected():
            return None
        pattern = os.path.join(self.account_path, "**", "SavedVariables", WoWConfig.ADDON_LUA)
        candidates = glob.glob(pattern, recursive=True)
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)

    def refresh(self, force=False):
        """Relit le fichier seulement s'il a changé (ou si force). True si de nouvelles données sont chargées."""
        if force:
            self._parsed_mtime = None
        path = self.find_saved_variables_file()
        if not path:
            self.file_path = None
            self.last_error = ""
            return False

        try:
            mtime = os.path.getmtime(path)
        except OSError as e:
            self.last_error = f"Lecture impossible : {e}"
            return False

        self.file_path = path
        self.file_mtime = mtime
        if path == self._parsed_path and mtime == self._parsed_mtime:
            return False

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                parsed = parse_lua_file(f.read())
        except (OSError, LuaParseError, IndexError, ValueError) as e:
            # Fichier peut-être en cours d'écriture : on retentera au prochain tour
            self.last_error = f"Erreur de lecture/parsing : {e}"
            return False

        self._parsed_path, self._parsed_mtime = path, mtime

        db = parsed.get(WoWConfig.DB_VARIABLE)
        if not isinstance(db, dict):
            self.last_error = (f"Variable {WoWConfig.DB_VARIABLE} absente du fichier "
                               f"(vérifie la ligne '## SavedVariables' du .toc)")
            return False

        char = _as_dict(db.get("characterData", db))   # ancien format plat toléré
        if not char.get("name"):
            self.last_error = "Fichier trouvé mais sans données de personnage (fais /reload en jeu)"
            return False

        inventory = _as_dict(db.get("inventory"))
        quests = _as_dict(db.get("quests"))

        self.data = {
            "name": char.get("name", ""),
            "realm": char.get("realm", ""),
            "level": char.get("level", 1),
            "race": char.get("race", ""),
            "raceFile": char.get("raceFile", ""),
            "class": char.get("class", ""),
            "classFile": char.get("classFile", ""),
            "faction": char.get("faction", ""),
            "sex": char.get("sex", 0),
            "specialization": char.get("specialization", ""),
            "ilvl": char.get("ilvl", 0),
            "xp": char.get("xp", 0),
            "xpMax": char.get("xpMax", 0),
            "restedXP": char.get("restedXP", 0),
            "money": char.get("money", 0),
            "zone": char.get("zone", ""),
            "subzone": char.get("subzone", ""),
            "stats": _as_dict(char.get("stats")),
            "titleName": char.get("titleName", ""),
            "armor": char.get("armor", 0),
            "crit": char.get("crit", 0),
            "haste": char.get("haste", 0),
            "mastery": char.get("mastery", 0),
            "versatility": char.get("versatility", 0),
            "updated": char.get("updated", 0),
        }
        self.snapshot = {
            "character": self.data,
            "inventory": {
                "capacity": inventory.get("capacity", 0),
                "used": inventory.get("used", 0),
                "items": [_as_dict(i) for i in _as_list(inventory.get("items"))],
            },
            "quests": {
                "count": quests.get("count", 0),
                "completedTotal": quests.get("completedTotal", 0),
                "max": quests.get("max", 35),
                "list": [
                    dict(_as_dict(q),
                         objectives=[_as_dict(o) for o in _as_list(_as_dict(q).get("objectives"))],
                         rewards=[_as_dict(r) for r in _as_list(_as_dict(q).get("rewards"))])
                    for q in _as_list(quests.get("list"))
                ],
            },
            "professions": [_as_dict(p) for p in _as_list(db.get("professions"))],
            "equipment": [
                dict(_as_dict(i), tooltip=[_as_dict(l) for l in _as_list(_as_dict(i).get("tooltip"))])
                for i in _as_list(db.get("equipment"))
            ],
            "played": _as_dict(db.get("played")),
            "talents": _normalize_talents(db.get("talents")),
            "spellbook": _normalize_spellbook(db.get("spellbook")),
            "achievements": _normalize_achievements(db.get("achievements")),
            "collections": _normalize_collections(db.get("collections")),
            "recipes": _normalize_recipes(db.get("recipes")),
            "achv": _normalize_achv(db.get("achv")),
            "stats": _normalize_stats(db.get("stats")),
            "mounts": _normalize_mounts(db.get("mounts")),
            "pets": _normalize_pets(db.get("pets")),
            "toys": _normalize_toys(db.get("toys")),
            "heirlooms": _normalize_heirlooms(db.get("heirlooms")),
            "transmog": _normalize_transmog(db.get("transmog")),
            "currencies": _dict_list(db.get("currencies")),
            "factions": _dict_list(db.get("factions")),
            "lockouts": _normalize_lockouts(db.get("lockouts")),
            "vault": _normalize_vault(db.get("vault")),
            "mythicPlus": _normalize_mythic(db.get("mythicPlus")),
            "characterBank": _normalize_bank(db.get("characterBank")),
            "bestiary": _normalize_bestiary(db.get("bestiary")),
            "warbandBank": _normalize_bank(db.get("warbandBank")),
            "guildBank": _normalize_guild_bank(db.get("guildBank")),
            "log": _dict_list(db.get("log")),
            "scanInfo": _as_dict(db.get("scanInfo")),
            "fileTime": mtime,
            "settings": _as_dict(db.get("settings")),
        }
        self.last_error = ""
        print(f"Données chargées depuis {path} : {self.data.get('name')} niv {self.data.get('level')}")
        return True

    def get_character_data(self):
        self.refresh()
        return self.data

    def status_lines(self):
        """Textes de diagnostic affichés dans l'interface."""
        if not self.is_connected():
            return [f"Dossier WoW introuvable : {self.wow_path}"]
        if not self.file_path:
            return [f"{WoWConfig.ADDON_LUA} introuvable : lance WoW avec l'addon puis tape /ha save"]
        age = _format_age(int(time.time() - self.file_mtime))
        lines = [f"Fichier écrit par WoW il y a {age}  |  " + self.sync_info()]
        if self.last_error:
            lines.append(self.last_error)
        return lines

    def sync_info(self):
        minutes = self.snapshot.get("settings", {}).get("autoMinutes", 0) if self.snapshot else 0
        if isinstance(minutes, (int, float)) and minutes > 0:
            return f"Sync auto : toutes les {int(minutes)} min"
        return "Sync auto désactivée (/ha auto 5 en jeu)"
