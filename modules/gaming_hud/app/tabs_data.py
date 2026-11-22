"""
Onglets de données : Hauts Faits (exploration complète), Réputations et monnaies,
Instances et Chambre forte, Historique d'activité (évolution, journal, statistiques).
"""
import time

import pygame

from character import format_duration
from tabutil import format_age, format_remaining, hover, message
from theme import C, EVENT_COLORS
from wowhead import achievement_url, currency_url

_LEGACY_NAMES = ("prouesse", "feats of strength", "héritage", "heritage", "legacy")
_LEGACY_IDS = (81, 15234)


# ===========================================================================
#  Hauts Faits
# ===========================================================================
def _parse_date(text):
    try:
        day, month, year = text.split("/")
        return int(year) * 10000 + int(month) * 100 + int(day)
    except (ValueError, AttributeError):
        return 0


def _achv_index(ui, achv):
    """Index des hauts faits (arbre de catégories, comptes, racines 'prouesses/héritage'), mis en cache."""
    key = (achv.get("updated"), len(achv["cats"]), len(achv["list"]))
    cached = ui._cache.get("achv")
    if cached and cached[0] == key:
        return cached[1]
    cats = {c["id"]: c for c in achv["cats"]}
    children = {}
    for c in achv["cats"]:
        children.setdefault(c["parent"], []).append(c["id"])

    def root_of(cid):
        seen = 0
        while cats.get(cid) and cats[cid]["parent"] in cats and seen < 10:
            cid, seen = cats[cid]["parent"], seen + 1
        return cid

    legacy_roots = {cid for cid, c in cats.items()
                    if c["parent"] not in cats and (cid in _LEGACY_IDS or any(n in c["name"].lower() for n in _LEGACY_NAMES))}

    by_cat = {cid: achv["list"].get(str(cid), []) for cid in cats}
    legacy = {cid: root_of(cid) in legacy_roots for cid in cats}

    def descendants(cid):
        out = [cid]
        for child in children.get(cid, []):
            out += descendants(child)
        return out

    counts = {}
    for cid in cats:
        items = [i for d in descendants(cid) for i in by_cat.get(d, [])]
        counts[cid] = (sum(1 for i in items if i["done"]), len(items))
    everything = [(i, cid) for cid in cats for i in by_cat[cid]]
    recent = sorted((p for p in everything if p[0]["done"] and p[0]["date"]), key=lambda p: -_parse_date(p[0]["date"]))[:60]
    index = {"cats": cats, "children": children, "by_cat": by_cat, "legacy": legacy, "counts": counts,
             "all": everything, "recent": recent, "descendants": descendants,
             "roots": [c["id"] for c in achv["cats"] if c["parent"] not in cats]}
    ui._cache["achv"] = (key, index)
    return index


