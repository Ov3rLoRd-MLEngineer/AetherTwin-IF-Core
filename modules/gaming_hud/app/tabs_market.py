"""
Onglet « Hôtel des ventes et addons » : prix des objets (API Battle.net, TradeSkillMaster, Auctionator), valeur des
sacs et des banques, recherche d'un objet avec l'historique des prix, et explorateur des données de tous les addons
installés. Lecture seule : l'appli n'achète ni ne vend rien, et n'écrit jamais dans les fichiers du jeu.
"""
import threading
import time

import pygame

from addon_data import Market, installed_addons, load_saved_variables, saved_variable_files, tree_rows
from bnet import REGIONS, BnetError
from character import Character
from config import WoWConfig
from theme import C, QUALITY_COLORS
from tabutil import format_age, hover, message
from wowhead import item_url

VIEWS = (("value", "Valeur des sacs"), ("banks", "Valeur des banques"), ("search", "Rechercher un prix"),
         ("addons", "Données des addons"))


def _money(copper):
    return Character.format_money(int(copper)) if copper else "—"


# champs des sources de prix (TSM surtout) : libellé français, et s'il s'agit d'un prix ou d'un nombre
FIELDS = {"minimum": ("prix minimum", True), "en vente": ("quantité en vente", False),
          "minBuyout": ("achat immédiat minimum (royaume)", True), "numAuctions": ("enchères (royaume)", False),
          "marketValueRecent": ("valeur de marché récente (royaume)", True), "historical": ("historique (royaume)", True),
          "regionMarketValue": ("valeur de marché (région)", True), "regionHistorical": ("historique (région)", True),
          "regionSale": ("prix de vente moyen (région)", True), "regionSoldPerDay": ("ventes par jour (région)", False),
          "regionSalePercent": ("taux de vente (région)", False)}


def _field(key, value):
    label, is_price = FIELDS.get(key, (key, True))
    if is_price:
        return label, _money(value)
    # nombres affichés tels que la source les écrit (l'échelle de certains champs de TSM n'est pas documentée)
    return label, f"{value:,}".replace(",", " ")


# ===========================================================================
#  Chargement des prix (dans un fil : les fichiers d'addons peuvent peser plusieurs Mo)
# ===========================================================================
def _market(ui, realm):
    store = ui.state.setdefault("market_job", {"busy": False, "note": "", "ok": True})
    if ui.market is None or ui.market.realm != realm or ui.market.wow_path != WoWConfig.WOW_PATH:
        ui.market = Market(WoWConfig.WOW_PATH, realm)
        _reload(ui, with_bnet=False)
    return ui.market, store


def _reload(ui, with_bnet=True):
    store = ui.state.setdefault("market_job", {"busy": False, "note": "", "ok": True})
    if store["busy"]:
        return
    store.update(busy=True, note="Lecture des prix…", ok=True)
    market, media = ui.market, ui.media

    def work():
        notes = []
        try:
            market.reload()
            if with_bnet and media is not None and media.available():
                prices = dict(media.bnet.commodities())
                if market.realm:
                    prices.update(media.bnet.realm_auctions(market.realm))
                market.set_bnet(prices)
                notes.append(f"Battle.net : {len(prices)} objets en vente")
        except BnetError as e:
            notes.append(f"Battle.net : {e}")
            store["ok"] = False
        except Exception as e:   # fichier d'addon illisible : les autres sources restent utilisables
            notes.append(f"Erreur : {e}")
            store["ok"] = False
        store.update(busy=False, note="  ·  ".join(notes) or "Prix relus.")
    threading.Thread(target=work, daemon=True).start()


