"""
Liens Wowhead et icônes d'objets pour WoW Assistant

- Lien : fabriqué automatiquement depuis le lien d'objet du jeu ("item:ID:enchant:gemmes...:bonus...").
  Exemple : item:256996::::::::80:::::1:13663  ->  https://www.wowhead.com/fr/item=256996?bonus=13663&lvl=80
- Surcharge : wowhead_links.json (par identifiant d'objet ou par emplacement) pour forcer un lien.
- Icônes : nom de l'icône lu sur Wowhead, image téléchargée une fois puis gardée dans cache/icons.
  Tout se fait dans un fil d'arrière-plan : en cas d'échec réseau, l'interface garde un repère coloré.
"""
import json
import os
import queue
import re
import threading
import time
import urllib.request

import pygame

from config import WoWConfig


# ===========================================================================
#  Liens
# ===========================================================================
def parse_item_string(item_string):
    """'item:ID:enchant:gem1:gem2:gem3:gem4:suffix:unique:linkLevel:spec:mask:context:nBonus:b1:b2...'"""
    parts = (item_string or "").split(":")

    def num(i):
        try:
            return int(parts[i])
        except (IndexError, ValueError):
            return 0

    n_bonus = num(13)
    return {
        "id": num(1),
        "enchant": num(2),
        "gems": [g for g in (num(3), num(4), num(5), num(6)) if g],
        "level": num(9),
        "bonus": [b for b in (num(14 + i) for i in range(n_bonus)) if b],
    }


def build_url(item_string):
    info = parse_item_string(item_string)
    if not info["id"]:
        return ""
    params = []
    if info["bonus"]:
        params.append("bonus=" + ":".join(str(b) for b in info["bonus"]))
    if info["enchant"]:
        params.append(f"ench={info['enchant']}")
    if info["gems"]:
        params.append("gems=" + ":".join(str(g) for g in info["gems"]))
    if info["level"]:
        params.append(f"lvl={info['level']}")
    url = f"{WoWConfig.WOWHEAD_BASE}/item={info['id']}"
    return url + ("?" + "&".join(params) if params else "")


def _simple_url(kind, ident):
    return f"{WoWConfig.WOWHEAD_BASE}/{kind}={ident}" if ident else ""


def npc_url(npc_id):
    return _simple_url("npc", npc_id)


def spell_url(spell_id):
    return _simple_url("spell", spell_id)


def quest_url(quest_id):
    return _simple_url("quest", quest_id)


def achievement_url(achievement_id):
    return _simple_url("achievement", achievement_id)


def item_url(item_id):
    return _simple_url("item", item_id)


def currency_url(currency_id):
    return _simple_url("currency", currency_id)


def transmog_set_url(set_id):
    return _simple_url("transmog-set", set_id)


def battle_pet_url(species_id):
    return _simple_url("battle-pet", species_id)


def talent_calc_url(loadout):
    """Calculateur de talents Wowhead à partir de la chaîne d'export du jeu."""
    return f"{WoWConfig.WOWHEAD_BASE}/talent-calc/blizzard/{loadout}" if loadout else ""


class LinkResolver:
    """Lien Wowhead d'un objet équipé : surcharge manuelle si elle existe, sinon automatique."""

    def __init__(self, path=None):
        self.path = path or WoWConfig.LINKS_FILE
        self._mtime = None
        self._by_item = {}
        self._by_slot = {}

    def _reload_if_needed(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self._mtime, self._by_item, self._by_slot = None, {}, {}
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"wowhead_links.json illisible : {e}")
            return
        self._by_item = {str(k): v for k, v in (data.get("by_item") or {}).items() if v}
        self._by_slot = {str(k): v for k, v in (data.get("by_slot") or {}).items() if v}

    def url_for(self, item):
        self._reload_if_needed()
        return (self._by_item.get(str(item.get("id")))
                or self._by_slot.get(str(item.get("slot")))
                or build_url(item.get("itemString", "")))


