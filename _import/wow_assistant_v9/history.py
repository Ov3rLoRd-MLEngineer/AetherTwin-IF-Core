"""
Historique de progression (niveau, XP, or, niveau d'objet) pour WoW Assistant
Stocké dans history.json à côté de l'appli.
"""
import json
import os
import time


class History:
    def __init__(self, path, min_interval=300, max_entries=5000):
        self.path = path
        self.min_interval = min_interval
        self.max_entries = max_entries
        self.entries = []
        self._baseline = {}   # personnage -> première entrée vue pendant cette session
        self._latest = {}     # personnage -> dernière entrée vue pendant cette session
        self._load()

    # ------------------------------------------------------------------ fichier
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.entries = data[-self.max_entries:]
        except (OSError, ValueError):
            self.entries = []

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.entries[-self.max_entries:], f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"Historique non sauvegardé : {e}")

    # ------------------------------------------------------------------ enregistrement
    @staticmethod
    def _entry(character, extras=None):
        entry = {
            "t": int(time.time()),
            "char": character.key,
            "level": character.level,
            "xp": character.xp,
            "xp_max": character.xp_max,
            "money": character.money,
            "ilvl": character.ilvl,
            "zone": character.zone,
            "played": character.played_total,
        }
        entry.update(extras or {})
        return entry

    def record(self, character, extras=None):
        """Ajoute un point si quelque chose a changé (et pas plus d'un point par intervalle,
        sauf changement de niveau). Retourne True si un point a été ajouté."""
        if not character.name:
            return False
        entry = self._entry(character, extras)
        key = entry["char"]
        self._baseline.setdefault(key, entry)
        self._latest[key] = entry

        last = next((e for e in reversed(self.entries) if e.get("char") == key), None)
        if last:
            same = all(last.get(k) == entry.get(k) for k in ("level", "xp", "money", "ilvl", "quests", "ach_points"))
            if same:
                return False
            level_up = entry["level"] != last.get("level")
            if not level_up and entry["t"] - last.get("t", 0) < self.min_interval:
                return False
        self.entries.append(entry)
        self._save()
        return True

    # ------------------------------------------------------------------ lecture
    def get_recent(self, char_key, n=20):
        return [e for e in self.entries if e.get("char") == char_key][-n:]

    def session_summary(self, char_key):
        """Gains depuis le lancement de l'appli : niveaux, or (en cuivre), durée."""
        base, latest = self._baseline.get(char_key), self._latest.get(char_key)
        if not base or not latest:
            return {"levels": 0, "money": 0, "seconds": 0}
        return {
            "levels": latest["level"] - base["level"],
            "money": latest["money"] - base["money"],
            "seconds": latest["t"] - base["t"],
        }


# ===========================================================================
#  Journal d'activité : événements déduits en comparant deux états successifs
# ===========================================================================
def snapshot_state(character, quests, data):
    """Résumé de l'état actuel, comparé au précédent pour fabriquer le journal d'activité."""
    ach = data.achievements
    col = data.collections
    return {
        "t": 0,   # rempli par l'appelant (heure de l'écriture du fichier par le jeu)
        "level": character.level,
        "zone": character.zone,
        "spec": character.spec,
        "ilvl": character.ilvl,
        "money": character.money,
        "gear": {str(slot): item.get("name", "") for slot, item in character.equipment.items()},
        "quests": {str(q["id"]): [q["name"], q["status"]] for q in quests.quests},
        "ach_points": ach.get("points", 0),
        "ach_recent": [a.get("id") for a in ach.get("recent", [])],
        "ach_names": {str(a.get("id")): a.get("name", "") for a in ach.get("recent", [])},
        "mounts": {str(m.get("id")): m.get("name", "") for m in col["mounts"].get("list", [])},
        "pets": col["pets"].get("owned", 0),
        "toys": col["toys"].get("collected", 0),
    }


