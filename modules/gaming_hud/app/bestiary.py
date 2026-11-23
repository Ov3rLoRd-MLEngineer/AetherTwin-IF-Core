"""
Bestiaire : créatures rencontrées et tuées.

Deux sources, parce qu'aucune ne suffit seule :
- le **journal de combat** du jeu (fichier Logs/WoWCombatLog*.txt, /ha combatlog on) lu ici : créatures tuées,
  aptitudes qu'elles utilisent, PV et ressource max., niveau et carte (journalisation avancée du jeu) ;
  depuis Midnight les addons n'ont plus accès au journal de combat, mais le fichier est toujours écrit ;
- l'**addon** (HermesAssistant 1.9) : niveau, type, rang (élite, rare…), zone, et le butin de chaque corps
  (objets, or), que le journal de combat ne contient pas.

Tout est gardé dans bestiary.json (à côté de l'appli, jamais dans le dossier du jeu), avec les notes du joueur.
Lecture seule du jeu.
"""
import csv
import glob
import json
import os
import threading
import time

# Drapeaux du journal de combat : « à moi » (le joueur et ses familiers)
AFFILIATION_MINE = 0x1
SPELL_EVENTS = ("SPELL_CAST_SUCCESS", "SPELL_CAST_START", "SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE",
                "SPELL_AURA_APPLIED", "SPELL_HEAL", "SPELL_SUMMON", "RANGE_DAMAGE")
MAX_READ_PER_POLL = 24 * 1024 * 1024     # on rattrape un gros fichier en plusieurs fois
MAX_SPELLS = 40
POWER_NAMES = {0: "Mana", 1: "Rage", 2: "Focalisation", 3: "Énergie", 6: "Puissance runique"}
CLASSIFICATIONS = {"elite": "Élite", "rareelite": "Élite rare", "rare": "Rare", "worldboss": "Boss",
                   "trivial": "Insignifiante", "minus": "Mineure", "normal": ""}


def npc_id(guid):
    """« Creature-0-3767-0-1-12345-000ABC » → 12345 ; None pour un joueur, un familier, un objet…"""
    if not guid or not (guid.startswith("Creature-") or guid.startswith("Vehicle-")):
        return None
    parts = guid.split("-")
    try:
        return int(parts[5])
    except (IndexError, ValueError):
        return None


def _flags(value):
    try:
        return int(value, 16)
    except (TypeError, ValueError):
        return 0


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_line(line):
    """(événement, champs) d'une ligne du journal, ou None. Les noms entre guillemets peuvent contenir des virgules."""
    head, sep, rest = line.rstrip("\r\n").partition("  ")
    if not sep or not rest:
        return None
    try:
        fields = next(csv.reader([rest]))
    except (csv.Error, StopIteration):
        return None
    return (fields[0], fields) if fields else None


def _advanced(fields, start):
    """Infos « journalisation avancée » (unité décrite, PV, ressource, carte, niveau) à partir de `start`."""
    adv = fields[start:start + 17]
    if len(adv) < 17 or "-" not in adv[0] and adv[0] != "0000000000000000":
        return None
    power_type = _int(adv[8].split("|")[0], -1)
    max_power = _int(adv[10].split("|")[0])
    return {"guid": adv[0], "hp": _int(adv[3]), "power_type": power_type, "power": max_power,
            "map": _int(adv[14]), "level": _int(adv[16])}


