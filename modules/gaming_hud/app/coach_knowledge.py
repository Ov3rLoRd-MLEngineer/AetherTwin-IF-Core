"""
Base de connaissances du coach (coach_knowledge.json) : ce que Hermes a vérifié, et surtout ce que le joueur a corrigé.

Même principe que l'apprentissage de Scantrad sur le mode manuel : le travail du joueur fait foi.
  - **joueur** : correction ou règle donnée par le joueur. Priorité absolue, jamais périmée.
  - **sourcé** : fait vérifié par Hermes sur une page (Wowhead, site officiel, guide...) : lien et date obligatoires ;
    à revérifier après REVERIFY_DAYS jours, ou dès que le jeu change de patch (12.1.5 -> 12.2.0 : version lue dans
    .build.info, voir gameversion.py).
  - **rejeté** : écarté par le joueur ; gardé pour que Hermes ne le réenregistre pas.

Les textes enregistrés sont des données : ils sont rendus à Hermes comme tels, jamais exécutés. Fichier propre à
l'appli (pas dans le dossier du jeu), écrit de façon atomique.
"""
import json
import os
import re
import threading
import time
import unicodedata

# dans le profil Windows (comme les réglages partagés) : la même base pour toutes les copies de l'appli et pour
# le serveur MCP lancé par Hermes, quel que soit le dossier d'où il tourne
DEFAULT_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "WoWAssistant",
                            "coach_knowledge.json")
REVERIFY_DAYS = 45
MAX_ENTRIES = 3000
MAX_FACT = 1200
TOPICS = ("règle", "quête", "build", "équipement", "talents", "métier", "donjon", "raid", "objet", "zone",
          "mécanique", "économie", "autre")
STATUSES = ("joueur", "sourcé", "rejeté")


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text):
    return {w for w in re.findall(r"[a-z0-9']{3,}", _norm(text))}


