"""
Bilans de combat : un résumé après chaque boss (ENCOUNTER_START / END) et chaque clé Mythique+
(CHALLENGE_MODE_START / END), tiré du journal de combat que le jeu écrit (Logs/WoWCombatLog*.txt).

Analyse **après coup**, hors du jeu : depuis Midnight les addons n'ont plus accès aux données de combat, mais le
fichier du journal est toujours écrit et Warcraft Logs (entre autres) s'en sert de la même façon. Rien n'est envoyé
nulle part : les bilans restent dans `%APPDATA%\\WoWAssistant\\combat_reports.json` (ils contiennent les noms des
membres du groupe : jamais dans le dépôt).

Par groupe (le joueur et les membres de son groupe / raid) : dégâts et soins (par seconde), dégâts subis,
interruptions, dissipations, morts avec les derniers coups reçus, et ce qui a fait le plus mal au joueur.
"""
import json
import os
import re
import threading
import time

from bestiary import _advanced, _flags, _int

REPORTS_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "WoWAssistant",
                            "combat_reports.json")
MAX_REPORTS = 40
MINE, PARTY, RAID, TYPE_PLAYER = 0x1, 0x2, 0x4, 0x400
DAMAGE = ("SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE", "SWING_DAMAGE", "SPELL_BUILDING_DAMAGE",
          "DAMAGE_SPLIT")
HEAL = ("SPELL_HEAL", "SPELL_PERIODIC_HEAL")
DIFFICULTIES = {1: "Normal", 2: "Héroïque", 8: "Mythique+", 14: "Normal", 15: "Héroïque", 16: "Mythique",
                17: "Recherche de raid", 23: "Mythique", 205: "Suivi", 208: "Gouffre"}
_TS = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?")


def line_time(line, default=None):
    """Horodatage d'une ligne (« 11/23/2026 07:12:33.1234-5  ... »), en heure locale."""
    m = _TS.match(line)
    if not m:
        return default if default is not None else time.time()
    month, day, year, hh, mm, ss, frac = m.groups()
    year = int(year) if year else time.localtime().tm_year
    year += 2000 if year < 100 else 0
    stamp = time.mktime((year, int(month), int(day), int(hh), int(mm), int(ss), 0, 0, -1))
    return stamp + (float("0." + frac) if frac else 0.0)


def _in_group(flags):
    return bool(flags & (MINE | PARTY | RAID)) and bool(flags & TYPE_PLAYER)


def _short(name):
    return (name or "?").split("-")[0]


class _Fight:
    def __init__(self, kind, name, start, **info):
        self.kind, self.name, self.start = kind, name, start
        self.info = info
        self.players = {}        # nom -> {damage, healing, taken, interrupts, dispels, deaths}
        self.me = ""
        self.hurt_me = {}        # sort -> dégâts reçus par le joueur
        self.recent = {}         # nom -> 5 derniers coups reçus
        self.deaths = []
        self.last = start

    def player(self, name):
        return self.players.setdefault(_short(name), {"damage": 0, "healing": 0, "taken": 0, "interrupts": 0,
                                                       "dispels": 0, "deaths": 0})

    def feed(self, event, f, t):
        self.last = t
        src_name, src_flags = f[2], _flags(f[3])
        dst_name, dst_flags = f[6], _flags(f[7])
        if src_flags & MINE and src_flags & TYPE_PLAYER:
            self.me = _short(src_name)
        spell_event = not event.startswith("SWING")
        base = 12 if spell_event else 9
        if event in DAMAGE or event in HEAL:
            start = base + (17 if _advanced(f, base) else 0)
            amount = _int(f[start]) if len(f) > start else 0
            if event in HEAL:
                amount -= _int(f[start + 1]) if len(f) > start + 1 else 0      # sans le surplus de soins
                if _in_group(src_flags) and amount > 0:
                    self.player(src_name)["healing"] += amount
                return
            src_owner_mine = bool(src_flags & MINE)       # familiers du joueur comptés pour lui
            if _in_group(src_flags):
                self.player(src_name)["damage"] += amount
            elif src_owner_mine and self.me:
                self.player(self.me)["damage"] += amount
            if _in_group(dst_flags) and amount > 0:
                self.player(dst_name)["taken"] += amount
                spell = f[10] if spell_event and len(f) > 10 else "Mêlée"
                hits = self.recent.setdefault(_short(dst_name), [])
                hits.append({"spell": spell, "from": _short(src_name), "amount": amount})
                del hits[:-5]
                if dst_flags & MINE:
                    self.hurt_me[spell] = self.hurt_me.get(spell, 0) + amount
        elif event == "SPELL_INTERRUPT" and _in_group(src_flags):
            self.player(src_name)["interrupts"] += 1
        elif event in ("SPELL_DISPEL", "SPELL_STOLEN") and _in_group(src_flags):
            self.player(src_name)["dispels"] += 1
        elif event == "UNIT_DIED" and _in_group(dst_flags):
            name = _short(dst_name)
            self.player(name)["deaths"] += 1
            self.deaths.append({"name": name, "at": round(t - self.start), "hits": list(self.recent.get(name, []))})

    def report(self, end, success, duration=None):
        duration = max(1.0, duration if duration else end - self.start)
        players = sorted(({"name": n, **p, "dps": round(p["damage"] / duration), "hps": round(p["healing"] / duration)}
                          for n, p in self.players.items()), key=lambda p: -p["damage"])
        return {"kind": self.kind, "name": self.name, "start": int(self.start), "duration": round(duration),
                "success": bool(success), "me": self.me, "players": players, "deaths": self.deaths[:20],
                "hurtMe": sorted(({"spell": s, "amount": a} for s, a in self.hurt_me.items()),
                                 key=lambda h: -h["amount"])[:6], **self.info}


