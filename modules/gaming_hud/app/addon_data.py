"""
Compatibilité avec les addons existants : on lit, sans jamais rien écrire, ce qu'ils enregistrent sur le disque.

- Tous les addons : liste de ce qui est installé (Interface/AddOns, fichier .toc) et de leurs données sauvegardées
  (WTF/Account/…/SavedVariables), consultables dans l'explorateur de l'onglet Hôtel des ventes.
- Lecteurs dédiés (prix de l'Hôtel des ventes) :
    * TradeSkillMaster : données de marché téléchargées par l'application TSM dans
      Interface/AddOns/TradeSkillMaster_AppHelper/AppData.lua (valeur du marché, prix minimum, ventes par jour…) ;
    * Auctionator : prix relevés par vos propres scans, avec leur historique (Auctionator.lua des SavedVariables).

Les formats viennent de la façon dont ces addons écrivent leurs fichiers ; ils ne sont pas documentés
officiellement. Les lecteurs sont donc tolérants : une entrée qu'ils ne comprennent pas est ignorée, jamais une
erreur bloquante.
"""
import glob
import os
import re
import time

from lua_parser import LuaParseError, parse_lua_file

MAX_SV_BYTES = 60 * 1024 * 1024  # au-delà, le fichier n'est pas chargé (l'explorateur le signale)


# ===========================================================================
#  Addons installés et données sauvegardées
# ===========================================================================
def _toc_fields(path):
    fields = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"##\s*([\w-]+)\s*:\s*(.*)", line.strip())
                if m:
                    fields[m.group(1).lower()] = m.group(2).strip()
    except OSError:
        pass
    return fields


def _plain_title(title):
    return re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", title)  # codes couleur du jeu dans les titres d'addons


def installed_addons(wow_path):
    """[{folder, title, version, saved: [noms des variables sauvegardées]}] des addons installés."""
    root = os.path.join(wow_path or "", "Interface", "AddOns")
    out = []
    if not os.path.isdir(root):
        return out
    for folder in sorted(os.listdir(root), key=str.lower):
        toc = next(iter(sorted(glob.glob(os.path.join(root, folder, "*.toc")))), None)
        if not toc:
            continue
        fields = _toc_fields(toc)
        saved = []
        for key in ("savedvariables", "savedvariablespercharacter"):
            saved += [s.strip() for s in fields.get(key, "").split(",") if s.strip()]
        out.append({"folder": folder, "title": _plain_title(fields.get("title", folder)),
                    "version": fields.get("version", ""), "saved": saved})
    return out


def saved_variable_files(wow_path):
    """Fichiers de données des addons : [{addon, scope ('compte' ou 'Royaume / Personnage'), path, size, updated}]."""
    account_root = os.path.join(wow_path or "", "WTF", "Account")
    out = []
    for path in glob.glob(os.path.join(account_root, "*", "SavedVariables", "*.lua")):
        out.append(("compte", path))
    for path in glob.glob(os.path.join(account_root, "*", "*", "*", "SavedVariables", "*.lua")):
        parts = path.replace("\\", "/").split("/")
        out.append((f"{parts[-4]} / {parts[-3]}", path))
    files = []
    for scope, path in out:
        name = os.path.splitext(os.path.basename(path))[0]
        if name.startswith("Blizzard_"):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        files.append({"addon": name, "scope": scope, "path": path, "size": stat.st_size, "updated": stat.st_mtime})
    return sorted(files, key=lambda f: (f["addon"].lower(), f["scope"]))


def load_saved_variables(path):
    """{variable: valeur} d'un fichier de données d'addon. Lève ValueError si le fichier est trop gros ou illisible."""
    size = os.path.getsize(path)
    if size > MAX_SV_BYTES:
        raise ValueError(f"fichier trop volumineux ({size // (1024 * 1024)} Mo) pour l'explorateur")
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    try:
        return parse_lua_file(text)
    except LuaParseError as e:
        raise ValueError(f"format non reconnu : {e}") from e