def _money_text(copper):
    gold = abs(copper) // 10000
    silver = (abs(copper) // 100) % 100
    return f"{gold} or {silver} arg" if gold else f"{silver} arg"


def diff_states(prev, new):
    """[(type, texte)] décrivant ce qui a changé entre deux états."""
    events = []
    if new["level"] != prev.get("level", new["level"]):
        events.append(("level", f"Niveau {prev['level']} → {new['level']}"))
    if new["zone"] and new["zone"] != prev.get("zone", new["zone"]):
        events.append(("zone", f"Arrivée à {new['zone']}"))
    if new["spec"] and new["spec"] != prev.get("spec", new["spec"]):
        events.append(("spec", f"Spécialisation : {new['spec']}"))
    delta = new["money"] - prev.get("money", new["money"])
    if abs(delta) >= 10000:
        events.append(("gold", f"Or {'+' if delta > 0 else '-'}{_money_text(delta)}"))
    if new["ilvl"] != prev.get("ilvl", new["ilvl"]):
        events.append(("gear", f"Niveau d'objet {prev['ilvl']:g} → {new['ilvl']:g}"))
    for slot, name in new["gear"].items():
        if name and name != prev.get("gear", {}).get(slot, name):
            events.append(("gear", f"Équipé : {name}"))

    old_quests, new_quests = prev.get("quests", {}), new["quests"]
    for qid, (name, status) in new_quests.items():
        if qid not in old_quests:
            events.append(("quest", f"Quête acceptée : {name}"))
        elif status == "complete" and old_quests[qid][1] != "complete":
            events.append(("quest", f"Objectifs terminés : {name}"))
    for qid, (name, status) in old_quests.items():
        if qid not in new_quests:
            text = "Quête rendue" if status == "complete" else "Quête retirée du journal"
            events.append(("quest", f"{text} : {name}"))

    for aid in new["ach_recent"]:
        if aid not in prev.get("ach_recent", new["ach_recent"]):
            events.append(("achievement", f"Haut fait : {new['ach_names'].get(str(aid), aid)}"))
    for mid, name in new["mounts"].items():
        if prev.get("mounts") and mid not in prev["mounts"]:
            events.append(("collection", f"Nouvelle monture : {name}"))
    if new["pets"] > prev.get("pets", new["pets"]):
        events.append(("collection", f"Mascottes : +{new['pets'] - prev['pets']}"))
    if new["toys"] > prev.get("toys", new["toys"]):
        events.append(("collection", f"Jouets : +{new['toys'] - prev['toys']}"))
    return events


class ActivityLog:
    """Événements horodatés, gardés dans activity.json (même quand l'appli est fermée entre deux)."""

    def __init__(self, path, max_events=1000):
        self.path = path
        self.max_events = max_events
        self.events = []
        self.last_state = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.events = data.get("events", [])[-max_events:]
            self.last_state = data.get("last_state", {})
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"events": self.events[-self.max_events:], "last_state": self.last_state},
                          f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"Journal d'activité non sauvegardé : {e}")

    def process(self, char_key, state, when):
        """Compare avec l'état précédent du personnage, enregistre les événements, retourne les nouveaux."""
        state = dict(state, t=when)
        prev = self.last_state.get(char_key)
        new_events = []
        if prev and when >= prev.get("t", 0):
            for kind, text in diff_states(prev, state):
                new_events.append({"t": when, "char": char_key, "kind": kind, "text": text})
        self.events.extend(new_events)
        self.last_state[char_key] = state
        self._save()
        return new_events

    def merge_game_log(self, char_key, log):
        """Ajoute les événements notés par l'addon (morts, quêtes rendues avec XP, niveaux, hauts faits).
        Dédoublonnage : un événement déjà déduit (même texte avant la parenthèse, à moins de 10 min) est remplacé
        par la version de l'addon, plus détaillée."""
        added = 0
        for entry in log or []:
            t, text, kind = int(entry.get("t", 0)), str(entry.get("text", "")), entry.get("kind", "")
            if not t or not text:
                continue
            base = text.split(" (")[0]
            duplicate = None
            for existing in reversed(self.events[-400:]):
                if existing.get("char") != char_key:
                    continue
                if existing.get("t") == t and existing.get("text") == text:
                    duplicate = existing
                    break
                if existing.get("text", "").split(" (")[0] == base and abs(existing.get("t", 0) - t) < 600:
                    duplicate = existing
                    break
            if duplicate is not None:
                if duplicate.get("text") != text and len(text) > len(duplicate.get("text", "")):
                    duplicate.update(text=text, kind=kind or duplicate.get("kind"), t=t)
                    added += 1
                continue
            self.events.append({"t": t, "char": char_key, "kind": kind, "text": text})
            added += 1
        if added:
            self.events.sort(key=lambda e: e.get("t", 0))
            self._save()
        return added

    def recent(self, char_key=None, n=60):
        items = [e for e in self.events if char_key is None or e.get("char") == char_key]
        return list(reversed(items[-n:]))