# ===========================================================================
#  Onglet
# ===========================================================================
def draw_market(ui, ctx, rect):
    x, y, w, h = rect
    character = getattr(ctx, "character", None)
    realm = getattr(character, "realm", "") or ""
    region = str(getattr(character, "region", "") or "").lower()
    if ui.settings is not None and not ui.settings.get("bnet.region") and region in REGIONS:
        ui.settings.set("bnet.region", region)  # région du compte lue par l'addon : rien à choisir
        ui.settings.save()
    market, job = _market(ui, realm)
    left = (x, y, 340, h)
    right = (x + 356, y, w - 356, h)
    view = ui.state.setdefault("market_view", "value")

    ui.frame(left, "Hôtel des ventes")
    py = y + 46
    for i, (key, label) in enumerate(VIEWS):
        ui.pill((x + 16, py + i * 34, 308, 28), label, view == key, lambda k=key: ui.state.update(market_view=k))
    py += len(VIEWS) * 34 + 14

    ui.text("Sources de prix", "small", "label", (x + 16, py))
    py += 24
    for name, count, when in market.sources():
        color = "green" if count else "gray"
        ui.text(ui.fit(name, "small", 190), "small", color, (x + 16, py))
        ui.text(f"{count} objets" if count else "aucune donnée", "tiny", "gray", (x + 324, py + 2), anchor="topright")
        if when:
            ui.text(f"données {format_age(when)}", "tiny", "gray", (x + 324, py + 18), anchor="topright")
        py += 36
    ui.pill((x + 16, py, 308, 28), "Relire les prix" + (" (en cours…)" if job["busy"] else ""), False,
            lambda: _reload(ui))
    py += 34
    if job["note"]:
        for line in ui.wrap(job["note"], "tiny", 308)[:3]:
            ui.text(line, "tiny", "green" if job["ok"] else "orange", (x + 16, py))
            py += 16
    _bnet_status(ui, (x + 16, py + 8, 308, y + h - py - 16))

    if view == "value":
        _draw_value(ui, right, market, getattr(ctx, "inventory", None) and ctx.inventory.items or [],
                    "Valeur des sacs", "Sacs vides, ou personnage pas encore lu.")
    elif view == "banks":
        data = getattr(ctx, "data", None)
        items = []
        for bank in (getattr(data, "characterBank", None), getattr(data, "warbandBank", None), getattr(data, "guildBank", None)):
            for tab in (bank or {}).get("tabs", []):
                items += tab.get("items", [])
        _draw_value(ui, right, market, items, "Valeur des banques (personnage, bataillon, guilde)",
                    "Banques jamais consultées : ouvrez-les une fois en jeu, puis /ha save.")
    elif view == "search":
        _draw_search(ui, right, market, ctx)
    else:
        _draw_addons(ui, right)


# ---------------------------------------------------------------------------
#  Réglages Battle.net (dans le panneau de gauche)
# ---------------------------------------------------------------------------
def _bnet_configured(ui):
    return bool(ui.settings and ui.settings.get("bnet.client_id") and ui.settings.get("bnet.client_secret"))


def _bnet_status(ui, rect):
    """État de l'API dans l'onglet ; les identifiants se règlent dans Paramètres généraux > Jeu."""
    x, y, w, h = rect
    if h < 80 or ui.settings is None:
        return
    pygame.draw.line(ui.screen, C["header_border"], (x, y), (x + w, y), 1)
    ui.text("API Battle.net (facultative)", "small", "gold", (x, y + 8))
    ok = _bnet_configured(ui)
    ui.text("Identifiants enregistrés" if ok else "Aucun identifiant", "tiny", "green" if ok else "gray", (x, y + 30))
    ui.pill((x, y + 50, w, 28), "Régler (Paramètres > Jeu)", False, lambda: ui.open_settings("game"))