# ===========================================================================
#  Icônes
# ===========================================================================
class IconCache:
    """Icônes (objets, sorts, hauts faits) : téléchargées en arrière-plan, gardées sur disque.
    Clé de cache : l'identifiant seul pour les objets (compatible avec l'ancien cache), 'spell:ID'
    ou 'achievement:ID' pour le reste."""

    def __init__(self, cache_dir=None, names_file=None, enabled=None, display_names_file=None):
        self.cache_dir = cache_dir or WoWConfig.ICON_CACHE_DIR
        self.names_file = names_file or WoWConfig.ICON_NAMES_FILE
        self.display_names_file = display_names_file or WoWConfig.ITEM_NAMES_FILE
        self.enabled = WoWConfig.ONLINE_ICONS if enabled is None else enabled
        self._names = {}          # clé -> nom du fichier d'icône
        self._display = {}        # clé -> nom affichable (lu dans l'infobulle Wowhead)
        self._surfaces = {}
        self._failed = {}
        self._queued = set()
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._worker = None
        self.last_error = ""
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except OSError:
            pass
        self._names = self._load_json(self.names_file)
        self._display = self._load_json(self.display_names_file)

    @staticmethod
    def _load_json(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _save_json(path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
        except OSError:
            pass

    @staticmethod
    def _key(kind, ident):
        return str(ident) if kind == "item" else f"{kind}:{ident}"

    # ------------------------------------------------------------------ côté interface
    def get(self, ident, size, kind="item"):
        """Surface de l'icône (carrée) ou None si pas encore disponible."""
        key = self._key(kind, ident)
        name = self._names.get(key)
        if name:
            cache_key = (name, size)
            surf = self._surfaces.get(cache_key)
            if surf is not None:
                return surf
            path = os.path.join(self.cache_dir, name + ".jpg")
            if os.path.isfile(path):
                try:
                    image = pygame.image.load(path).convert()
                    surf = pygame.transform.smoothscale(image, (size, size))
                    self._surfaces[cache_key] = surf
                    return surf
                except pygame.error:
                    try:
                        os.remove(path)   # fichier corrompu : il sera retéléchargé
                    except OSError:
                        pass
        if self.enabled and ident:
            self._enqueue(kind, ident)
        return None

    def request(self, ident, kind="item"):
        """Demande le téléchargement (nom + icône) sans attendre le résultat."""
        if self.enabled and ident:
            self._enqueue(kind, ident)

    def display_name(self, ident, kind="item"):
        """Nom lu sur Wowhead (ex. composant dont le jeu n'a pas fourni le nom), ou ''."""
        return self._display.get(self._key(kind, ident), "")

    def stats(self, item_ids, kind="item"):
        """(icônes disponibles, total) pour l'affichage de diagnostic."""
        item_ids = list(item_ids)
        ready = 0
        for i in item_ids:
            name = self._names.get(self._key(kind, i))
            if name and os.path.isfile(os.path.join(self.cache_dir, name + ".jpg")):
                ready += 1
        return ready, len(item_ids)

    # ------------------------------------------------------------------ arrière-plan
    def _enqueue(self, kind, ident):
        item = (kind, ident)
        now = time.time()
        with self._lock:
            if item in self._queued:
                return
            if now - self._failed.get(item, 0) < WoWConfig.ICON_RETRY_SECONDS:
                return
            self._queued.add(item)
        self._queue.put(item)
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._worker.start()

    def _run(self):
        while True:
            try:
                item = self._queue.get(timeout=5)
            except queue.Empty:
                return
            try:
                self._download(*item)
                self._failed.pop(item, None)
            except Exception as e:   # réseau, format inattendu... : on retentera plus tard
                self._failed[item] = time.time()
                self.last_error = f"Icône {item[0]} {item[1]} : {e}"
            finally:
                with self._lock:
                    self._queued.discard(item)
            time.sleep(WoWConfig.ICON_THROTTLE)

    @staticmethod
    def _http_get(url):
        request = urllib.request.Request(url, headers={"User-Agent": "WoWAssistant/1.4 (outil personnel)"})
        with urllib.request.urlopen(request, timeout=WoWConfig.HTTP_TIMEOUT) as response:
            return response.read()

    @staticmethod
    def _tooltip_url(kind, ident):
        if kind == "item":
            return WoWConfig.WOWHEAD_TOOLTIP_URL.format(id=ident)
        return WoWConfig.WOWHEAD_TOOLTIP_BASE.format(kind=kind, id=ident)

    @staticmethod
    def _page_url(kind, ident):
        if kind == "item":
            return WoWConfig.WOWHEAD_PAGE_URL.format(id=ident)
        return WoWConfig.WOWHEAD_PAGE_BASE.format(kind=kind, id=ident)

    def _fetch_icon_info(self, kind, ident):
        """(nom de l'icône, nom affichable ou '')"""
        # 1) infobulle JSON de Wowhead : {"name": ..., "icon": "inv_helm_..."}
        try:
            data = json.loads(self._http_get(self._tooltip_url(kind, ident)).decode("utf-8"))
            icon = str(data.get("icon", "")).strip().lower()
            if icon:
                return icon, str(data.get("name", "")).strip()
        except Exception:
            pass
        # 2) repli : page de l'objet / du sort
        html = self._http_get(self._page_url(kind, ident)).decode("utf-8", "ignore")
        match = re.search(r"/icons/(?:large|medium|small)/([a-z0-9_\-]+)\.(?:jpg|png)", html)
        if not match:
            raise ValueError("nom d'icône introuvable")
        return match.group(1).lower(), ""

    def _download(self, kind, ident):
        key = self._key(kind, ident)
        name, display = self._names.get(key), ""
        if not name:
            name, display = self._fetch_icon_info(kind, ident)
        path = os.path.join(self.cache_dir, name + ".jpg")
        if not os.path.isfile(path):
            data = self._http_get(WoWConfig.ICON_URL.format(name=name))
            if not data.startswith(b"\xff\xd8"):
                raise ValueError("image JPEG invalide")
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        self._names[key] = name
        self._save_json(self.names_file, self._names)
        if display:
            self._display[key] = display
            self._save_json(self.display_names_file, self._display)
