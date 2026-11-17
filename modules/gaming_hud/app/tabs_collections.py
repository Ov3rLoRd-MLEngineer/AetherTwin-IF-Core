"""
Onglet Collections du bataillon : Montures, Codex des mascottes, Jouets, Héritage, Transmoglyphe.
Chaque collection s'affiche sur deux colonnes, avec un emplacement réservé au futur modèle 3D à droite.
"""
import pygame

from character import CLASS_COLORS
from icons_draw import draw_icon
from tabutil import format_age, hover, message
from theme import C, QUALITY_COLORS, clean_wow_text, format_gold
from wowhead import battle_pet_url, item_url, spell_url, transmog_set_url

SUBTABS = [("mounts", "Montures"), ("pets", "Codex des mascottes"), ("toys", "Jouets"),
           ("heirlooms", "Héritage"), ("transmog", "Transmoglyphe")]

PET_TYPES = {1: "Humanoïde", 2: "Draconien", 3: "Volant", 4: "Mort-vivant", 5: "Bestiole", 6: "Magique",
             7: "Élémentaire", 8: "Bête", 9: "Aquatique", 10: "Mécanique"}
PET_TYPE_COLORS = {1: (200, 160, 100), 2: (90, 180, 90), 3: (120, 170, 230), 4: (150, 120, 190), 5: (190, 190, 120),
                   6: (80, 160, 230), 7: (230, 130, 60), 8: (200, 90, 90), 9: (60, 180, 200), 10: (170, 170, 175)}
PET_RARITY = {1: "Médiocre", 2: "Commune", 3: "Inhabituelle", 4: "Rare"}

CLASSES = [(1, "Guerrier", "WARRIOR"), (2, "Paladin", "PALADIN"), (3, "Chasseur", "HUNTER"), (4, "Voleur", "ROGUE"),
           (5, "Prêtre", "PRIEST"), (6, "DK", "DEATHKNIGHT"), (7, "Chaman", "SHAMAN"), (8, "Mage", "MAGE"),
           (9, "Démoniste", "WARLOCK"), (10, "Moine", "MONK"), (11, "Druide", "DRUID"), (12, "DH", "DEMONHUNTER"),
           (13, "Évocateur", "EVOKER")]
CLASS_FULL = {6: "Chevalier de la mort", 12: "Chasseur de démons"}
# type d'armure de chaque classe (1 tissu, 2 cuir, 3 mailles, 4 plaques)
ARMOR_OF_CLASS = {5: 1, 8: 1, 9: 1, 4: 2, 10: 2, 11: 2, 12: 2, 3: 3, 7: 3, 13: 3, 1: 4, 2: 4, 6: 4}
ARMOR_NAMES = {1: "tissu", 2: "cuir", 3: "mailles", 4: "plaques"}
ALL_CLASS_SLOTS = ("INVTYPE_CLOAK", "INVTYPE_BODY", "INVTYPE_TABARD")


def _color(rgb, dim=False):
    return tuple(int(v * 0.55) for v in rgb) if dim else rgb


def draw_collections(ui, ctx, rect):
    x, y, w, h = rect
    px = x
    for key, label in SUBTABS:
        pw = ui.fonts["small"].size(label)[0] + 36
        ui.pill((px, y, pw, 32), label, ui.state["collection"] == key, lambda k=key: ui.state.update(collection=k))
        px += pw + 6
    ui.text("Or du bataillon : " + format_gold(ctx.data.collections.get("warbandMoney", 0)), "small", "gold",
            (x + w, y + 8), anchor="topright")
    body = (x, y + 44, w, h - 44)
    view = ui.state["collection"]
    {"mounts": _mounts, "pets": _pets, "toys": _toys, "heirlooms": _heirlooms, "transmog": _transmog}[view](ui, ctx, body)


# ===========================================================================
#  Mise en page commune : liste sur deux colonnes + panneau de détail avec modèle 3D
# ===========================================================================
def _selected(ui, view, entries, keyfn):
    key = ui.state["sel"].get(view)
    for entry in entries:
        if keyfn(entry) == key:
            return entry
    return entries[0] if entries else None