def bnet_settings(ui, rect):
    """Identifiants Battle.net (Paramètres généraux > Jeu). Enregistrés dans settings.json sur ce PC."""
    x, y, w, h = rect
    if ui.settings is None:
        return
    if "bn_id" not in ui.inputs:
        ui.inputs["bn_id"] = str(ui.settings.get("bnet.client_id", "") or "")
        ui.inputs["bn_secret"] = str(ui.settings.get("bnet.client_secret", "") or "")
    region = str(ui.settings.get("bnet.region", "") or "eu")
    ui.text("API Battle.net (facultative)", "medium", "gold", (x, y), shadow=True)
    ok = _bnet_configured(ui)
    ui.text("Identifiants enregistrés" if ok else "Aucun identifiant enregistré", "small",
            "green" if ok else "gray", (x + w, y + 6), anchor="topright")
    y += 32
    ui.text("Images du personnage, des montures, des mascottes et des créatures ; prix de l'Hôtel des ventes.",
            "small", "gray", (x, y))
    y += 30
    ui.text("Client ID", "small", "label", (x, y + 6))
    ui.input_box((x + 150, y, w - 150, 30), "bn_id", "Client ID")
    y += 38
    ui.text("Client secret", "small", "label", (x, y + 6))
    ui.input_box((x + 150, y, w - 150 - 40, 30), "bn_secret", "Client secret", mask=True)
    ui.pill((x + w - 34, y, 34, 30), "×", False, lambda: _clear_bnet(ui))
    y += 40
    ui.text("Région", "small", "label", (x, y + 5))
    for i, code in enumerate(REGIONS):
        ui.pill((x + 150 + i * 56, y, 50, 28), code.upper(), region == code,
                lambda c=code: (ui.settings.set("bnet.region", c), ui.settings.save()))
    ui.pill((x + w - 170, y, 170, 28), "Enregistrer", True, lambda: _save_bnet(ui))
    y += 38
    link = pygame.Rect(x, y, 420, 18)
    ui.text("Créer des identifiants (gratuit) : develop.battle.net", "tiny",
            "light_gray" if not hover(link) else "gold", (x, y))
    ui.link(link, "https://develop.battle.net/access/clients")


def _save_bnet(ui):
    ui.settings.set("bnet.client_id", ui.inputs.get("bn_id", "").strip())
    ui.settings.set("bnet.client_secret", ui.inputs.get("bn_secret", "").strip())
    ui.settings.save()
    if ui.media is not None and ui.media.bnet is not None:
        ui.media.bnet._token = ""   # nouveaux identifiants : nouveau jeton
    ui.notify("Identifiants Battle.net enregistrés")
    _reload(ui)


def _clear_bnet(ui):
    ui.inputs["bn_secret"] = ""
    ui.settings.set("bnet.client_secret", "")
    ui.settings.save()
    ui.notify("Secret Battle.net effacé de settings.json")


# ---------------------------------------------------------------------------
#  Valeur d'une liste d'objets
# ---------------------------------------------------------------------------
def _item_tip(ui, market, item_id, name, quality):
    rows = [(name, quality, "")]
    for source, info in market.details(item_id).items():
        rows.append((f"{source} : {_money(info.get('prix'))}", C["gold"], ""))
        for key, value in info.items():
            if key == "prix":
                continue
            label, shown = _field(key, value)
            rows.append((f"   {label} : {shown}", C["light_gray"], ""))
    if len(rows) == 1:
        rows.append(("Aucun prix connu", C["gray"], ""))
    return {"rows": rows, "border": quality, "footer": "Clic : ouvrir sur Wowhead"}


