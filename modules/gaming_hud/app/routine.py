"""
Routine de la semaine : ce qu'il reste à faire avant la remise à zéro, pour chaque personnage.

- **Automatique** (données de l'addon) : Grande Chambre forte, écus et monnaies plafonnés à la semaine, quêtes
  hebdomadaires / journalières du journal, verrouillages de raid et de donjon, clés Mythique+ de la semaine.
- **Mes tâches** : ce que l'addon ne voit pas (Proie, commandes d'artisanat, logis, événement de la semaine...),
  cochées à la main, décochées seules à la remise à zéro (hebdomadaire ou quotidienne).
- **Autres personnages** : le fichier de l'addon ne garde que le dernier personnage joué ; un résumé de chacun est
  donc gardé ici à chaque lecture (`%APPDATA%\\WoWAssistant\\routine.json`, hors du dépôt et du dossier du jeu).

Heures de remise à zéro : données par l'addon (1.10, API du jeu) ; sinon calculées d'après la région (EU : mercredi
04:00 UTC, Amériques / Océanie : mardi 15:00 UTC).
"""
import json
import os
import threading
import time

ROUTINE_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "WoWAssistant", "routine.json")
DAY, WEEK = 86400, 7 * 86400
VAULT_KINDS = {3: "Raid", 1: "Donjons (Mythique+)", 6: "Monde (Gouffres...)", 2: "JcJ classé"}
PERIODS = {"weekly": "Hebdo", "daily": "Quotidien"}
MAX_TASKS = 40
# remise à zéro par défaut (UTC) : (jour de la semaine, heure) ; 0 = lundi
REGION_RESET = {"eu": (2, 4), "us": (1, 15), "kr": (3, 0), "tw": (3, 0)}


def _utc_reset(now, weekday, hour, period):
    """Prochaine remise à zéro (horodatage) après `now`."""
    t = time.gmtime(now)
    midnight = now - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)
    if period == "daily":
        nxt = midnight + hour * 3600
        return nxt if nxt > now else nxt + DAY
    nxt = midnight + ((weekday - t.tm_wday) % 7) * DAY + hour * 3600
    return nxt if nxt > now else nxt + WEEK


def next_resets(summary=None, now=None):
    """(quotidienne, hebdomadaire) : prochaines remises à zéro pour ce personnage."""
    now = now or time.time()
    summary = summary or {}
    region = str(summary.get("region") or "eu").lower()
    weekday, hour = REGION_RESET.get(region, REGION_RESET["eu"])
    daily, weekly = summary.get("dailyReset") or 0, summary.get("weeklyReset") or 0
    # données de l'addon : valables tant qu'elles sont dans le futur ; sinon on avance d'autant de périodes
    if daily:
        while daily <= now:
            daily += DAY
    else:
        daily = _utc_reset(now, weekday, hour, "daily")
    if weekly:
        while weekly <= now:
            weekly += WEEK
    else:
        weekly = _utc_reset(now, weekday, hour, "weekly")
    return daily, weekly


def format_delay(seconds):
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, DAY)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days} j {hours} h"
    return f"{hours} h {rest // 60:02d}" if hours else f"{rest // 60} min"


# --------------------------------------------------------------------------- résumé d'un personnage
def summarize(snapshot, now=None):
    """Résumé « semaine » d'un instantané de l'addon (dictionnaire brut)."""
    now = now or time.time()
    c = snapshot.get("character") or {}
    vault = snapshot.get("vault") or {}
    rows = {}
    for a in vault.get("activities") or []:
        rows.setdefault(a.get("type", 0), []).append(a)
    vault_rows = []
    for kind in [k for k in VAULT_KINDS if k in rows] + [k for k in rows if k not in VAULT_KINDS]:
        acts = sorted(rows[kind], key=lambda a: a.get("index", 0))[:3]
        vault_rows.append({"kind": kind, "label": VAULT_KINDS.get(kind, f"Activité {kind}"),
                           "slots": [[a.get("progress", 0), a.get("threshold", 0)] for a in acts],
                           "unlocked": sum(1 for a in acts if a.get("progress", 0) >= a.get("threshold", 0) > 0)})
    currencies = [{"name": x.get("name", ""), "weekly": x.get("weekly", 0), "weeklyMax": x.get("weeklyMax", 0),
                   "quantity": x.get("quantity", 0), "max": x.get("max", 0)}
                  for x in snapshot.get("currencies") or [] if (x.get("weeklyMax") or 0) > 0]
    quests = (snapshot.get("quests") or {}).get("list") or []
    periodic = [{"title": q.get("title", ""), "status": q.get("status", ""), "period": "weekly" if q.get("freq") == 2
                 else "daily", "zone": q.get("zone", "")} for q in quests if q.get("freq") in (1, 2)]
    lockouts = snapshot.get("lockouts") or {}
    instances = [{"name": i.get("name", ""), "difficulty": i.get("difficulty", ""), "progress": i.get("progress", 0),
                  "total": i.get("total", 0), "expires": i.get("expires", 0), "raid": bool(i.get("isRaid"))}
                 for i in lockouts.get("instances") or [] if (i.get("expires") or 0) > now]
    bosses = [b.get("name", "") for b in lockouts.get("worldBosses") or [] if (b.get("expires") or 0) > now]
    mp = snapshot.get("mythicPlus") or {}
    week = mp.get("week") or []
    key = mp.get("keystone")
    return {
        "name": c.get("name", "?"), "realm": c.get("realm", ""), "class": c.get("class", ""),
        "classFile": c.get("classFile", ""), "level": c.get("level", 0), "ilvl": c.get("ilvl", 0),
        "region": c.get("region", ""), "updated": int(c.get("updated") or snapshot.get("fileTime") or now),
        "weeklyReset": c.get("weeklyReset") or 0, "dailyReset": c.get("dailyReset") or 0,
        "vault": vault_rows, "vaultRewards": bool(vault.get("hasRewards")), "currencies": currencies,
        "periodic": periodic, "instances": instances, "worldBosses": bosses,
        "mythic": {"runs": len(week), "best": max([r.get("level", 0) for r in week] or [0]),
                   "keystone": f"{key.get('name', '')} +{key.get('level', 0)}" if key else ""},
    }