def tree_rows(value, depth=0, max_depth=3, limit=400, prefix=""):
    """Aperçu d'une valeur sous forme de lignes (profondeur, clé, résumé) pour l'explorateur ; `limit` lignes."""
    rows = []

    def summary(v):
        if isinstance(v, dict):
            return f"{{{len(v)} entrées}}"
        if isinstance(v, str):
            return repr(v if len(v) <= 80 else v[:77] + "…")
        return str(v)

    def walk(v, d, label):
        if len(rows) >= limit:
            return
        rows.append((d, label, summary(v)))
        if isinstance(v, dict) and d < max_depth:
            for key in list(v)[:60]:
                walk(v[key], d + 1, str(key))
            if len(v) > 60:
                rows.append((d + 1, "…", f"{len(v) - 60} autres entrées"))

    walk(value, depth, prefix or "(racine)")
    return rows


# ===========================================================================
#  Prix : TradeSkillMaster (AppHelper)
# ===========================================================================
_TSM_BLOCK = re.compile(r'LoadData\(\s*"([A-Z_]+)"\s*,\s*"([^"]*)"\s*,\s*\[\[(.*?)\]\]\s*\)', re.S)


def _item_id(key):
    """Identifiant d'objet d'une clé de prix : 12345, « 12345 », « i:12345 », « i:12345:… »."""
    if isinstance(key, int):
        return key
    m = re.match(r"^(?:i:)?(\d+)", str(key))
    return int(m.group(1)) if m else None


def tsm_prices(wow_path, realm=""):
    """{item_id: {champ: valeur}} lus dans les données téléchargées par l'application TSM (AppData.lua).
    Les champs dépendent du bloc : « marketValueRecent », « minBuyout », « numAuctions » pour le royaume,
    « regionMarketValue », « regionSoldPerDay »… pour la région. Le royaume du personnage passe en priorité."""
    path = os.path.join(wow_path or "", "Interface", "AddOns", "TradeSkillMaster_AppHelper", "AppData.lua")
    if not os.path.isfile(path):
        return {}, None
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    prices, newest = {}, 0
    blocks = []
    for tag, scope, body in _TSM_BLOCK.findall(text):
        if not tag.startswith("AUCTIONDB"):
            continue
        local = bool(realm) and realm.lower() in scope.lower()
        blocks.append((0 if not local else 1, tag, scope, body))  # le royaume du personnage s'applique en dernier
    for _local, _tag, _scope, body in sorted(blocks):
        try:
            data = parse_lua_file("x = " + body.strip()[len("return"):].strip())["x"]
        except (LuaParseError, KeyError):
            continue
        fields = data.get("fields") or {}
        names = [fields[k] for k in sorted(k for k in fields if isinstance(k, int))]
        newest = max(newest, int(data.get("downloadTime") or 0))
        rows = data.get("data") or {}
        for key in sorted(k for k in rows if isinstance(k, int)):
            row = rows[key]
            if not isinstance(row, dict):
                continue
            values = [row[k] for k in sorted(k for k in row if isinstance(k, int))]
            if not values or len(values) != len(names):
                continue
            item_id = _item_id(values[0])
            if item_id is None:
                continue
            entry = prices.setdefault(item_id, {})
            for name, value in zip(names[1:], values[1:]):
                if isinstance(value, (int, float)):
                    entry[name] = int(value)
    return prices, (newest or None)


# ===========================================================================
#  Prix : Auctionator
# ===========================================================================
def _auctionator_file(wow_path):
    files = glob.glob(os.path.join(wow_path or "", "WTF", "Account", "*", "SavedVariables", "Auctionator.lua"))
    return max(files, key=os.path.getmtime) if files else None