def draw_achievements(ui, ctx, rect):
    x, y, w, h = rect
    ach, full = ctx.data.achievements, ctx.data.achv

    ui.frame((x, y, w, 92))
    ui.text(f"{ach['points']:,}".replace(",", " "), "huge", "gold", (x + 24, y + 12), shadow=True)
    ui.text("points de haut fait", "small", "label", (x + 24, y + 54))
    pct = 100 * ach["completed"] / ach["total"] if ach["total"] else 0
    ui.text(f"{ach['completed']:,} / {ach['total']:,} obtenus  ({pct:.0f} %)".replace(",", " "), "medium", "text", (x + 330, y + 14))
    ui.bar((x + 330, y + 46, w - 380, 18), pct, C["orange"], (50, 34, 14))
    age = ctx.data.scan_age("achievements")
    ui.text("Analyse complète : " + (format_age(full["updated"]) if full["updated"] else "jamais — tapez /ha scan en jeu"),
            "small", "gray" if full["updated"] else "orange", (x + w - 24, y + 14), anchor="topright")
    ui.text("(le jeu ne signale pas les hauts faits « expirés » : ils sont regroupés sous Prouesses / Héritage)",
            "tiny", "gray", (x + w - 24, y + 72), anchor="topright")

    body = (x, y + 104, w, h - 104)
    if not full["cats"]:
        ui.frame(body, "Exploration")
        message(ui, body, ["Liste complète des hauts faits non exportée", "Tapez /ha scan en jeu (quelques secondes, sans à-coup),",
                           "puis /ha save pour l'envoyer à l'application."])
        return
    index = _achv_index(ui, full)
    left = (body[0], body[1], 430, body[3])
    right = (body[0] + 446, body[1], body[2] - 446, body[3])

    # ---------------- arbre des catégories
    ui.frame(left, "Catégories")
    sel = ui.state["ach_cat"]
    opened = ui.state["ach_open"]
    rows = [("all", None, 0), ("recent", "recent", 0)]
    for root in index["roots"]:
        rows.append(("cat", root, 0))
        if root in opened:
            rows += [("cat", child, 1) for child in index["children"].get(root, [])]
    area = pygame.Rect(left[0] + 10, left[1] + 46, left[2] - 20, left[3] - 58)
    top = ui.scroll_begin("ach_tree", area, len(rows) * 32)
    for i, (kind, cid, depth) in enumerate(rows):
        ry = top + i * 32
        if ry + 32 < area.y or ry > area.bottom:
            continue
        row = pygame.Rect(area.x + 2, ry, area.w - 20, 30)
        active = (kind == "all" and sel is None) or (kind == "recent" and sel == "recent") or (kind == "cat" and sel == cid)
        if active:
            pygame.draw.rect(ui.screen, (44, 40, 30), row, border_radius=4)
            pygame.draw.rect(ui.screen, C["gold"], row, 1, border_radius=4)
        elif hover(row):
            pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
        if kind == "all":
            ui.text("Tous les hauts faits", "small", "gold", (row.x + 10, ry + 7))
            ui.click(row, lambda: ui.state.update(ach_cat=None))
        elif kind == "recent":
            ui.text("Derniers obtenus", "small", "gold", (row.x + 10, ry + 7))
            ui.click(row, lambda: ui.state.update(ach_cat="recent"))
        else:
            cat = index["cats"][cid]
            has_children = bool(index["children"].get(cid)) and depth == 0
            arrow = ("▾ " if cid in opened else "▸ ") if has_children else "   "
            legacy = index["legacy"].get(cid)
            ui.text(ui.fit(arrow + cat["name"], "small", row.w - 100), "small", "gray" if legacy else "text",
                    (row.x + 10 + depth * 22, ry + 7))
            done, total = index["counts"][cid]
            ui.text(f"{done}/{total}", "small", "light_gray", (row.right - 8, ry + 7), anchor="topright")

            def pick(c=cid, expand=has_children):
                ui.state["ach_cat"] = c
                if expand:
                    (opened.remove if c in opened else opened.append)(c)
            ui.click(row, pick)
    ui.scroll_end()

    # ---------------- liste des hauts faits
    sel_name = ("Tous les hauts faits" if sel is None else "Derniers obtenus" if sel == "recent" else index["cats"][sel]["name"])
    ui.frame(right, sel_name)
    px = right[0] + 16
    for key, label in (("all", "Tous"), ("done", "Obtenus"), ("todo", "À obtenir"), ("legacy", "Prouesses / non obtenables")):
        pw = ui.fonts["small"].size(label)[0] + 28
        ui.pill((px, right[1] + 44, pw, 28), label, ui.state["ach_filter"] == key, lambda k=key: ui.state.update(ach_filter=k))
        px += pw + 6
    query = ui.input_box((right[0] + 16, right[1] + 80, 380, 28), "ach_search", "Rechercher un haut fait…")

    if sel is None:
        pool = index["all"]
    elif sel == "recent":
        pool = index["recent"]
    else:
        pool = [(i, d) for d in index["descendants"](sel) for i in index["by_cat"].get(d, [])]
    flt = ui.state["ach_filter"]
    items = []
    for item, cid in pool:
        legacy = index["legacy"].get(cid, False)
        if flt == "done" and not item["done"]:
            continue
        if flt == "todo" and (item["done"] or legacy):
            continue
        if flt == "legacy" and not legacy:
            continue
        if query and query not in item["name"].lower() and query not in item["desc"].lower():
            continue
        items.append((item, legacy))
    ui.text(f"{len(items)} résultat(s)", "small", "gray", (right[0] + right[2] - 20, right[1] + 86), anchor="topright")

    area = pygame.Rect(right[0] + 10, right[1] + 120, right[2] - 20, right[3] - 132)
    if not items:
        message(ui, area, ["Aucun haut fait ne correspond"])
        return
    top = ui.scroll_begin("ach_list", area, len(items) * 74)
    for i, (item, legacy) in enumerate(items):
        ry = top + i * 74
        if ry + 74 < area.y or ry > area.bottom:
            continue
        row = pygame.Rect(area.x + 2, ry, area.w - 22, 68)
        pygame.draw.rect(ui.screen, C["panel_alt"], row, border_radius=5)
        if hover(row):
            pygame.draw.rect(ui.screen, C["gold"], row, 1, border_radius=5)
        ui.icon("achievement", item["id"], (row.x + 8, row.y + 8, 52, 52),
                border=C["gold"] if item["done"] else C["frame"], fallback=item["name"])
        ui.text(ui.fit(item["name"], "medium", row.w - 330), "medium", "gold" if item["done"] else "light_gray", (row.x + 72, row.y + 6))
        for n, line in enumerate(ui.wrap(item["desc"], "small", row.w - 330)[:2]):
            ui.text(line, "small", "light_gray" if item["done"] else "gray", (row.x + 72, row.y + 30 + n * 18))
        ui.text(f"{item['points']} pts", "small", "orange", (row.right - 12, row.y + 8), anchor="topright")
        if item["done"]:
            ui.text("Obtenu" + (f" le {item['date']}" if item["date"] else ""), "small", "green", (row.right - 12, row.y + 38), anchor="topright")
        elif legacy:
            ui.text("Non obtenable", "small", "gray", (row.right - 12, row.y + 38), anchor="topright")
        else:
            ui.text("À obtenir", "small", "orange", (row.right - 12, row.y + 38), anchor="topright")
        ui.link(row, achievement_url(item["id"]))
        ui.tip(row, {"rows": [(item["name"], C["gold"], f"{item['points']} pts"), (item["desc"], C["light_gray"], "")],
                     "footer": "Clic : ouvrir sur Wowhead"})
    ui.scroll_end()