def _two_columns(ui, area, scroll_key, entries, view, keyfn, draw_cell):
    """Liste défilante sur 2 colonnes ; draw_cell(cell, entry, selected) dessine une cellule."""
    if not entries:
        message(ui, area, ["Aucun résultat"])
        return
    selected_key = keyfn(_selected(ui, view, entries, keyfn))
    cell_w = (area.w - 20) // 2
    rows = (len(entries) + 1) // 2
    top = ui.scroll_begin(scroll_key, area, rows * 54)
    for i, entry in enumerate(entries):
        ry = top + (i // 2) * 54
        if ry + 54 < area.y or ry > area.bottom:
            continue
        cell = pygame.Rect(area.x + (i % 2) * cell_w, ry, cell_w - 6, 50)
        selected = keyfn(entry) == selected_key
        if selected:
            pygame.draw.rect(ui.screen, (44, 40, 30), cell, border_radius=5)
            pygame.draw.rect(ui.screen, C["gold"], cell, 1, border_radius=5)
        elif hover(cell):
            pygame.draw.rect(ui.screen, C["row_hover"], cell, border_radius=5)
        draw_cell(cell, entry, selected)
        ui.click(cell, lambda k=keyfn(entry): ui.state["sel"].update({view: k}))
    ui.scroll_end()


def _detail(ui, rect, caption, tint, shape, title, title_color, lines, url, llm_title, llm_context):
    x, y, w, h = rect
    ui.frame(rect, "Détail")
    ui.model_placeholder((x + 16, y + 46, w - 32, 300), caption, tint, shape)
    ry = y + 360
    ui.text(ui.fit(title, "large", w - 32), "large", title_color, (x + 16, ry), shadow=True)
    ry += 38
    for text, color in lines:
        for line in ui.wrap(text, "small", w - 36):
            if ry > y + h - 70:
                break
            ui.text(line, "small", color, (x + 16, ry))
            ry += 21
        ry += 4
    ui.detail_buttons(x + 16, y + h - 50, url, llm_title, llm_context)


def _filters(ui, x, y, key, options):
    px = x
    for value, label in options:
        pw = ui.fonts["small"].size(label)[0] + 26
        ui.pill((px, y, pw, 28), label, ui.state[key] == value, lambda v=value: ui.state.update({key: v}))
        px += pw + 6


def _layout(rect):
    x, y, w, h = rect
    left_w = 790
    return (x, y, left_w, h), (x + left_w + 16, y, w - left_w - 16, h)


def _owned_filter(entries, mode, owned_fn):
    if mode == "owned":
        return [e for e in entries if owned_fn(e)]
    if mode == "missing":
        return [e for e in entries if not owned_fn(e)]
    return entries


def _context(kind, name, status, extra, url):
    lines = [f"{kind} World of Warcraft : « {name} » ({status})."]
    lines += [e for e in extra if e]
    lines.append(f"Lien Wowhead : {url}")
    return "\n".join(lines)


# ===========================================================================
#  Montures
# ===========================================================================
def _mounts(ui, ctx, rect):
    data = ctx.data
    entries = list(data.mounts["list"])
    if not entries:   # pas d'analyse complète : on se rabat sur la liste des montures obtenues
        entries = [{"id": m["id"], "spellID": m["spellID"], "name": m["name"], "collected": True, "source": "", "desc": ""}
                   for m in data.collections["mounts"]["list"]]
    left, right = _layout(rect)
    owned = sum(1 for e in entries if e["collected"])
    ui.frame(left, f"Montures — {owned} obtenues / {len(entries)}")
    _filters(ui, left[0] + 16, left[1] + 44, "mount_filter", [("all", "Toutes"), ("owned", "Obtenues"), ("missing", "Manquantes")])
    query = ui.input_box((left[0] + 16, left[1] + 80, 360, 28), "mount_search", "Rechercher une monture…")
    ui.text("Analyse : " + format_age(data.mounts["updated"]), "small", "gray", (left[0] + left[2] - 20, left[1] + 52), anchor="topright")
    shown = [e for e in _owned_filter(entries, ui.state["mount_filter"], lambda m: m["collected"])
             if query in e["name"].lower()]
    shown.sort(key=lambda e: e["name"])
    area = pygame.Rect(left[0] + 10, left[1] + 120, left[2] - 20, left[3] - 132)

    def cell(rc, m, selected):
        ui.icon("spell", m["spellID"], (rc.x + 5, rc.y + 5, 40, 40), border=C["gold"] if m["collected"] else C["frame"], fallback=m["name"])
        ui.text(ui.fit(m["name"], "small", rc.w - 70), "small", "text" if m["collected"] else "gray", (rc.x + 54, rc.y + 8))
        ui.text("Obtenue" if m["collected"] else "Manquante", "tiny", "green" if m["collected"] else "orange", (rc.x + 54, rc.y + 28))
    _two_columns(ui, area, "mounts", shown, "mounts", lambda m: m["id"], cell)

    m = _selected(ui, "mounts", shown, lambda e: e["id"])
    if m is None:
        ui.frame(right, "Détail")
        return
    url = spell_url(m["spellID"])
    source = clean_wow_text(m["source"]).strip()
    desc = clean_wow_text(m["desc"]).strip()
    _detail(ui, right, "Modèle 3D de la monture", (40, 44, 60), "object", m["name"], C["gold"],
            [("Obtenue" if m["collected"] else "Pas encore obtenue", C["green"] if m["collected"] else C["orange"]),
             (source, C["light_gray"]), (desc, C["gray"])], url, f"Monture : {m['name']}",
            _context("Monture", m["name"], "obtenue" if m["collected"] else "pas encore obtenue", [f"Source : {source}", desc], url))


# ===========================================================================
#  Codex des mascottes
# ===========================================================================
def _pets(ui, ctx, rect):
    data = ctx.data
    entries = data.pets["list"]
    left, right = _layout(rect)
    owned = sum(1 for e in entries if e["owned"])
    ui.frame(left, f"Codex des mascottes — {owned} possédées / {len(entries)}")
    _filters(ui, left[0] + 16, left[1] + 44, "pet_filter", [("all", "Toutes"), ("owned", "Possédées"), ("missing", "Manquantes")])
    query = ui.input_box((left[0] + 16, left[1] + 80, 360, 28), "pet_search", "Rechercher une mascotte…")
    ui.text("Analyse : " + format_age(data.pets["updated"]), "small", "gray", (left[0] + left[2] - 20, left[1] + 52), anchor="topright")
    # filtre par famille
    px, py = left[0] + 16, left[1] + 116
    for tid, name in [(None, "Toutes familles")] + list(PET_TYPES.items()):
        pw = ui.fonts["tiny"].size(name)[0] + 22
        if px + pw > left[0] + left[2] - 14:
            px, py = left[0] + 16, py + 30
        ui.pill((px, py, pw, 24), name, ui.state["pet_type"] == tid, lambda t=tid: ui.state.update(pet_type=t), font="tiny")
        px += pw + 4
    shown = [e for e in _owned_filter(entries, ui.state["pet_filter"], lambda p: p["owned"])
             if query in e["name"].lower() and (ui.state["pet_type"] is None or e["type"] == ui.state["pet_type"])]
    shown.sort(key=lambda e: e["name"])
    if not entries:
        message(ui, left, ["Codex non exporté", "Tapez /ha scan en jeu, puis /ha save."])
    area = pygame.Rect(left[0] + 10, py + 36, left[2] - 20, left[3] - (py - left[1]) - 48)

    def cell(rc, p, selected):
        tint = PET_TYPE_COLORS.get(p["type"], (150, 150, 150))
        icon = pygame.Rect(rc.x + 5, rc.y + 5, 40, 40)
        pygame.draw.rect(ui.screen, _color(tint, dim=not p["owned"]), icon, border_radius=5)
        ui.text(PET_TYPES.get(p["type"], "?")[:2].upper(), "small", (10, 10, 12), icon.center, anchor="center")
        ui.text(ui.fit(p["name"], "small", rc.w - 70), "small", "text" if p["owned"] else "gray", (rc.x + 54, rc.y + 8))
        if p["owned"]:
            rarity = PET_RARITY.get(p["rarity"], "")
            ui.text(f"Niv. {p['level']}  ·  {rarity}" + (f"  ·  ×{p['owned']}" if p["owned"] > 1 else ""), "tiny",
                    QUALITY_COLORS.get(max(0, p["rarity"] - 1), (200, 200, 200)), (rc.x + 54, rc.y + 28))
        else:
            ui.text("Manquante", "tiny", "orange", (rc.x + 54, rc.y + 28))
    _two_columns(ui, area, "pets", shown, "pets", lambda p: p["id"], cell)

    p = _selected(ui, "pets", shown, lambda e: e["id"])
    if p is None:
        ui.frame(right, "Détail")
        return
    url = battle_pet_url(p["id"])
    lines = [(f"Famille : {PET_TYPES.get(p['type'], '?')}", PET_TYPE_COLORS.get(p["type"], C["light_gray"]))]
    if p["owned"]:
        lines.append((f"Possédée ×{p['owned']}  ·  niveau max. {p['level']}  ·  {PET_RARITY.get(p['rarity'], '')}", C["green"]))
    else:
        lines.append(("Pas encore possédée", C["orange"]))
    lines.append(("Combat de mascottes : " + ("oui" if p["battle"] else "non"), C["gray"]))
    source, desc = clean_wow_text(p["source"]).strip(), clean_wow_text(p["desc"]).strip()
    lines += [(source, C["light_gray"]), (desc, C["gray"])]
    _detail(ui, right, "Modèle 3D de la mascotte", PET_TYPE_COLORS.get(p["type"], (60, 60, 70)), "object", p["name"],
            C["gold"], lines, url, f"Mascotte : {p['name']}",
            _context("Mascotte de combat", p["name"], "possédée" if p["owned"] else "pas encore possédée",
                     [f"Famille : {PET_TYPES.get(p['type'], '?')}", f"Source : {source}", desc], url))


# ===========================================================================
#  Jouets et héritage
# ===========================================================================
def _simple_collection(ui, ctx, rect, view, title, entries, filter_key, search_key, subtitle_fn, caption, detail_lines_fn, kind_label):
    left, right = _layout(rect)
    owned = sum(1 for e in entries if e["owned"])
    ui.frame(left, f"{title} — {owned} obtenus / {len(entries)}")
    _filters(ui, left[0] + 16, left[1] + 44, filter_key, [("all", "Tous"), ("owned", "Obtenus"), ("missing", "Manquants")])
    query = ui.input_box((left[0] + 16, left[1] + 80, 360, 28), search_key, "Rechercher…")
    if not entries:
        message(ui, left, [f"{title} non exporté(s)", "Tapez /ha scan en jeu, puis /ha save."])
    shown = [e for e in _owned_filter(entries, ui.state[filter_key], lambda t: t["owned"])
             if query in (e["name"] or "").lower()]
    shown.sort(key=lambda e: e["name"] or "")
    area = pygame.Rect(left[0] + 10, left[1] + 120, left[2] - 20, left[3] - 132)

    def cell(rc, it, selected):
        name = it["name"] or ui.icons.display_name(it["id"]) or f"Objet {it['id']}"
        quality = QUALITY_COLORS.get(it.get("quality", 1), (255, 255, 255)) if it["owned"] else C["frame"]
        ui.icon("item", it["id"], (rc.x + 5, rc.y + 5, 40, 40), border=quality, fallback=name)
        ui.text(ui.fit(name, "small", rc.w - 70), "small", "text" if it["owned"] else "gray", (rc.x + 54, rc.y + 8))
        ui.text(subtitle_fn(it), "tiny", "green" if it["owned"] else "orange", (rc.x + 54, rc.y + 28))
    _two_columns(ui, area, view, shown, view, lambda t: t["id"], cell)

    it = _selected(ui, view, shown, lambda e: e["id"])
    if it is None:
        ui.frame(right, "Détail")
        return
    name = it["name"] or ui.icons.display_name(it["id"]) or f"Objet {it['id']}"
    url = item_url(it["id"])
    lines = detail_lines_fn(it)
    _detail(ui, right, caption, (46, 46, 56), "object", name, QUALITY_COLORS.get(it.get("quality", 1), C["gold"]) if it["owned"] else C["gold"],
            lines, url, f"{kind_label} : {name}",
            _context(kind_label, name, "obtenu" if it["owned"] else "pas encore obtenu", [t for t, _ in lines], url))


def _toys(ui, ctx, rect):
    _simple_collection(ui, ctx, rect, "toys", "Jouets", ctx.data.toys["list"], "toy_filter", "toy_search",
                       lambda t: "Obtenu" if t["owned"] else "Manquant", "Modèle 3D du jouet",
                       lambda t: [("Obtenu" if t["owned"] else "Pas encore obtenu", C["green"] if t["owned"] else C["orange"])], "Jouet")


def _heirlooms(ui, ctx, rect):
    def lines(h):
        out = [("Obtenu" if h["owned"] else "Pas encore obtenu", C["green"] if h["owned"] else C["orange"])]
        if h.get("slot"):
            out.append((f"Emplacement : {h['slot'].replace('INVTYPE_', '').title()}", C["light_gray"]))
        if h.get("source"):
            out.append((clean_wow_text(h["source"]), C["gray"]))
        return out
    _simple_collection(ui, ctx, rect, "heirlooms", "Héritage", ctx.data.heirlooms["list"], "toy_filter", "heirloom_search",
                       lambda t: "Obtenu" if t["owned"] else "Manquant", "Modèle 3D de l'objet d'héritage", lines, "Objet d'héritage")


# ===========================================================================
#  Transmoglyphe (apparences obtenues par le compte + ensembles)
# ===========================================================================
def _item_ok(item, class_id):
    if class_id is None:
        return True
    if item["equipLoc"] in ALL_CLASS_SLOTS or item["classID"] != 4:
        return True
    sub = item["subClassID"]
    return sub not in ARMOR_NAMES or ARMOR_OF_CLASS.get(class_id) == sub


def _set_ok(tm_set, class_id):
    return class_id is None or tm_set["classMask"] == 0 or bool(tm_set["classMask"] & (1 << (class_id - 1)))


def _classes_of_item(item):
    if item["equipLoc"] in ALL_CLASS_SLOTS or item["classID"] != 4 or item["subClassID"] not in ARMOR_NAMES:
        return "Toutes les classes"
    sub = item["subClassID"]
    names = [CLASS_FULL.get(cid, name) for cid, name, _ in CLASSES if ARMOR_OF_CLASS[cid] == sub]
    return f"Armure en {ARMOR_NAMES[sub]} : " + ", ".join(names)


def _classes_of_set(tm_set):
    if tm_set["classMask"] == 0:
        return "Toutes les classes"
    return ", ".join(CLASS_FULL.get(cid, name) for cid, name, _ in CLASSES if tm_set["classMask"] & (1 << (cid - 1)))


def _transmog(ui, ctx, rect):
    x, y, w, h = rect
    tm = ctx.data.transmog
    class_id = ui.state["tm_class"]
    sel = ui.state["tm_sel"]

    # ------------------------------------------------ barre du haut : recherche, Wowhead, assistant
    ui.frame((x, y, w, 118))
    query = ui.input_box((x + 16, y + 12, 400, 30), "tm_search", "Rechercher une apparence ou un ensemble…")
    ui.text("Analyse : " + format_age(tm["updated"]), "small", "gray", (x + 430, y + 20))
    info = _tm_selection(ui, ctx, sel)
    bx = x + w - 16 - 410
    if info:
        ui.detail_buttons(bx, y + 10, info["url"], info["llm_title"], info["llm_context"])
    else:
        ui.text("Sélectionnez une apparence ou un ensemble", "small", "gray", (x + w - 16, y + 20), anchor="topright")
    ui.text("Classe :", "small", "label", (x + 16, y + 62))
    px = x + 90
    for cid, label in [(None, "Toutes")] + [(c[0], c[1]) for c in CLASSES]:
        pw = ui.fonts["small"].size(label)[0] + 22
        key = CLASSES[cid - 1][2] if cid else None
        color = CLASS_COLORS.get(key, C["text"]) if key else C["text"]
        rc = pygame.Rect(px, y + 56, pw, 28)
        active = class_id == cid
        pygame.draw.rect(ui.screen, (44, 40, 30) if active else (28, 28, 33), rc, border_radius=5)
        pygame.draw.rect(ui.screen, C["gold"] if active else C["frame"], rc, 2 if active else 1, border_radius=5)
        ui.text(label, "small", color, rc.center, anchor="center")
        ui.click(rc, lambda c=cid: ui.state.update(tm_class=c))
        if cid in CLASS_FULL:
            ui.tip(rc, {"rows": [(CLASS_FULL[cid], color, "")]})
        px += pw + 5
    ui.text("Les restrictions d'armure par classe suivent les règles générales du jeu (les armes sont ouvertes à toutes).",
            "tiny", "gray", (x + 16, y + 94))

    left = (x, y + 130, 760, h - 130)
    right = (x + 776, y + 130, w - 776, h - 130)
    ui.frame(left, "Apparences obtenues par le compte")
    if not tm["cats"] and not tm["sets"]:
        message(ui, left, ["Transmogrification non exportée", "Tapez /ha scan en jeu (transmog, ensembles), puis /ha save."])
        _tm_detail(ui, right, info)
        return

    # ------------------------------------------------ liste dépliable
    opened = ui.state["tm_open"]
    rows = []
    for cat in tm["cats"]:
        items = [it for it in tm["items"].get(str(cat["id"]), []) if _item_ok(it, class_id)]
        names = {}
        for it in items:
            names[it["source"]] = it["name"] or ui.icons.display_name(it["id"]) or f"Objet {it['id']}"
        if query:
            items = [it for it in items if query in names[it["source"]].lower()]
        if class_id is not None and not items:
            continue
        if query and not items:
            continue
        rows.append(("cat", cat, len(items)))
        if cat["id"] in opened or query:
            rows += [("item", (cat["id"], it, names[it["source"]]), 0) for it in items]
    sets = [s for s in tm["sets"] if _set_ok(s, class_id) and (not query or query in s["name"].lower() or query in s["label"].lower())]
    owned_sets = [s for s in sets if s["total"] and s["have"] >= s["total"]]
    todo_sets = [s for s in sets if not (s["total"] and s["have"] >= s["total"])]
    if tm["sets"]:
        rows.append(("setsec", None, len(sets)))
        if "sets" in opened or query:
            rows.append(("subhead", f"Ensembles possédés ({len(owned_sets)})", 0))
            rows += [("set", s, 0) for s in sorted(owned_sets, key=lambda s: s["name"])]
            rows.append(("subhead", f"Ensembles à obtenir ({len(todo_sets)})", 0))
            rows += [("set", s, 0) for s in sorted(todo_sets, key=lambda s: (-s["have"] / max(1, s["total"]), s["name"]))]
    heights = {"cat": 44, "setsec": 44, "item": 30, "set": 34, "subhead": 30}
    area = pygame.Rect(left[0] + 10, left[1] + 46, left[2] - 20, left[3] - 58)
    top = ui.scroll_begin("tm_list", area, sum(heights[r[0]] for r in rows) + 8)
    ry = top
    for kind, data, count in rows:
        rh = heights[kind]
        if ry + rh >= area.y and ry <= area.bottom:
            row = pygame.Rect(area.x + 2, ry, area.w - 22, rh - 2)
            if kind in ("cat", "setsec"):
                key = data["id"] if kind == "cat" else "sets"
                is_open = key in opened or bool(query)
                pygame.draw.rect(ui.screen, C["header"], row, border_radius=5)
                pygame.draw.rect(ui.screen, C["header_border"], row, 1, border_radius=5)
                draw_icon(ui.screen, data["id"] if kind == "cat" else "set", (row.x + 8, row.y + 7, 28, 28), C["gold"])
                label = data["name"] if kind == "cat" else "Ensembles"
                ui.text(("▾ " if is_open else "▸ ") + label, "medium", "gold", (row.x + 46, row.y + 10), shadow=True)
                if kind == "cat":
                    ui.text(f"{count} affichées  ·  {data['collected']}/{data['total']} dans le jeu", "small", "light_gray",
                            (row.right - 12, row.y + 12), anchor="topright")
                else:
                    ui.text(f"{len(owned_sets)} possédés  ·  {len(todo_sets)} à obtenir", "small", "light_gray",
                            (row.right - 12, row.y + 12), anchor="topright")
                ui.click(row, lambda k=key: (opened.remove(k) if k in opened else opened.append(k)))
            elif kind == "subhead":
                ui.text(data, "small", "label", (row.x + 20, ry + 7))
            elif kind == "item":
                cat_id, item, name = data
                active = sel == ("item", cat_id, item["source"])
                if active:
                    pygame.draw.rect(ui.screen, (44, 40, 30), row, border_radius=4)
                    pygame.draw.rect(ui.screen, C["gold"], row, 1, border_radius=4)
                elif hover(row):
                    pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
                quality = QUALITY_COLORS.get(item["quality"], (255, 255, 255))
                ui.text(ui.fit(name, "small", row.w - 60), "small", quality, (row.x + 30, ry + 5))
                ui.click(row, lambda c=cat_id, s=item["source"]: ui.state.update(tm_sel=("item", c, s)))
            else:
                s = data
                active = sel == ("set", s["id"])
                if active:
                    pygame.draw.rect(ui.screen, (44, 40, 30), row, border_radius=4)
                    pygame.draw.rect(ui.screen, C["gold"], row, 1, border_radius=4)
                elif hover(row):
                    pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
                complete = s["total"] and s["have"] >= s["total"]
                ui.text(ui.fit(s["name"] + (f"  —  {s['label']}" if s["label"] else ""), "small", row.w - 150), "small",
                        "green" if complete else "text", (row.x + 30, ry + 7))
                ui.text(f"{s['have']}/{s['total']}", "small", "green" if complete else "orange", (row.right - 12, ry + 7), anchor="topright")
                ui.click(row, lambda sid=s["id"]: ui.state.update(tm_sel=("set", sid)))
        ry += rh
    ui.scroll_end()
    if not rows:
        message(ui, area, ["Aucune apparence ne correspond"])
    _tm_detail(ui, right, info)


def _tm_selection(ui, ctx, sel):
    """Description de la sélection courante (apparence ou ensemble) : titre, lignes, liens, contexte pour l'assistant."""
    tm = ctx.data.transmog
    if not sel:
        return None
    if sel[0] == "item":
        for item in tm["items"].get(str(sel[1]), []):
            if item["source"] == sel[2]:
                name = item["name"] or ui.icons.display_name(item["id"]) or f"Objet {item['id']}"
                if not item["name"]:
                    ui.icons.request(item["id"])
                cat = next((c["name"] for c in tm["cats"] if c["id"] == sel[1]), "")
                url = item_url(item["id"])
                lines = [(f"Catégorie : {cat}", C["light_gray"]), (_classes_of_item(item), C["gray"]),
                         ("Apparence obtenue par le compte", C["green"])]
                return {"title": name, "color": QUALITY_COLORS.get(item["quality"], C["gold"]), "lines": lines, "url": url,
                        "caption": "Modèle 3D de l'objet équipé", "llm_title": f"Apparence : {name}",
                        "llm_context": _context("Apparence de transmogrification", name, "obtenue", [f"Catégorie : {cat}", _classes_of_item(item)], url)}
    else:
        for s in tm["sets"]:
            if s["id"] == sel[1]:
                url = transmog_set_url(s["id"])
                complete = s["total"] and s["have"] >= s["total"]
                lines = [(s["label"], C["light_gray"]), (_classes_of_set(s), C["gray"]),
                         (f"{s['have']}/{s['total']} pièces obtenues", C["green"] if complete else C["orange"])]
                return {"title": s["name"], "color": C["gold"], "lines": lines, "url": url, "caption": "Modèle 3D de l'ensemble",
                        "llm_title": f"Ensemble : {s['name']}",
                        "llm_context": _context("Ensemble de transmogrification", s["name"],
                                                f"{s['have']}/{s['total']} pièces obtenues", [s["label"], _classes_of_set(s)], url)}
    return None


def _tm_detail(ui, rect, info):
    x, y, w, h = rect
    ui.frame(rect, "Aperçu")
    ui.model_placeholder((x + 16, y + 46, w - 32, h - 200), info["caption"] if info else "Modèle 3D", (46, 46, 56), "person")
    if not info:
        ui.text("Choisissez un élément dans la liste", "small", "gray", (x + w // 2, y + h - 90), anchor="center")
        return
    ry = y + h - 140
    ui.text(ui.fit(info["title"], "large", w - 32), "large", info["color"], (x + 16, ry), shadow=True)
    ry += 36
    for text, color in info["lines"]:
        for line in ui.wrap(text, "small", w - 36)[:2]:
            if ry < y + h - 18:
                ui.text(line, "small", color, (x + 16, ry))
            ry += 20