class ReportBuilder:
    """Reçoit les lignes du journal (via le lecteur du Bestiaire) et produit les bilans."""

    def __init__(self, path=REPORTS_PATH):
        self.path = path
        self.reports = []
        self.lock = threading.Lock()
        self.version = 0
        self.encounter = None
        self.run = None
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.reports = [r for r in data.get("reports", []) if isinstance(r, dict)]
        except (OSError, ValueError, AttributeError):
            self.reports = []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "reports": self.reports[-MAX_REPORTS:]}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _add(self, report):
        with self.lock:
            self.reports.append(report)
            del self.reports[:-MAX_REPORTS]
            self.version += 1
        self._save()

    def feed(self, event, f, raw):
        if event in ("ENCOUNTER_START", "ENCOUNTER_END", "CHALLENGE_MODE_START", "CHALLENGE_MODE_END"):
            self._control(event, f, line_time(raw))
            return
        if len(f) < 9 or (self.encounter is None and self.run is None):
            return
        t = None
        for fight in (self.encounter, self.run):
            if fight is not None:
                if t is None:
                    t = line_time(raw, fight.last)
                fight.feed(event, f, t)

    def _control(self, event, f, t):
        if event == "ENCOUNTER_START" and len(f) >= 5:
            difficulty = _int(f[3])
            self.encounter = _Fight("boss", f[2], t, difficulty=DIFFICULTIES.get(difficulty, f"difficulté {difficulty}"),
                                    groupSize=_int(f[4]), keyLevel=self.run.info.get("keyLevel") if self.run else 0)
        elif event == "ENCOUNTER_END" and self.encounter is not None and len(f) >= 6:
            fight_ms = _int(f[6]) if len(f) > 6 else 0
            report = self.encounter.report(t, _int(f[5]) == 1, fight_ms / 1000 if fight_ms else None)
            self.encounter = None
            if self.run is not None:
                self.run.info.setdefault("bosses", []).append({"name": report["name"], "success": report["success"],
                                                               "duration": report["duration"]})
            self._add(report)
        elif event == "CHALLENGE_MODE_START" and len(f) >= 5:
            self.run = _Fight("clé", f[1], t, keyLevel=_int(f[4]), difficulty="Mythique+")
        elif event == "CHALLENGE_MODE_END" and self.run is not None:
            total_ms = _int(f[4]) if len(f) > 4 else 0
            report = self.run.report(t, _int(f[2]) == 1, total_ms / 1000 if total_ms else None)
            self.run = None
            self._add(report)

    # ------------------------------------------------------------------ lecture
    def latest(self, n=20):
        with self.lock:
            return list(reversed(self.reports[-n:]))


def describe(report):
    """Bilan en texte (pour Hermes et le presse-papiers)."""
    if not report:
        return ""
    when = time.strftime("%d/%m %H:%M", time.localtime(report.get("start", 0)))
    head = (f"{'Boss' if report['kind'] == 'boss' else 'Clé Mythique+'} : {report['name']}"
            + (f" +{report['keyLevel']}" if report.get("keyLevel") else "")
            + f" ({report.get('difficulty', '')}), {when}, {format_duration(report['duration'])}, "
            + ("réussi" if report["success"] else "échec / abandon"))
    lines = [head, f"Joueur : {report.get('me') or '?'}"]
    for p in report["players"][:10]:
        lines.append(f"- {p['name']} : {p['dps']} DPS, {p['hps']} HPS, {p['taken']} dégâts subis, "
                     f"{p['interrupts']} interruptions, {p['dispels']} dissipations, {p['deaths']} mort(s)")
    for d in report["deaths"][:8]:
        hits = ", ".join(f"{h['spell']} ({h['from']}, {h['amount']})" for h in d["hits"][-3:])
        lines.append(f"Mort : {d['name']} à {format_duration(d['at'])} — derniers coups : {hits or 'inconnus'}")
    if report.get("hurtMe"):
        lines.append("Ce qui a fait le plus mal au joueur : "
                     + ", ".join(f"{h['spell']} ({h['amount']})" for h in report["hurtMe"]))
    if report.get("bosses"):
        lines.append("Boss de la clé : " + ", ".join(f"{b['name']} ({'tué' if b['success'] else 'raté'}, "
                                                     f"{format_duration(b['duration'])})" for b in report["bosses"]))
    return "\n".join(lines)


def format_duration(seconds):
    """« 45 s », « 20 min 05 s » (pas « 20:05 », qu'on lirait comme une heure)."""
    seconds = max(0, int(seconds or 0))
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


ANALYSIS_PROMPT = ("Voici le bilan de mon dernier combat, tiré du journal de combat du jeu (WoW Assistant). "
                   "Analyse-le pour MOI (le joueur indiqué) : ce qui a coûté le combat ou du temps, mes morts et ce "
                   "qui les a causées (mécaniques à éviter, défensifs à utiliser), mon DPS / HPS par rapport au groupe, "
                   "les interruptions. Donne 3 conseils concrets pour la prochaine fois. Vérifie les mécaniques de boss "
                   "sur Wowhead si besoin.\n\n")