class KnowledgeBase:
    def __init__(self, path, patch_fn=None):
        self.path = path
        self.patch_fn = patch_fn      # -> patch du jeu installé (« 12.1.5 ») ; chaque fait est daté avec
        self.entries = []
        self.version = 0
        self._lock = threading.Lock()
        self._mtime = None
        self.load()

    # ------------------------------------------------------------------ fichier
    def load(self):
        try:
            self._mtime = os.path.getmtime(self.path)
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.entries = [e for e in data.get("entries", []) if isinstance(e, dict) and e.get("fact")]
        except (OSError, ValueError, AttributeError):
            self.entries = []
        self.version += 1

    def reload_if_changed(self):
        """Hermes (serveur MCP, autre processus) et l'appli écrivent le même fichier."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if mtime != self._mtime:
            self.load()

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": self.entries[-MAX_ENTRIES:]}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        self._mtime = os.path.getmtime(self.path)
        self.version += 1

    def current_patch(self):
        try:
            return (self.patch_fn() if self.patch_fn else "") or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------ écriture
    def add(self, topic, subject, fact, source="", status="sourcé", question=""):
        """Ajoute ou met à jour (même sujet et même thème). Retourne (ok, message, entrée)."""
        topic = topic if topic in TOPICS else "autre"
        subject, fact, source = (str(subject or "").strip()[:200], str(fact or "").strip()[:MAX_FACT],
                                 str(source or "").strip()[:500])
        if status not in STATUSES:
            return False, "statut inconnu", None
        if not subject or not fact:
            return False, "sujet et fait obligatoires", None
        if status == "sourcé" and not re.match(r"^https?://", source):
            return False, "un fait vérifié doit citer la page consultée (lien http/https)", None
        patch = self.current_patch()
        with self._lock:
            self.reload_if_changed()
            now = time.time()
            key = (topic, _norm(subject))
            for e in self.entries:
                if (e["topic"], _norm(e["subject"])) == key:
                    if e["status"] == "joueur" and status != "joueur":
                        return False, "le joueur a déjà tranché ce sujet : sa version fait foi", e
                    if e["status"] == "rejeté" and status != "joueur" and _norm(e["fact"]) == _norm(fact):
                        return False, "ce fait a été rejeté par le joueur", e
                    if patch:
                        e["patch"] = patch
                    e.update(fact=fact, source=source, status=status, verified=now,
                             history=(e.get("history") or [])[-4:] + [{"fact": e["fact"], "at": e["verified"]}])
                    if question:
                        e["question"] = question[:300]
                    self._save()
                    return True, "mis à jour", e
            entry = {"id": f"k{int(now * 1000):x}", "topic": topic, "subject": subject, "fact": fact,
                     "source": source, "status": status, "created": now, "verified": now, "uses": 0}
            if patch:
                entry["patch"] = patch
            if question:
                entry["question"] = question[:300]
            self.entries.append(entry)
            self._save()
            return True, "enregistré", entry

    def set_status(self, entry_id, status):
        with self._lock:
            self.reload_if_changed()
            for e in self.entries:
                if e["id"] == entry_id and status in STATUSES:
                    e["status"], e["verified"] = status, time.time()
                    patch = self.current_patch()
                    if patch:
                        e["patch"] = patch
                    self._save()
                    return True
        return False

    def delete(self, entry_id):
        with self._lock:
            self.reload_if_changed()
            before = len(self.entries)
            self.entries = [e for e in self.entries if e["id"] != entry_id]
            if len(self.entries) != before:
                self._save()
                return True
        return False

    # ------------------------------------------------------------------ lecture
    def stale_reason(self, e, now=None, patch=None):
        """Pourquoi un fait vérifié en ligne est à revérifier ("" sinon). Les corrections du joueur ne périment pas."""
        if e["status"] != "sourcé":
            return ""
        patch = self.current_patch() if patch is None else patch
        if patch and e.get("patch") and e["patch"] != patch:
            return f"patch changé : {e['patch']} → {patch}"
        if (now or time.time()) - e.get("verified", 0) > REVERIFY_DAYS * 86400:
            return f"vérifié il y a plus de {REVERIFY_DAYS} jours"
        return ""

    def stale(self, e, now=None, patch=None):
        return bool(self.stale_reason(e, now, patch))

    def search(self, query="", topic="", limit=12, count_use=False):
        """Entrées utiles pour une question : les règles du joueur d'abord, puis les plus proches de la question."""
        self.reload_if_changed()
        words = _words(query)
        now = time.time()
        patch = self.current_patch()
        scored = []
        for e in self.entries:
            if e["status"] == "rejeté" or (topic and e["topic"] != topic):
                continue
            overlap = len(words & _words(" ".join((e["subject"], e["fact"], e.get("question", "")))))
            if words and not overlap and e["topic"] != "règle":
                continue
            rank = (2 if e["status"] == "joueur" else 0) + (1 if e["topic"] == "règle" else 0)
            scored.append((rank, overlap, e.get("verified", 0), e))
        scored.sort(key=lambda t: t[:3], reverse=True)
        found = [t[3] for t in scored[:limit]]
        if count_use and found:
            with self._lock:
                for e in found:
                    e["uses"] = e.get("uses", 0) + 1
                try:
                    self._save()
                except OSError:
                    pass
        return [{"thème": e["topic"], "sujet": e["subject"], "fait": e["fact"],
                 "statut": {"joueur": "corrigé par le joueur (fait foi)", "sourcé": "vérifié en ligne"}[e["status"]]
                 + (f" — à revérifier ({self.stale_reason(e, now, patch)})" if self.stale(e, now, patch) else ""),
                 "source": e.get("source") or None, "version_du_jeu": e.get("patch") or None,
                 "vérifié_le": time.strftime("%d/%m/%Y", time.localtime(e.get("verified", 0)))} for e in found]

    def stats(self):
        self.reload_if_changed()
        out = {s: 0 for s in STATUSES}
        for e in self.entries:
            out[e["status"]] = out.get(e["status"], 0) + 1
        patch = self.current_patch()
        out["à revérifier"] = sum(1 for e in self.entries if self.stale(e, patch=patch))
        return out