class CombatLogReader:
    """Lit la suite des fichiers du journal de combat (positions mémorisées) et alimente `entries`."""

    def __init__(self, store):
        self.store = store
        self.engaged = {}      # guid de créature → True si « moi » l'a frappée ou en a été la cible
        self.dead = set()

    def feed(self, line, parsed=None):
        parsed = parsed or parse_line(line)
        if not parsed:
            return
        event, f = parsed
        if len(f) < 9:
            return
        src, src_name, src_flags = f[1], f[2], _flags(f[3])
        dst, dst_name, dst_flags = f[5], f[6], _flags(f[7])
        src_npc, dst_npc = npc_id(src), npc_id(dst)
        mine_src, mine_dst = bool(src_flags & AFFILIATION_MINE), bool(dst_flags & AFFILIATION_MINE)
        if dst_npc and mine_src and event.endswith(("_DAMAGE", "_MISSED", "_AURA_APPLIED")):
            self.engaged[dst] = True
        if src_npc and mine_dst:
            self.engaged[src] = True

        if event == "UNIT_DIED" and dst_npc and self.engaged.pop(dst, None) and dst not in self.dead:
            self.dead.add(dst)
            entry = self.store.entry(dst_npc, dst_name)
            entry["kills"] = entry.get("kills", 0) + 1
            entry["lastKill"] = int(time.time())
            if len(self.dead) > 5000:
                self.dead.clear()
            return
        if event == "PARTY_KILL" and dst_npc and mine_src and dst not in self.dead:
            self.dead.add(dst)
            self.engaged.pop(dst, None)
            entry = self.store.entry(dst_npc, dst_name)
            entry["kills"] = entry.get("kills", 0) + 1
            entry["lastKill"] = int(time.time())
            return

        # aptitudes utilisées par une créature engagée (ou contre moi)
        if src_npc and event in SPELL_EVENTS and len(f) >= 12 and (src in self.engaged or mine_dst):
            entry = self.store.entry(src_npc, src_name)
            spells = entry.setdefault("spells", {})
            key = str(_int(f[9]))
            if key != "0" and (key in spells or len(spells) < MAX_SPELLS):
                spell = spells.setdefault(key, {"name": f[10], "count": 0})
                spell["count"] += 1

        # PV, ressource, carte, niveau (journalisation avancée) de la créature décrite par la ligne
        if event.endswith(("_DAMAGE", "_CAST_SUCCESS", "_HEAL", "_ENERGIZE")) and "_PERIODIC" not in event:
            start = 9 if event.startswith("SWING") else 12
            adv = _advanced(f, start)
            if adv:
                creature = npc_id(adv["guid"])
                if creature and adv["guid"] in self.engaged:
                    name = src_name if adv["guid"] == src else dst_name
                    entry = self.store.entry(creature, name)
                    if adv["hp"] > entry.get("hp", 0):
                        entry["hp"] = adv["hp"]
                    if adv["power"] > 0 and adv["power_type"] >= 0:
                        entry["power"], entry["powerType"] = max(adv["power"], entry.get("power", 0)), adv["power_type"]
                    if adv["level"] > 0:
                        entry["level"] = adv["level"]
                    if adv["map"] > 0:
                        maps = entry.setdefault("maps", {})
                        maps[str(adv["map"])] = maps.get(str(adv["map"]), 0) + 1
                    entry["seen"] = int(time.time())
        if len(self.engaged) > 20000:
            self.engaged.clear()