def auctionator_prices(wow_path, realm=""):
    """{item_id: {"price": dernier prix minimum relevé, "history": [(jour, prix)]}} des scans Auctionator.
    La base est rangée par royaume (et parfois faction) ; le royaume du personnage est préféré, sinon le premier."""
    path = _auctionator_file(wow_path)
    if not path:
        return {}, None
    try:
        db = load_saved_variables(path).get("AUCTIONATOR_PRICE_DATABASE")
    except (ValueError, OSError):
        return {}, None
    if not isinstance(db, dict):
        return {}, None
    realms = [k for k, v in db.items() if isinstance(v, dict) and not str(k).startswith("__")]
    if not realms:
        return {}, None
    chosen = next((k for k in realms if realm and str(k).lower().startswith(realm.lower())), realms[0])
    prices = {}
    for key, entry in db[chosen].items():
        item_id = _item_id(key)
        if item_id is None or not isinstance(entry, dict):
            continue
        price = entry.get("m")
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        history = entry.get("h") if isinstance(entry.get("h"), dict) else entry.get("l")
        points = sorted((int(d), int(p)) for d, p in (history or {}).items()
                        if isinstance(d, (int, float)) and isinstance(p, (int, float)))
        current = prices.get(item_id)
        if current is None or price < current["price"]:  # variantes d'un même objet : la moins chère
            prices[item_id] = {"price": int(price), "history": points}
    return prices, os.path.getmtime(path)


# ===========================================================================
#  Synthèse des sources
# ===========================================================================
class Market:
    """Prix d'un objet selon toutes les sources disponibles, et une estimation unique pour les totaux.

    Ordre de confiance pour l'estimation : Battle.net (instantané officiel de l'heure), TSM (valeur de marché
    calculée sur plusieurs jours), Auctionator (dernier prix vu par vos scans)."""

    def __init__(self, wow_path="", realm=""):
        self.wow_path, self.realm = wow_path, realm
        self.tsm, self.tsm_time = {}, None
        self.auctionator, self.auctionator_time = {}, None
        self.bnet, self.bnet_time = {}, None
        self.loaded_at = 0.0

    def reload(self):
        self.tsm, self.tsm_time = tsm_prices(self.wow_path, self.realm)
        self.auctionator, self.auctionator_time = auctionator_prices(self.wow_path, self.realm)
        self.loaded_at = time.time()
        return self

    def set_bnet(self, prices):
        self.bnet, self.bnet_time = dict(prices), time.time()

    def sources(self):
        """État de chaque source pour l'affichage : [(nom, nombre d'objets, date de la donnée ou None)]."""
        return [("Battle.net (HdV officiel)", len(self.bnet), self.bnet_time),
                ("TradeSkillMaster", len(self.tsm), self.tsm_time),
                ("Auctionator", len(self.auctionator), self.auctionator_time)]

    def details(self, item_id):
        out = {}
        if item_id in self.bnet:
            b = self.bnet[item_id]
            out["Battle.net"] = {"prix": b["market"], "minimum": b["min"], "en vente": b["quantity"]}
        if item_id in self.tsm:
            t = self.tsm[item_id]
            value = t.get("marketValueRecent") or t.get("regionMarketValue") or t.get("minBuyout")
            if value:
                out["TSM"] = {"prix": value, **{k: v for k, v in t.items() if k != "marketValueRecent"}}
        if item_id in self.auctionator:
            out["Auctionator"] = {"prix": self.auctionator[item_id]["price"]}
        return out

    def estimate(self, item_id):
        """(prix unitaire en cuivre, source) ou (None, None)."""
        for name, info in self.details(item_id).items():
            if info.get("prix"):
                return int(info["prix"]), name
        return None, None

    def history(self, item_id):
        return (self.auctionator.get(item_id) or {}).get("history", [])

    def value_of(self, items):
        """Valeur d'une liste d'objets [{id, quantity|count}] : (total, [(objet, prix unitaire, total, source)]),
        les objets sans prix connu à part (prix None)."""
        rows, total = [], 0
        for item in items:
            quantity = int(item.get("quantity", item.get("count", 1)) or 1)
            price, source = self.estimate(int(item["id"]))
            line_total = price * quantity if price else 0
            total += line_total
            rows.append((item, price, line_total, source))
        rows.sort(key=lambda r: -r[2])
        return total, rows