def char_key(summary):
    """Même clé que Character.key (personnage-royaume)."""
    name, realm = summary.get("name", "?"), summary.get("realm", "")
    return f"{name}-{realm}" if realm else name


def outdated(summary, now=None):
    """Résumé lu avant la dernière remise à zéro hebdomadaire : sa progression de la semaine ne vaut plus."""
    now = now or time.time()
    _daily, weekly = next_resets(summary, now)
    return summary.get("updated", 0) < weekly - WEEK


# --------------------------------------------------------------------------- liste à cocher
def checklist(summary, now=None):
    """Éléments automatiques : [{"group", "label", "detail", "done": True/False/None}]."""
    now = now or time.time()
    items = []
    old = outdated(summary, now)
    if summary.get("vaultRewards") and not old:
        items.append({"group": "Grande Chambre forte", "label": "Récompense à récupérer", "detail": "", "done": False})
    for row in summary.get("vault") or []:
        total = len(row["slots"])
        nxt = next((s for s in row["slots"] if s[0] < s[1]), None)
        detail = "" if nxt is None else f"prochain emplacement : {min(nxt[0], nxt[1])}/{nxt[1]}"
        items.append({"group": "Grande Chambre forte", "label": f"{row['label']} : {0 if old else row['unlocked']}/{total}",
                      "detail": "à refaire (nouvelle semaine)" if old else detail,
                      "done": (not old) and row["unlocked"] >= total and total > 0})
    for cur in summary.get("currencies") or []:
        weekly = 0 if old else cur["weekly"]
        items.append({"group": "Monnaies de la semaine", "label": f"{cur['name']} : {weekly}/{cur['weeklyMax']}",
                      "detail": f"en poche : {cur['quantity']}" + (f"/{cur['max']}" if cur["max"] else ""),
                      "done": weekly >= cur["weeklyMax"]})
    for q in summary.get("periodic") or []:
        items.append({"group": "Quêtes " + ("hebdomadaires" if q["period"] == "weekly" else "journalières"),
                      "label": q["title"], "detail": q["zone"],
                      "done": True if q["status"] == "complete" else (None if q["status"] == "failed" else False)})
    mythic = summary.get("mythic") or {}
    if mythic.get("keystone") or mythic.get("runs"):
        runs = 0 if old else mythic.get("runs", 0)
        items.append({"group": "Mythique+", "label": f"Clés cette semaine : {runs}"
                      + (f" (meilleure +{mythic['best']})" if runs and mythic.get("best") else ""),
                      "detail": f"clé en poche : {mythic['keystone']}" if mythic.get("keystone") else "", "done": None})
    for inst in summary.get("instances") or []:
        items.append({"group": "Verrouillages", "label": f"{inst['name']} ({inst['difficulty']})",
                      "detail": f"{inst['progress']}/{inst['total']} boss",
                      "done": inst["progress"] >= inst["total"] > 0})
    for boss in summary.get("worldBosses") or []:
        items.append({"group": "Verrouillages", "label": f"Boss mondial : {boss}", "detail": "vaincu", "done": True})
    return items