class Bestiary:
    def __init__(self, path, logs_dir=None):
        self.path = path
        self.logs_dir = logs_dir
        self.lock = threading.Lock()
        self.data = {"created": int(time.time()), "files": {}, "creatures": {}, "notes": {}}
        self.addon = {}          # données de l'addon (instantané du personnage)
        self.version = 0         # change à chaque modification : l'onglet recalcule sa liste
        self.busy = False
        self.last_poll = 0.0
        self.error = ""
        self.reader = CombatLogReader(self)
        self.listeners = []      # autres lecteurs des mêmes lignes (bilans de combat) : le fichier n'est lu qu'une fois
        self._load()

    # ------------------------------------------------------------------ fichier
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                for key in ("files", "creatures", "notes"):
                    if isinstance(stored.get(key), dict):
                        self.data[key] = stored[key]
                self.data["created"] = stored.get("created", self.data["created"])
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with self.lock:
            text = json.dumps(self.data, ensure_ascii=False)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
        except OSError as e:
            self.error = f"bestiaire non enregistré : {e}"

    # ------------------------------------------------------------------ données
    def entry(self, creature_id, name=""):
        """Fiche (journal de combat) d'une créature ; appelée sous verrou par le lecteur."""
        entry = self.data["creatures"].setdefault(str(creature_id), {"name": name, "kills": 0,
                                                                     "first": int(time.time())})
        if name and not entry.get("name"):
            entry["name"] = name
        return entry

    def set_addon(self, addon):
        if addon is not self.addon:
            self.addon = addon or {}
            self.version += 1

    def set_note(self, creature_id, text):
        with self.lock:
            if text.strip():
                self.data["notes"][str(creature_id)] = text.strip()
            else:
                self.data["notes"].pop(str(creature_id), None)
            self.version += 1
        self.save()

    def note(self, creature_id):
        return self.data["notes"].get(str(creature_id), "")

    def entries(self):
        """Fiches fusionnées (journal + addon + note), une par créature."""
        with self.lock:
            log = {k: dict(v) for k, v in self.data["creatures"].items()}
        out = []
        for key in set(log) | set(self.addon):
            out.append(merge_entry(key, log.get(key, {}), self.addon.get(key, {}), self.note(key)))
        return out

    # ------------------------------------------------------------------ journal de combat
    def poll(self, now=None):
        """Toutes les 5 s : lit la suite du journal de combat dans un fil (l'interface ne se fige jamais)."""
        now = now or time.time()
        if self.busy or now - self.last_poll < 5 or not self.logs_dir or not os.path.isdir(self.logs_dir):
            return
        self.last_poll = now
        self.busy = True
        threading.Thread(target=self._read_logs, daemon=True).start()

    def read_logs_now(self):
        """Lecture immédiate (tests, bouton « Relire »)."""
        self.busy = True
        self._read_logs()

    def _read_logs(self):
        changed = False
        try:
            files = sorted(glob.glob(os.path.join(self.logs_dir, "WoWCombatLog*.txt")), key=os.path.getmtime)
            budget = MAX_READ_PER_POLL
            for path in files:
                name = os.path.basename(path)
                size = os.path.getsize(path)
                known = self.data["files"].get(name)
                if known is None:
                    # fichier d'avant la création du bestiaire : on ne relit pas des mois d'historique
                    known = size if os.path.getmtime(path) < self.data["created"] else 0
                    self.data["files"][name] = known
                if known > size:      # fichier recréé
                    known = 0
                if known == size:
                    continue
                with open(path, "rb") as f:
                    f.seek(known)
                    chunk = f.read(min(budget, size - known))
                end = chunk.rfind(b"\n")
                if end < 0:
                    continue
                chunk = chunk[:end + 1]
                with self.lock:
                    for raw in chunk.decode("utf-8", "replace").splitlines():
                        parsed = parse_line(raw)
                        if not parsed:
                            continue
                        self.reader.feed(raw, parsed)
                        for listener in self.listeners:
                            try:
                                listener.feed(parsed[0], parsed[1], raw)
                            except Exception as e:      # noqa: BLE001 - un bilan raté ne bloque pas le bestiaire
                                self.error = f"bilan de combat : {e}"
                    self.data["files"][name] = known + len(chunk)
                changed = True
                budget -= len(chunk)
                if budget <= 0:
                    break
            for name in [n for n in self.data["files"] if not os.path.exists(os.path.join(self.logs_dir, n))]:
                self.data["files"].pop(name, None)
            self.error = ""
        except OSError as e:
            self.error = f"journal de combat illisible : {e}"
        finally:
            if changed:
                self.version += 1
                self.save()
            self.busy = False


def merge_entry(key, log, addon, note):
    """Une fiche affichable à partir des deux sources."""
    items = addon.get("items") or {}
    loots = _int(addon.get("loots"))
    loot = sorted(({"id": _int(i), "name": it.get("name", ""), "quality": _int(it.get("q"), 1),
                    "count": _int(it.get("c")), "times": _int(it.get("n")),
                    "rate": (_int(it.get("n")) / loots) if loots else 0.0}
                   for i, it in items.items() if isinstance(it, dict)), key=lambda x: -x["times"])
    spells = sorted(({"id": _int(s), "name": v.get("name", ""), "count": _int(v.get("count"))}
                     for s, v in (log.get("spells") or {}).items() if isinstance(v, dict)), key=lambda x: -x["count"])
    level_min = _int(addon.get("lvl")) or _int(log.get("level"))
    level_max = max(_int(addon.get("lvlMax")), level_min)
    power_type = log.get("powerType", addon.get("ptype"))
    zones = addon.get("zones") or {}
    return {
        "id": _int(key), "name": addon.get("name") or log.get("name") or f"Créature {key}",
        "kills": _int(log.get("kills")), "levelMin": level_min, "levelMax": level_max,
        "hp": max(_int(log.get("hp")), _int(addon.get("hp"))),
        "power": max(_int(log.get("power")), _int(addon.get("power"))),
        "powerName": POWER_NAMES.get(_int(power_type, -1), "Ressource") if power_type is not None else "",
        "type": addon.get("ctype", ""), "family": addon.get("family", ""),
        "rank": CLASSIFICATIONS.get(addon.get("class", ""), addon.get("class", "")),
        "zones": sorted(zones, key=lambda z: -_int(zones[z])) if isinstance(zones, dict) else [],
        "maps": sorted((log.get("maps") or {}), key=lambda m: -_int(log["maps"][m])),
        "spells": spells, "loot": loot, "loots": loots, "money": _int(addon.get("money")),
        "avgMoney": (_int(addon.get("money")) / loots) if loots else 0,
        "seen": max(_int(log.get("seen")), _int(addon.get("seen")), _int(log.get("lastKill"))),
        "note": note,
    }