def _draw_value(ui, rect, market, items, title, empty):
    x, y, w, h = rect
    ui.frame(rect, title)
    if not items:
        message(ui, rect, [empty])
        return
    total, rows = market.value_of(items)
    priced = sum(1 for _i, price, _t, _s in rows if price)
    ui.text(f"Valeur estimée : {_money(total)}", "large", "gold", (x + 16, y + 44), shadow=True)
    ui.text(f"{priced} objets sur {len(rows)} ont un prix connu", "small", "gray", (x + 16, y + 76))
    context = [f"{(i.get('name') or i['id'])} x{i.get('quantity', i.get('count', 1))} : "
               f"{_money(p)} l'unité ({s})" for i, p, _t, s in rows[:30] if p]
    ui.pill((x + w - 226, y + 44, 210, 32), "Conseil de vente (Hermes)", False,
            lambda: ui.ask_assistant(f"Hôtel des ventes : {title.lower()}",
                                     "Prix estimés (cuivre → or) des objets les plus précieux :\n" + "\n".join(context),
                                     suggestions=["Que devrais-je vendre en priorité, et à quel prix ?",
                                                  "Qu'est-ce que je devrais garder ?",
                                                  "Ces prix sont-ils intéressants pour revendre ?"]))
    area = pygame.Rect(x + 10, y + 104, w - 20, h - 116)
    top = ui.scroll_begin("market_" + title, area, len(rows) * 40)
    for n, (item, price, line_total, source) in enumerate(rows):
        ry = top + n * 40
        if ry + 40 < area.y or ry > area.bottom:
            continue
        row = pygame.Rect(area.x, ry, area.w - 12, 36)
        if hover(row):
            pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
        quality = QUALITY_COLORS.get(item.get("quality", 1), (255, 255, 255))
        name = item.get("name") or ui.icons.display_name(item["id"]) or f"Objet {item['id']}"
        quantity = item.get("quantity", item.get("count", 1))
        ui.icon("item", item["id"], (row.x + 2, row.y + 2, 32, 32), border=quality, fallback=name)
        ui.text(ui.fit(f"{name}  x{quantity}", "small", row.w - 420), "small", quality, (row.x + 44, row.y + 8))
        ui.text(_money(price) if price else "prix inconnu", "small", "light_gray" if price else "gray",
                (row.right - 230, row.y + 8), anchor="topright")
        ui.text(_money(line_total) if price else "", "small", "gold", (row.right - 70, row.y + 8), anchor="topright")
        ui.text(source or "", "tiny", "gray", (row.right - 6, row.y + 10), anchor="topright")
        ui.tip(row, lambda iid=item["id"], nm=name, q=quality: _item_tip(ui, market, iid, nm, q))
        ui.link(row, item_url(item["id"]))
    ui.scroll_end()


# ---------------------------------------------------------------------------
#  Recherche d'un objet et historique
# ---------------------------------------------------------------------------
def _known_items(ctx):
    """Objets connus de l'appli (sacs, banques, équipement) : {id: (nom, qualité)}."""
    known = {}
    pools = [getattr(getattr(ctx, "inventory", None), "items", []) or []]
    data = getattr(ctx, "data", None)
    for bank in (getattr(data, "characterBank", None), getattr(data, "warbandBank", None), getattr(data, "guildBank", None)):
        for tab in (bank or {}).get("tabs", []):
            pools.append(tab.get("items", []))
    equipment = getattr(getattr(ctx, "character", None), "equipment", {}) or {}
    pools.append([i for i in equipment.values() if i])
    for pool in pools:
        for item in pool:
            if item.get("id") and item.get("name"):
                known[int(item["id"])] = (item["name"], item.get("quality", 1))
    return known