# --------------------------------------------------------------------------- fichier
class RoutineStore:
    def __init__(self, path=ROUTINE_PATH):
        self.path = path
        self.characters, self.tasks, self.done = {}, [], {}
        self._lock = threading.Lock()
        self._mtime = None
        self.load()

    def load(self):
        try:
            self._mtime = os.path.getmtime(self.path)
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self.characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
        self.tasks = [t for t in data.get("tasks") or [] if isinstance(t, dict) and t.get("text")]
        self.done = data.get("done") if isinstance(data.get("done"), dict) else {}

    def reload_if_changed(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if mtime != self._mtime:
            self.load()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "characters": self.characters, "tasks": self.tasks, "done": self.done}, f,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ personnages
    def record(self, snapshot, now=None):
        """Garde le résumé du personnage de cet instantané ; True s'il a changé."""
        if not (snapshot.get("character") or {}).get("name"):
            return False
        summary = summarize(snapshot, now)
        key = char_key(summary)
        with self._lock:
            self.reload_if_changed()
            known = self.characters.get(key) or {}
            if known.get("updated", 0) > summary["updated"]:      # instantané plus ancien (cache) : on garde
                return False
            if dict(known, updated=summary["updated"]) == summary:
                return False
            self.characters[key] = summary
            return self._save()

    def others(self, current_key):
        return sorted((s for k, s in self.characters.items() if k != current_key),
                      key=lambda s: -s.get("updated", 0))

    # ------------------------------------------------------------------ tâches perso
    def add_task(self, text, period="weekly"):
        text = str(text or "").strip()[:120]
        if not text or period not in PERIODS:
            return False
        with self._lock:
            self.reload_if_changed()
            if len(self.tasks) >= MAX_TASKS or any(t["text"].lower() == text.lower() for t in self.tasks):
                return False
            stamp = int(time.time() * 1000)
            ids = {t["id"] for t in self.tasks}
            while f"t{stamp:x}" in ids:  # deux ajouts dans la même milliseconde : identifiants distincts
                stamp += 1
            self.tasks.append({"id": f"t{stamp:x}", "text": text, "period": period})
            return self._save()

    def remove_task(self, task_id):
        with self._lock:
            self.reload_if_changed()
            self.tasks = [t for t in self.tasks if t["id"] != task_id]
            for marks in self.done.values():
                marks.pop(task_id, None)
            return self._save()

    def is_done(self, key, task, now=None):
        now = now or time.time()
        stamp = (self.done.get(key) or {}).get(task["id"], 0)
        daily, weekly = next_resets(self.characters.get(key), now)
        start = (weekly - WEEK) if task.get("period") == "weekly" else (daily - DAY)
        return stamp >= start

    def toggle(self, key, task_id, now=None):
        now = now or time.time()
        task = next((t for t in self.tasks if t["id"] == task_id), None)
        if task is None:
            return False
        with self._lock:
            self.reload_if_changed()
            marks = self.done.setdefault(key, {})
            if self.is_done(key, task, now):
                marks.pop(task_id, None)
            else:
                marks[task_id] = now
            return self._save()


# --------------------------------------------------------------------------- pour Hermes
def describe(store, current_key, now=None):
    """Texte (et données) de la semaine : personnage actuel, tâches, autres personnages."""
    now = now or time.time()
    current = store.characters.get(current_key) or {}
    daily, weekly = next_resets(current, now)
    out = {"personnage": current_key,
           "remise_à_zéro": {"hebdomadaire_dans": format_delay(weekly - now), "quotidienne_dans": format_delay(daily - now)},
           "à_faire": [], "fait": [], "mes_tâches": [], "autres_personnages": []}
    for item in checklist(current, now) if current else []:
        line = item["group"] + " : " + item["label"] + (f" ({item['detail']})" if item["detail"] else "")
        (out["fait"] if item["done"] else out["à_faire"]).append(line)
    for task in store.tasks:
        out["mes_tâches"].append(f"{task['text']} ({PERIODS[task['period']].lower()}) : "
                                 + ("fait" if store.is_done(current_key, task, now) else "à faire"))
    for s in store.others(current_key)[:12]:
        vault = sum(r["unlocked"] for r in s.get("vault") or []) if not outdated(s, now) else 0
        out["autres_personnages"].append(
            f"{s['name']} ({s.get('realm', '')}), niveau {s.get('level', 0)}, ilvl {s.get('ilvl', 0)} : chambre forte "
            f"{vault}/9" + (" — récompense à récupérer" if s.get("vaultRewards") and not outdated(s, now) else "")
            + f", vu le {time.strftime('%d/%m %H:%M', time.localtime(s.get('updated', 0)))}")
    return out


def plan_prompt(store, current_key, minutes, now=None):
    data = describe(store, current_key, now)
    return (f"J'ai {minutes} minutes de jeu. Voici ma routine de la semaine (données de WoW Assistant) :\n"
            + json.dumps(data, ensure_ascii=False, indent=1)
            + "\nPropose un plan concret pour ce temps-là, par ordre de priorité (ce qui rapporte le plus avant la "
              "remise à zéro, ce qui se perd si je ne le fais pas), avec une durée estimée par étape. Tiens compte de "
              "mon niveau : ce qui n'est pas encore accessible ne compte pas.")