# ===========================================================================
#  Réputations et monnaies
# ===========================================================================
_REACTION_COLORS = {1: (200, 60, 60), 2: (210, 90, 60), 3: (220, 140, 50), 4: (230, 200, 60), 5: (120, 200, 80),
                    6: (70, 200, 120), 7: (60, 190, 170), 8: (60, 170, 220)}


def _grouped(entries, query):
    rows, last = [], None
    for entry in entries:
        if query and query not in entry["name"].lower():
            continue
        if entry.get("group") != last:
            rows.append(("group", entry.get("group") or "Autres"))
            last = entry.get("group")
        rows.append(("item", entry))
    return rows


def draw_reputations(ui, ctx, rect):
    x, y, w, h = rect
    data = ctx.data
    left = (x, y, 800, h)
    right = (x + 816, y, w - 816, h)

    ui.frame(left, f"Réputations ({len(data.factions)})")
    query = ui.input_box((left[0] + 16, left[1] + 44, 340, 28), "rep_search", "Rechercher une faction…")
    area = pygame.Rect(left[0] + 10, left[1] + 82, left[2] - 20, left[3] - 94)
    rows = _grouped(data.factions, query)
    if not rows:
        message(ui, area, ["Aucune réputation exportée", "(les groupes repliés dans le jeu ne sont pas lus : tapez /ha save)"])
    else:
        top = ui.scroll_begin("reps", area, sum(34 if r[0] == "group" else 52 for r in rows))
        ry = top
        for kind, entry in rows:
            rh = 34 if kind == "group" else 52
            if ry + rh >= area.y and ry <= area.bottom:
                if kind == "group":
                    ui.text(entry, "medium", "gold", (area.x + 8, ry + 8), shadow=True)
                    pygame.draw.line(ui.screen, C["header_border"], (area.x + 6, ry + rh - 3), (area.right - 20, ry + rh - 3), 1)
                else:
                    color = (90, 160, 255) if entry["kind"] == "renown" else (230, 160, 230) if entry["kind"] == "friend" \
                        else _REACTION_COLORS.get(entry.get("reaction", 4), (150, 150, 150))
                    ui.text(ui.fit(entry["name"], "small", 380), "small", "text", (area.x + 12, ry + 4))
                    ui.text(entry.get("label", ""), "small", color, (area.right - 28, ry + 4), anchor="topright")
                    need = max(1, entry.get("max", 1))
                    ui.bar((area.x + 12, ry + 28, area.w - 190, 12), 100 * min(entry.get("cur", 0), need) / need, color, (32, 32, 38))
                    ui.text(f"{entry.get('cur', 0):,} / {need:,}".replace(",", " "), "tiny", "light_gray",
                            (area.right - 28, ry + 26), anchor="topright")
            ry += rh
        ui.scroll_end()

    ui.frame(right, f"Monnaies ({len(data.currencies)})")
    cquery = ui.input_box((right[0] + 16, right[1] + 44, 320, 28), "cur_search", "Rechercher une monnaie…")
    area = pygame.Rect(right[0] + 10, right[1] + 82, right[2] - 20, right[3] - 94)
    rows = _grouped(data.currencies, cquery)
    if not rows:
        message(ui, area, ["Aucune monnaie exportée", "(tapez /ha save en jeu)"])
        return
    top = ui.scroll_begin("currencies", area, sum(34 if r[0] == "group" else 48 for r in rows))
    ry = top
    for kind, entry in rows:
        rh = 34 if kind == "group" else 48
        if ry + rh >= area.y and ry <= area.bottom:
            if kind == "group":
                ui.text(entry, "medium", "gold", (area.x + 8, ry + 8), shadow=True)
                pygame.draw.line(ui.screen, C["header_border"], (area.x + 6, ry + rh - 3), (area.right - 20, ry + rh - 3), 1)
            else:
                row = pygame.Rect(area.x + 4, ry, area.w - 24, rh - 4)
                if hover(row):
                    pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
                ui.text(ui.fit(entry["name"], "small", row.w - 170), "small", "text", (row.x + 8, ry + 4))
                maxq = entry.get("max", 0)
                ui.text(f"{entry['quantity']:,}".replace(",", " ") + (f" / {maxq:,}".replace(",", " ") if maxq else ""),
                        "small", "gold", (row.right - 8, ry + 4), anchor="topright")
                if entry.get("weeklyMax"):
                    ui.text(f"cette semaine : {entry.get('weekly', 0)}/{entry['weeklyMax']}", "tiny", "gray", (row.x + 8, ry + 26))
                ui.link(row, currency_url(entry.get("id")))
        ry += rh
    ui.scroll_end()