def _draw_search(ui, rect, market, ctx):
    x, y, w, h = rect
    ui.frame(rect, "Rechercher un prix")
    query = ui.input_box((x + 16, y + 46, 360, 28), "market_search", "Nom ou numéro d'objet…").strip().lower()
    known = _known_items(ctx)
    if query.isdigit():
        matches = [(int(query), known.get(int(query), (f"Objet {query}", 1)))]
    elif len(query) >= 2:
        matches = sorted(((i, v) for i, v in known.items() if query in v[0].lower()), key=lambda kv: kv[1][0])[:12]
    else:
        matches = []
    ui.text("Objets de vos sacs, banques et équipement ; un numéro d'objet marche pour tout le reste.",
            "tiny", "gray", (x + 392, y + 54))
    if not matches:
        message(ui, (x, y + 60, w, h - 60), ["Tapez au moins deux lettres du nom d'un objet,",
                                             "ou son numéro (visible sur Wowhead)."])
        return
    selected = ui.state.get("market_item")
    if selected not in [m[0] for m in matches]:
        selected = matches[0][0]
    py = y + 90
    for item_id, (name, quality) in matches:
        cell = pygame.Rect(x + 16, py, 300, 30)
        active = item_id == selected
        ui.pill(cell, ui.fit(name, "small", 280), active, lambda i=item_id: ui.state.update(market_item=i))
        py += 34
    name, quality = dict(matches)[selected]
    dx, dy, dw = x + 336, y + 90, w - 352
    color = QUALITY_COLORS.get(quality, (255, 255, 255))
    ui.icon("item", selected, (dx, dy, 44, 44), border=color, fallback=name)
    ui.text(ui.fit(name, "large", dw - 60), "large", color, (dx + 56, dy + 8), shadow=True)
    ui.link(pygame.Rect(dx, dy, dw, 44), item_url(selected))
    dy += 60
    details = market.details(selected)
    if not details:
        ui.text("Aucun prix connu pour cet objet dans les sources disponibles.", "small", "gray", (dx, dy))
    for source, info in details.items():
        ui.text(f"{source} : {_money(info.get('prix'))}", "medium", "gold", (dx, dy))
        dy += 26
        for key, value in list(info.items())[1:6]:
            label, shown = _field(key, value)
            ui.text(f"{label} : {shown}", "small", "light_gray", (dx + 16, dy))
            dy += 22
        dy += 8
    _history_chart(ui, (dx, dy + 6, dw, min(220, y + h - dy - 70)), market.history(selected))
    ui.detail_buttons(dx, y + h - 48, item_url(selected), f"Prix : {name}",
                      "\n".join([f"Objet : {name} (n° {selected})"]
                                + [f"{s} : {_money(i.get('prix'))}" for s, i in details.items()]))


def _history_chart(ui, rect, points):
    """Courbe du prix relevé par Auctionator, jour par jour."""
    x, y, w, h = rect
    if h < 80:
        return
    pygame.draw.rect(ui.screen, (10, 10, 14), rect, border_radius=4)
    pygame.draw.rect(ui.screen, C["frame_lo"], rect, 1, border_radius=4)
    if len(points) < 2:
        ui.text("Historique : scannez l'HdV avec Auctionator plusieurs jours de suite", "small", "gray",
                (x + w // 2, y + h // 2), anchor="center")
        return
    points = points[-60:]
    days = [d for d, _p in points]
    prices = [p for _d, p in points]
    low, high = min(prices), max(prices)
    span_d, span_p = max(1, days[-1] - days[0]), max(1, high - low)
    coords = [(x + 10 + (d - days[0]) * (w - 20) / span_d, y + h - 24 - (p - low) * (h - 44) / span_p)
              for d, p in points]
    pygame.draw.lines(ui.screen, C["gold"], False, coords, 2)
    ui.text(f"Historique Auctionator ({len(points)} relevés)", "tiny", "gray", (x + 8, y + 4))
    ui.text(f"max {_money(high)}", "tiny", "light_gray", (x + w - 8, y + 4), anchor="topright")
    ui.text(f"min {_money(low)}", "tiny", "light_gray", (x + w - 8, y + h - 18), anchor="topright")


# ---------------------------------------------------------------------------
#  Explorateur des données d'addons
# ---------------------------------------------------------------------------
def _addons_state(ui):
    state = ui.state.setdefault("addons", {"at": 0.0, "addons": [], "files": [], "open": None, "rows": [],
                                           "error": "", "busy": False})
    if time.time() - state["at"] > 30:
        state.update(at=time.time(), addons=installed_addons(WoWConfig.WOW_PATH),
                     files=saved_variable_files(WoWConfig.WOW_PATH))
    return state


def _open_file(ui, state, entry):
    state.update(open=entry["path"], rows=[], error="", busy=True)

    def work():
        try:
            data = load_saved_variables(entry["path"])
            rows = []
            for name, value in data.items():
                rows += tree_rows(value, prefix=name, limit=600 - len(rows))
            state.update(rows=rows, busy=False)
        except (ValueError, OSError) as e:
            state.update(error=str(e), busy=False)
    threading.Thread(target=work, daemon=True).start()


def _draw_addons(ui, rect):
    x, y, w, h = rect
    ui.frame(rect, "Données des addons")
    state = _addons_state(ui)
    col = (x + 16, y + 46, 330, h - 62)
    ui.text(f"{len(state['addons'])} addons installés · {len(state['files'])} fichiers de données", "small",
            "light_gray", (col[0], col[1]))
    area = pygame.Rect(col[0], col[1] + 28, col[2], col[3] - 28)
    top = ui.scroll_begin("addon_files", area, len(state["files"]) * 46 + 10)
    for n, entry in enumerate(state["files"]):
        cell = pygame.Rect(area.x, top + n * 46, area.w - 12, 42)
        if cell.bottom < area.y or cell.y > area.bottom:
            continue
        active = entry["path"] == state["open"]
        if active or hover(cell):
            pygame.draw.rect(ui.screen, (44, 40, 30) if active else C["row_hover"], cell, border_radius=4)
        ui.text(ui.fit(entry["addon"], "small", cell.w - 90), "small", "gold" if active else "text", (cell.x + 6, cell.y + 4))
        ui.text(f"{entry['size'] // 1024} Ko", "tiny", "gray", (cell.right - 6, cell.y + 6), anchor="topright")
        ui.text(ui.fit(entry["scope"], "tiny", cell.w - 12), "tiny", "gray", (cell.x + 6, cell.y + 24))
        ui.click(cell, lambda e=entry: _open_file(ui, state, e))
    ui.scroll_end()
    if not state["files"]:
        message(ui, (col[0], col[1] + 30, col[2], 120), ["Aucune donnée d'addon trouvée", "(dossier WTF/Account)."])

    tx, tw = x + 362, w - 378
    if state["busy"]:
        ui.text("Lecture…", "small", "gray", (tx, y + 46))
        return
    if state["error"]:
        ui.text(state["error"], "small", "orange", (tx, y + 46))
        return
    if not state["rows"]:
        lines = ["Choisissez un fichier à gauche pour voir ce que l'addon enregistre.",
                 "Lecture seule : rien n'est jamais modifié."]
        names = [a["title"] for a in state["addons"]]
        if names:
            lines += ["", "Addons installés :"] + [", ".join(names[i:i + 4]) for i in range(0, min(len(names), 24), 4)]
        for i, line in enumerate(lines):
            ui.text(ui.fit(line, "small", tw), "small", "gray" if i < 2 else "light_gray", (tx, y + 46 + i * 22))
        return
    opened = next((f for f in state["files"] if f["path"] == state["open"]), None)
    summary = "\n".join(f"{'  ' * d}{k} = {v}" for d, k, v in state["rows"][:120])
    ui.pill((x + w - 226, y + 40, 210, 30), "Expliquer (Hermes)", False,
            lambda: ui.ask_assistant(f"Données de l'addon {opened['addon'] if opened else ''}",
                                     "Aperçu des données sauvegardées par l'addon (World of Warcraft) :\n" + summary,
                                     suggestions=["À quoi servent ces données ?", "Qu'est-ce que je peux en tirer ?"]))
    area = pygame.Rect(tx, y + 80, tw, h - 92)
    top = ui.scroll_begin("addon_tree", area, len(state["rows"]) * 20 + 10)
    for n, (depth, key, value) in enumerate(state["rows"]):
        ry = top + n * 20
        if ry + 20 < area.y or ry > area.bottom:
            continue
        indent = tx + depth * 18
        ui.text(ui.fit(str(key), "small", 240), "small", "gold" if depth == 0 else "text", (indent, ry))
        ui.text(ui.fit(value, "small", max(40, tx + tw - indent - 262)), "small", "light_gray", (indent + 250, ry))
    ui.scroll_end()