# ===========================================================================
#  Instances et Chambre forte
# ===========================================================================
_VAULT_TYPES = {3: "Raid", 1: "Donjons (Mythique+)", 6: "Monde", 2: "JcJ classé"}
_RAID_LEVELS = {14: "Normal", 15: "Héroïque", 16: "Mythique", 17: "Recherche de raid"}


def _vault_level_text(kind, level):
    if not level:
        return ""
    if kind == 3:
        return _RAID_LEVELS.get(level, f"Difficulté {level}")
    if kind == 1:
        return f"Clé +{level}"
    return f"Palier {level}"


def _draw_mythic_plus(ui, rect, mp):
    """Cote Mythique+, clé en poche, meilleur niveau par donjon (vert : dans les temps), clés de la semaine."""
    x, y, w, h = rect
    ui.frame(rect, "Mythique+")
    if not mp["dungeons"] and not mp["score"]:
        message(ui, rect, ["Pas encore de données Mythique+",
                           "(addon HermesAssistant 1.7 : copiez-le dans le jeu, puis /reload)"])
        return
    ui.text(f"Cote : {mp['score']}", "large", "gold", (x + 16, y + 44), shadow=True)
    key = mp["keystone"]
    ui.text(ui.fit(f"Clé en poche : {key['name']} +{key['level']}" if key else "Pas de clé en poche", "medium",
                   w - 280), "medium", "text" if key else "gray", (x + 240, y + 50))
    week = mp["week"]
    if week:
        best = max(r["level"] for r in week)
        done = sum(1 for r in week if r["completed"])
        ui.text(f"Cette semaine : {len(week)} clés, {done} terminées, meilleure +{best}", "small", "light_gray",
                (x + 240, y + 76))
    dungeons = sorted(mp["dungeons"], key=lambda d: (-d["level"], d["name"]))
    col_w = (w - 40) // 2
    for n, d in enumerate(dungeons[:8]):
        cx = x + 16 + (n % 2) * (col_w + 8)
        cy = y + 104 + (n // 2) * 26
        color = "gray" if not d["level"] else ("green" if d["inTime"] else "orange")
        ui.text(ui.fit(d["name"], "small", col_w - 120), "small", "text", (cx, cy))
        ui.text(f"+{d['level']}" if d["level"] else "—", "small", color, (cx + col_w - 70, cy), anchor="topright")
        ui.text(str(d["score"]) if d["score"] else "", "small", "light_gray", (cx + col_w - 8, cy), anchor="topright")
    context = "\n".join([f"Cote Mythique+ : {mp['score']}",
                         f"Clé : {key['name']} +{key['level']}" if key else "Pas de clé"]
                        + [f"{d['name']} : +{d['level']} ({'dans les temps' if d['inTime'] else 'hors temps'}), "
                           f"score {d['score']}" for d in dungeons])
    ui.pill((x + w - 226, y + h - 44, 210, 30), "Conseils M+ (Hermes)", False,
            lambda: ui.ask_assistant("Mythique+", context,
                                     suggestions=["Quel donjon pousser pour monter ma cote ?",
                                                  "Que faire de ma clé cette semaine ?"]))


def draw_instances(ui, ctx, rect):
    x, y, w, h = rect
    data = ctx.data
    mythic_h = 250
    left = (x, y, 800, h - mythic_h - 12)
    right = (x + 816, y, w - 816, h)
    _draw_mythic_plus(ui, (x, y + h - mythic_h, 800, mythic_h), data.mythicPlus)

    # ---------------- verrouillages
    instances, bosses = data.lockouts["instances"], data.lockouts["worldBosses"]
    ui.frame(left, f"Verrouillages ({len(instances) + len(bosses)})")
    area = pygame.Rect(left[0] + 10, left[1] + 46, left[2] - 20, left[3] - 58)
    if not instances and not bosses:
        message(ui, area, ["Aucun verrouillage actif", "(ou données pas encore reçues : /ha save en jeu)"])
    else:
        heights = [90 + ((len(i["bosses"]) + 1) // 2) * 22 for i in instances] + [44] * len(bosses)
        top = ui.scroll_begin("lockouts", area, sum(heights) + 8)
        ry = top
        now = time.time()
        for inst in instances:
            rh = 90 + ((len(inst["bosses"]) + 1) // 2) * 22
            if ry + rh >= area.y and ry <= area.bottom:
                card = pygame.Rect(area.x + 4, ry, area.w - 26, rh - 8)
                pygame.draw.rect(ui.screen, C["panel_alt"], card, border_radius=6)
                pygame.draw.rect(ui.screen, C["frame"], card, 1, border_radius=6)
                ui.text(ui.fit(inst["name"], "medium", card.w - 280), "medium", "gold", (card.x + 14, card.y + 8), shadow=True)
                ui.text(inst.get("difficulty", ""), "small", "label", (card.x + 14, card.y + 34))
                remaining = inst["expires"] - now
                ui.text(format_remaining(remaining), "small", "green" if remaining > 0 else "gray",
                        (card.right - 14, card.y + 10), anchor="topright")
                total = max(1, inst.get("total", len(inst["bosses"])))
                ui.bar((card.x + 14, card.y + 56, card.w - 120, 10), 100 * inst.get("progress", 0) / total, C["red"], (40, 30, 30))
                ui.text(f"{inst.get('progress', 0)}/{total}", "small", "light_gray", (card.right - 14, card.y + 50), anchor="topright")
                for n, boss in enumerate(inst["bosses"]):
                    bx = card.x + 14 + (n % 2) * (card.w // 2)
                    by = card.y + 74 + (n // 2) * 22
                    pygame.draw.circle(ui.screen, C["red"] if boss["killed"] else (60, 60, 66), (bx + 6, by + 9), 6)
                    ui.text(ui.fit(boss["name"], "small", card.w // 2 - 40), "small",
                            "gray" if boss["killed"] else "text", (bx + 20, by))
            ry += rh
        for boss in bosses:
            if ry + 44 >= area.y and ry <= area.bottom:
                card = pygame.Rect(area.x + 4, ry, area.w - 26, 38)
                pygame.draw.rect(ui.screen, C["panel_alt"], card, border_radius=6)
                ui.text(f"Boss mondial : {boss['name']}", "small", "text", (card.x + 14, card.y + 10))
                ui.text(format_remaining(boss["expires"] - now), "small", "green", (card.right - 14, card.y + 10), anchor="topright")
            ry += 44
        ui.scroll_end()

    # ---------------- Grande Chambre forte
    vault = data.vault
    ui.frame(right, "Grande Chambre forte")
    if not vault["activities"]:
        message(ui, right, ["Chambre forte non exportée", "(disponible à partir du niveau maximum)"])
        return
    if vault["hasRewards"]:
        ui.text("Récompenses à récupérer !", "medium", "green", (right[0] + right[2] // 2, right[1] + 44), anchor="midtop", shadow=True)
    elif vault["canClaim"]:
        ui.text("Vous pouvez choisir une récompense", "small", "green", (right[0] + right[2] // 2, right[1] + 46), anchor="midtop")
    ry = right[1] + 84
    by_type = {}
    for act in vault["activities"]:
        by_type.setdefault(act["type"], []).append(act)
    for kind in [k for k in _VAULT_TYPES if k in by_type] + [k for k in by_type if k not in _VAULT_TYPES]:
        ui.text(_VAULT_TYPES.get(kind, f"Activité {kind}"), "medium", "gold", (right[0] + 20, ry), shadow=True)
        ry += 34
        acts = sorted(by_type[kind], key=lambda a: a["index"])
        box_w = (right[2] - 40 - 2 * 10) // 3
        for n, act in enumerate(acts[:3]):
            box = pygame.Rect(right[0] + 20 + n * (box_w + 10), ry, box_w, 96)
            unlocked = act["progress"] >= act["threshold"] > 0
            pygame.draw.rect(ui.screen, (24, 36, 26) if unlocked else C["panel_alt"], box, border_radius=6)
            pygame.draw.rect(ui.screen, C["green"] if unlocked else C["frame"], box, 2 if unlocked else 1, border_radius=6)
            ui.text(f"Emplacement {act['index']}", "small", "label", (box.x + 12, box.y + 8))
            if unlocked:
                ui.text("Débloqué", "small", "green", (box.x + 12, box.y + 32))
                ui.text(_vault_level_text(kind, act["level"]), "small", "text", (box.x + 12, box.y + 54))
            else:
                ui.text(f"{act['progress']} / {act['threshold']}", "medium", "light_gray", (box.x + 12, box.y + 30))
                ui.bar((box.x + 12, box.y + 70, box.w - 24, 10), 100 * act["progress"] / max(1, act["threshold"]), C["orange"], (50, 34, 14))
        ry += 112


# ===========================================================================
#  Historique d'activité
# ===========================================================================
_RANGES = [("24h", "24 heures", 86400), ("7d", "7 jours", 7 * 86400), ("30d", "30 jours", 30 * 86400), ("all", "Tout", None)]
_KIND_LABELS = {"level": "Niveaux", "zone": "Zones", "gold": "Or", "gear": "Équipement", "quest": "Quêtes",
                "achievement": "Hauts faits", "collection": "Collections", "spec": "Spécialisation", "death": "Morts"}


def draw_activity(ui, ctx, rect):
    x, y, w, h = rect
    px = x
    for key, label in (("evolution", "Évolution"), ("journal", "Journal"), ("stats", "Statistiques")):
        ui.pill((px, y, 150, 30), label, ui.state["activity_view"] == key, lambda k=key: ui.state.update(activity_view=k))
        px += 158
    view = ui.state["activity_view"]
    if view != "stats":
        rx = x + w
        for key, label, _ in reversed(_RANGES):
            rx -= 124
            ui.pill((rx, y, 118, 30), label, ui.state["range"] == key, lambda k=key: ui.state.update(range=k))
    body = (x, y + 42, w, h - 42)
    if view == "evolution":
        _draw_evolution(ui, ctx, body)
    elif view == "journal":
        _draw_journal(ui, ctx, body)
    else:
        _draw_statistics(ui, ctx, body)


def _span(ui):
    return next(r[2] for r in _RANGES if r[0] == ui.state["range"])


def _draw_evolution(ui, ctx, rect):
    x, y, w, h = rect
    c = ctx.character
    entries = ctx.history.get_recent(c.key, 5000)
    span = _span(ui)
    if span:
        entries = [e for e in entries if e.get("t", 0) >= time.time() - span]
    cw, ch = (w - 16) // 2, (h - 16) // 2
    series = [
        ("Or", [(e["t"], e.get("money", 0) / 10000) for e in entries], C["gold"], lambda v: f"{v:,.0f} or".replace(",", " ")),
        ("Niveau d'objet équipé", [(e["t"], e.get("ilvl", 0)) for e in entries], C["blue"], lambda v: f"{v:.1f}"),
        ("Temps de jeu (heures)", [(e["t"], e["played"] / 3600) for e in entries if e.get("played")], C["green"],
         lambda v: f"{v:,.1f} h".replace(",", " ")),
        ("Points de haut fait", [(e["t"], e["ach_points"]) for e in entries if e.get("ach_points")], C["orange"], lambda v: f"{v:,.0f}".replace(",", " ")),
    ]
    for i, (title, points, color, fmt) in enumerate(series):
        ui.chart((x + (i % 2) * (cw + 16), y + (i // 2) * (ch + 16), cw, ch), points, color, fmt, title)


def _draw_journal(ui, ctx, rect):
    x, y, w, h = rect
    c = ctx.character
    left = (x, y, w - 436, h)
    right = (x + w - 420, y, 420, h)
    span = _span(ui)
    events = ctx.activity.recent(c.key, 1000)
    if span:
        events = [e for e in events if e.get("t", 0) >= time.time() - span]

    ui.frame(left, f"Journal d'activité ({len(events)})")
    px, py = left[0] + 16, left[1] + 44
    for key, label in [("all", "Tout")] + list(_KIND_LABELS.items()):
        pw = ui.fonts["small"].size(label)[0] + 24
        if px + pw > left[0] + left[2] - 16:
            px, py = left[0] + 16, py + 32
        ui.pill((px, py, pw, 26), label, ui.state["event_filter"] == key, lambda k=key: ui.state.update(event_filter=k))
        px += pw + 5
    flt = ui.state["event_filter"]
    shown = [e for e in events if flt == "all" or e.get("kind") == flt]
    area = pygame.Rect(left[0] + 10, py + 38, left[2] - 20, left[3] - (py - left[1]) - 50)
    if not shown:
        message(ui, area, ["Aucun événement sur cette période", "(ils s'ajoutent à chaque synchronisation avec le jeu)"])
    else:
        top = ui.scroll_begin("activity", area, len(shown) * 30)
        for i, event in enumerate(shown):
            ry = top + i * 30
            if ry + 30 < area.y or ry > area.bottom:
                continue
            stamp = time.localtime(event.get("t", 0))
            ui.text(time.strftime("%d/%m %H:%M", stamp), "tiny", "gray", (area.x + 8, ry + 8))
            pygame.draw.circle(ui.screen, EVENT_COLORS.get(event.get("kind"), C["gray"]), (area.x + 96, ry + 14), 5)
            ui.text(ui.fit(event.get("text", ""), "small", area.w - 150), "small", "text", (area.x + 110, ry + 5))
        ui.scroll_end()

    # résumé de la période
    ui.frame(right, "Résumé de la période")
    entries = ctx.history.get_recent(c.key, 5000)
    if span:
        entries = [e for e in entries if e.get("t", 0) >= time.time() - span]
    lines = []
    if len(entries) >= 2:
        first, last = entries[0], entries[-1]
        gold = (last.get("money", 0) - first.get("money", 0)) / 10000
        lines += [("Niveaux gagnés", str(last.get("level", 0) - first.get("level", 0))),
                  ("Or", f"{gold:+,.0f} or".replace(",", " ")),
                  ("Niveau d'objet", f"{first.get('ilvl', 0):g} → {last.get('ilvl', 0):g}")]
        if last.get("played") and first.get("played"):
            lines.append(("Temps joué", format_duration(last["played"] - first["played"])))
        if last.get("ach_points") and first.get("ach_points"):
            lines.append(("Points de haut fait", f"{last['ach_points'] - first['ach_points']:+d}"))
    kinds = {}
    for e in events:
        kinds[e.get("kind")] = kinds.get(e.get("kind"), 0) + 1
    lines += [("Quêtes rendues", str(sum(1 for e in events if e.get("text", "").startswith("Quête rendue")))),
              ("Quêtes acceptées", str(sum(1 for e in events if e.get("text", "").startswith("Quête acceptée")))),
              ("Zones visitées", str(len({e["text"] for e in events if e.get("kind") == "zone"}))),
              ("Morts", str(kinds.get("death", 0))),
              ("Hauts faits obtenus", str(kinds.get("achievement", 0))),
              ("Nouvelles collections", str(kinds.get("collection", 0))),
              ("Changements d'équipement", str(kinds.get("gear", 0)))]
    ry = right[1] + 52
    for i, (label, value) in enumerate(lines):
        if i % 2 == 0:
            pygame.draw.rect(ui.screen, C["panel_alt"], (right[0] + 10, ry - 2, right[2] - 20, 28))
        ui.text(label, "small", "label", (right[0] + 20, ry + 2))
        ui.text(value, "small", "text", (right[0] + right[2] - 20, ry + 2), anchor="topright")
        ry += 28
    ui.text("Tout ce qui est affiché vient de l'API officielle de WoW", "tiny", "gray", (right[0] + 20, right[1] + right[3] - 26))


def _draw_statistics(ui, ctx, rect):
    x, y, w, h = rect
    stats = ctx.data.stats
    left = (x, y, 420, h)
    right = (x + 436, y, w - 436, h)
    ui.frame(left, "Catégories de statistiques")
    ui.frame(right, "Statistiques du personnage")
    if not stats["cats"]:
        message(ui, rect, ["Statistiques non exportées", "Tapez /ha scan en jeu, puis /ha save."])
        return
    cats = {c["id"]: c for c in stats["cats"]}
    ordered = [c for c in stats["cats"]]
    area = pygame.Rect(left[0] + 10, left[1] + 46, left[2] - 20, left[3] - 58)
    sel = ui.state["stat_cat"]
    if sel not in cats:
        sel = next((c["id"] for c in ordered if stats["list"].get(str(c["id"]))), ordered[0]["id"])
        ui.state["stat_cat"] = sel
    top = ui.scroll_begin("stat_cats", area, len(ordered) * 32)
    for i, cat in enumerate(ordered):
        ry = top + i * 32
        if ry + 32 < area.y or ry > area.bottom:
            continue
        row = pygame.Rect(area.x + 2, ry, area.w - 20, 30)
        count = len(stats["list"].get(str(cat["id"]), []))
        if cat["id"] == sel:
            pygame.draw.rect(ui.screen, (44, 40, 30), row, border_radius=4)
            pygame.draw.rect(ui.screen, C["gold"], row, 1, border_radius=4)
        elif hover(row):
            pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
        indent = 18 if cat["parent"] in cats else 0
        ui.text(ui.fit(cat["name"], "small", row.w - 70 - indent), "small", "text" if count else "gray", (row.x + 10 + indent, ry + 7))
        if count:
            ui.text(str(count), "small", "light_gray", (row.right - 8, ry + 7), anchor="topright")
        ui.click(row, lambda c=cat["id"]: ui.state.update(stat_cat=c))
    ui.scroll_end()

    query = ui.input_box((right[0] + 16, right[1] + 44, 340, 28), "stat_search", "Rechercher dans toutes les statistiques…")
    ui.text("Analyse : " + format_age(stats["updated"]), "small", "gray", (right[0] + right[2] - 20, right[1] + 50), anchor="topright")
    if query:
        rows = [(cats[int(cid)]["name"] if int(cid) in cats else "", s) for cid, lst in stats["list"].items()
                for s in lst if query in s["name"].lower()]
    else:
        rows = [(None, s) for s in stats["list"].get(str(sel), [])]
    area = pygame.Rect(right[0] + 10, right[1] + 84, right[2] - 20, right[3] - 96)
    if not rows:
        message(ui, area, ["Aucune statistique"])
        return
    top = ui.scroll_begin("stat_list", area, len(rows) * 30)
    for i, (cat_name, stat) in enumerate(rows):
        ry = top + i * 30
        if ry + 30 < area.y or ry > area.bottom:
            continue
        if i % 2 == 0:
            pygame.draw.rect(ui.screen, C["panel_alt"], (area.x + 2, ry, area.w - 22, 28))
        label = stat["name"] + (f"   ({cat_name})" if cat_name else "")
        ui.text(ui.fit(label, "small", area.w - 230), "small", "text", (area.x + 12, ry + 5))
        ui.text(stat["value"], "small", "gold", (area.right - 30, ry + 5), anchor="topright")
    ui.scroll_end()
