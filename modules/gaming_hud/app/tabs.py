"""
Contenu des onglets de WoW Assistant (sauf Personnage, qui est dans ui.py).
Chaque fonction reçoit l'interface (ui), le contexte (ctx) et le rectangle de contenu.
"""
import time

import pygame

from theme import C, EVENT_COLORS, QUALITY_COLORS, format_gold
from wowhead import item_url, quest_url, spell_url, talent_calc_url
from character import Character


from tabutil import format_age, hover as _hover, message as _message


# ===========================================================================
#  Talents et grimoire
# ===========================================================================
def draw_talents(ui, ctx, rect):
    x, y, w, h = rect
    c, data = ctx.character, ctx.data
    left = (x, y, 520, h)
    right = (x + 536, y, w - 536, h)

    # ---------------- Talents
    t = data.talents
    ui.frame(left, "Talents")
    ui.text(c.spec or "Spécialisation inconnue", "large", c.class_color, (x + 16, y + 48), shadow=True)
    ui.text(f"{c.class_name} · niveau {c.level}", "small", "light_gray", (x + 16, y + 80))
    info = f"Points dépensés : {t['points']}"
    if t.get("hero"):
        info += f"   ·   Héros : {t['hero']}"
    ui.text(ui.fit(info, "small", 488), "small", "label", (x + 16, y + 102))
    if t.get("loadout"):
        url = talent_calc_url(t["loadout"])
        ui.pill((x + 16, y + 126, 310, 28), "Ouvrir dans le calculateur Wowhead", False,
                lambda u=url: ui._open_url(u))

    area = pygame.Rect(x + 10, y + 166, 500, h - 178)
    nodes = t["nodes"]
    if not nodes:
        _message(ui, area, ["Aucun talent exporté", "(niveau < 10, ou tapez /ha save en jeu)"])
    else:
        top = ui.scroll_begin("talents", area, len(nodes) * 44)
        for i, node in enumerate(nodes):
            ry = top + i * 44
            if ry + 44 < area.y or ry > area.bottom:
                continue
            row = pygame.Rect(area.x, ry, area.w - 12, 40)
            if _hover(row):
                pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
            maxed = node.get("rank", 1) >= node.get("maxRank", 1)
            ui.icon("spell", node.get("spellID"), (area.x + 4, ry + 2, 36, 36),
                    border=C["gold"] if maxed else C["frame_hi"], fallback=node.get("name", "?"))
            ui.text(ui.fit(node.get("name") or f"Sort {node.get('spellID')}", "small", 340), "small", "text",
                    (area.x + 50, ry + 11))
            ui.text(f"{node.get('rank', 1)}/{node.get('maxRank', 1)}", "small", "gold" if maxed else "light_gray",
                    (area.right - 22, ry + 11), anchor="topright")
            ui.tip(row, {"rows": [(node.get("name", ""), C["gold"], ""),
                                  (f"Rang {node.get('rank', 1)}/{node.get('maxRank', 1)}", C["text"], "")],
                         "footer": "Clic : ouvrir sur Wowhead"})
            ui.link(row, spell_url(node.get("spellID")))
        ui.scroll_end()

    # ---------------- Grimoire
    book = data.spellbook
    ui.frame(right, f"Grimoire ({data.spell_count()} sorts)")
    if not book:
        _message(ui, right, ["Grimoire non exporté", "(tapez /ha save en jeu)"])
        return
    px, py = right[0] + 16, right[1] + 48
    line_index = min(ui.state["spell_line"], len(book) - 1)
    for i, line in enumerate(book):
        pw = max(90, ui.fonts["small"].size(line["name"])[0] + 26)
        ui.pill((px, py, pw, 28), line["name"], i == line_index,
                lambda i=i: ui.state.update(spell_line=i))
        px += pw + 6
    query = ui.input_box((right[0] + 16, right[1] + 86, 320, 28), "spell_search", "Rechercher un sort…")

    spells = [s for s in book[line_index]["spells"] if query in s["name"].lower()]
    area = pygame.Rect(right[0] + 10, right[1] + 126, right[2] - 20, h - 138)
    cols = 3
    cell_w = (area.w - 14) // cols
    rows = (len(spells) + cols - 1) // cols
    top = ui.scroll_begin("spellbook", area, rows * 46)
    for i, spell in enumerate(spells):
        ry = top + (i // cols) * 46
        if ry + 46 < area.y or ry > area.bottom:
            continue
        cell = pygame.Rect(area.x + (i % cols) * cell_w, ry, cell_w - 6, 42)
        if _hover(cell):
            pygame.draw.rect(ui.screen, C["row_hover"], cell, border_radius=4)
        ui.icon("spell", spell.get("id"), (cell.x + 4, cell.y + 3, 36, 36),
                border=C["frame"] if spell.get("passive") else C["light_gray"], fallback=spell["name"])
        ui.text(ui.fit(spell["name"], "small", cell.w - 56), "small", "text", (cell.x + 48, cell.y + 5))
        ui.text("Passif" if spell.get("passive") else "Actif", "tiny", "gray", (cell.x + 48, cell.y + 24))
        ui.tip(cell, {"rows": [(spell["name"], C["gold"], ""),
                               ("Passif" if spell.get("passive") else "Sort actif", C["light_gray"], "")],
                      "footer": "Clic : ouvrir sur Wowhead"})
        ui.link(cell, spell_url(spell.get("id")))
    ui.scroll_end()
    if not spells:
        _message(ui, area, ["Aucun sort ne correspond"])


# ===========================================================================
#  Journal des quêtes
# ===========================================================================
_STATUS_COLOR = {"complete": "green", "failed": "red", "incomplete": "text"}


def draw_quest_journal(ui, ctx, rect):
    x, y, w, h = rect
    tracker = ctx.quests
    left = (x, y, 640, h)
    right = (x + 656, y, w - 656, h)

    ui.frame(left, f"Journal ({tracker.count()}/{tracker.max_quests})")
    ready = len(tracker.ready_to_turn_in())
    ongoing = len(tracker.get_incomplete_quests())
    ui.text(f"{ready} à rendre   ·   {ongoing} en cours   ·   {tracker.completed_total} terminées au total",
            "small", "label", (x + 16, y + 46))

    area = pygame.Rect(x + 10, y + 74, 620, h - 86)
    if not tracker.quests:
        _message(ui, area, ["Aucune quête dans le journal"])
        return

    # lignes : zones et quêtes, dans l'ordre du journal
    rows = []
    for zone, quests in tracker.group_by_zone().items():
        rows.append(("zone", zone, 30))
        rows.extend(("quest", q, 28) for q in quests)
    total_h = sum(r[2] for r in rows)

    selected_id = ui.state["quest_id"]
    if tracker.get_quest_by_id(selected_id) is None:
        selected_id = next(r[1]["id"] for r in rows if r[0] == "quest")
        ui.state["quest_id"] = selected_id

    top = ui.scroll_begin("quests", area, total_h)
    ry = top
    for kind, item, rh in rows:
        if ry + rh >= area.y and ry <= area.bottom:
            if kind == "zone":
                ui.text(ui.fit(item, "small", 580), "small", "gold", (area.x + 6, ry + 6))
                pygame.draw.line(ui.screen, C["header_border"], (area.x + 4, ry + rh - 2), (area.right - 14, ry + rh - 2), 1)
            else:
                quest = item
                row = pygame.Rect(area.x + 4, ry, area.w - 18, rh - 2)
                if quest["id"] == selected_id:
                    pygame.draw.rect(ui.screen, (44, 40, 30), row, border_radius=4)
                    pygame.draw.rect(ui.screen, C["gold"], row, 1, border_radius=4)
                elif _hover(row):
                    pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
                color = _STATUS_COLOR.get(quest["status"], "text")
                ui.text(ui.fit(f"[{quest['level']}] {quest['name']}", "small", 440), "small", color, (row.x + 8, ry + 5))
                done, count = tracker.progress(quest)
                label = tracker.status_label(quest)
                if count and quest["status"] == "incomplete":
                    label = f"{done}/{count}"
                ui.text(label, "small", color, (row.right - 8, ry + 5), anchor="topright")
                ui.click(row, lambda q=quest["id"]: ui.state.update(quest_id=q))
        ry += rh
    ui.scroll_end()

    # ---------------- détail
    quest = tracker.get_quest_by_id(selected_id)
    ui.frame(right, "Détail de la quête")
    rx, ry = right[0] + 20, right[1] + 54
    rw = right[2] - 40
    color = _STATUS_COLOR.get(quest["status"], "text")
    for line in ui.wrap(quest["name"], "large", rw - 120):
        ui.text(line, "large", "gold", (rx, ry), shadow=True)
        ry += 30
    ui.text(tracker.status_label(quest), "medium", color, (right[0] + right[2] - 20, right[1] + 56), anchor="topright")
    meta = f"Niveau {quest['level']}  ·  {quest['zone'] or 'Zone inconnue'}"
    if quest.get("task"):
        meta += "  ·  Bonus / monde"
    if quest.get("freq") == 1:
        meta += "  ·  Quotidienne"
    elif quest.get("freq") == 2:
        meta += "  ·  Hebdomadaire"
    ui.text(meta, "small", "light_gray", (rx, ry + 2))
    ry += 30

    # suivi dans le journal de WoW
    tag_x = rx
    for label, active, tag_color in (("Quête suivie", quest.get("tracked"), C["green"]),
                                      ("Objectif suivi (flèche)", quest.get("focus"), C["gold"])):
        if active:
            tw = ui.fonts["small"].size(label)[0] + 22
            pygame.draw.rect(ui.screen, (28, 28, 34), (tag_x, ry, tw, 26), border_radius=13)
            pygame.draw.rect(ui.screen, tag_color, (tag_x, ry, tw, 26), 1, border_radius=13)
            ui.text(label, "small", tag_color, (tag_x + tw // 2, ry + 13), anchor="center")
            tag_x += tw + 8
    if not quest.get("tracked") and not quest.get("focus"):
        ui.text("Non suivie dans le journal de WoW", "small", "gray", (rx, ry + 4))
    ry += 42

    ui.text("Objectifs", "medium", "label", (rx, ry))
    done_count = sum(1 for o in quest["objectives"] if o["done"])
    if quest["objectives"]:
        ui.text(f"{done_count}/{len(quest['objectives'])} terminés", "small", "gray", (right[0] + right[2] - 20, ry + 3),
                anchor="topright")
    ry += 32
    if not quest["objectives"]:
        ui.text("Aucun objectif détaillé (quête à rendre ou sans compteur)", "small", "gray", (rx, ry))
        ry += 26
    for obj in quest["objectives"]:
        center = (rx + 9, ry + 10)
        if obj["done"]:
            pygame.draw.circle(ui.screen, C["green"], center, 8)
            pygame.draw.lines(ui.screen, (10, 30, 14), False, [(rx + 4, ry + 10), (rx + 8, ry + 14), (rx + 14, ry + 6)], 2)
        else:
            pygame.draw.circle(ui.screen, C["gray"], center, 8, 2)
        lines = ui.wrap(obj["text"], "small", rw - 40)
        for line in lines:
            ui.text(line, "small", "gray" if obj["done"] else "text", (rx + 28, ry))
            ry += 22
        if obj.get("need", 0) > 1:
            pct = 100 * min(obj.get("have", 0), obj["need"]) / obj["need"]
            ui.bar((rx + 28, ry + 2, min(380, rw - 120), 12), pct, C["green"] if obj["done"] else C["orange"], (36, 36, 42))
            ui.text(f"{obj.get('have', 0)}/{obj['need']}", "tiny", "light_gray", (rx + 28 + min(380, rw - 120) + 10, ry))
            ry += 20
        ry += 8

    # récompenses
    if quest.get("reward_xp") or quest.get("reward_money") or quest.get("rewards"):
        ry += 8
        ui.text("Récompenses", "medium", "label", (rx, ry))
        ry += 32
        parts = []
        if quest.get("reward_xp"):
            parts.append((f"{quest['reward_xp']:,} points d'expérience".replace(",", " "), C["xp"]))
        if quest.get("reward_money"):
            gold, silver, cop = Character.split_money(quest["reward_money"])
            parts.append((f"{gold} or {silver} arg {cop} cu" if gold else f"{silver} arg {cop} cu", C["gold"]))
        for reward in quest.get("rewards", []):
            parts.append((f"{reward['name']}" + (f" x{reward['count']}" if reward.get("count", 1) > 1 else ""),
                          QUALITY_COLORS.get(reward.get("quality", 1), (255, 255, 255))))
        for text, tcolor in parts:
            ui.text("•  " + text, "small", tcolor, (rx, ry))
            ry += 24

    ui.detail_buttons(rx, right[1] + right[3] - 52, quest_url(quest["id"]), f"Quête : {quest['name']}",
                      _quest_context(quest, tracker))


def _quest_context(quest, tracker):
    lines = [f"Quête World of Warcraft : « {quest['name']} » (niveau {quest['level']}, zone : {quest['zone'] or 'inconnue'}).",
             f"Statut : {tracker.status_label(quest)}."]
    if quest["objectives"]:
        lines.append("Objectifs :")
        for obj in quest["objectives"]:
            lines.append(f"- [{'x' if obj['done'] else ' '}] {obj['text']}")
    if quest.get("rewards"):
        lines.append("Récompenses : " + ", ".join(r["name"] for r in quest["rewards"]))
    lines.append(f"Lien Wowhead : {quest_url(quest['id'])}")
    return "\n".join(lines)


# ===========================================================================
#  Sacs
# ===========================================================================
def _item_grid(ui, items, area, key, empty_lines):
    """Grille d'objets (icône, nom, quantité) avec infobulle et lien Wowhead."""
    if not items:
        _message(ui, area, empty_lines)
        return
    cols = max(1, (area.w - 14) // 236)
    cell_w = (area.w - 14) // cols
    rows = (len(items) + cols - 1) // cols
    top = ui.scroll_begin(key, area, rows * 56)
    for i, item in enumerate(items):
        ry = top + (i // cols) * 56
        if ry + 56 < area.y or ry > area.bottom:
            continue
        cell = pygame.Rect(area.x + (i % cols) * cell_w, ry, cell_w - 6, 52)
        if _hover(cell):
            pygame.draw.rect(ui.screen, C["row_hover"], cell, border_radius=4)
        quality = QUALITY_COLORS.get(item.get("quality", 1), (255, 255, 255))
        name = item.get("name") or ui.icons.display_name(item["id"]) or f"Objet {item['id']}"
        quantity = item.get("quantity", item.get("count", 1))
        kind = item.get("type") or ""
        ui.icon("item", item["id"], (cell.x + 4, cell.y + 4, 44, 44), border=quality, fallback=name)
        ui.text(ui.fit(name, "small", cell.w - 120), "small", quality, (cell.x + 56, cell.y + 6))
        if kind:
            ui.text(ui.fit(kind, "tiny", cell.w - 120), "tiny", "gray", (cell.x + 56, cell.y + 28))
        ui.text(f"x{quantity}", "small", "text", (cell.right - 8, cell.y + 6), anchor="topright")
        ui.tip(cell, {"rows": [(name, quality, ""), *([(kind, C["light_gray"], "")] if kind else []),
                               (f"Quantité : {quantity}", C["text"], "")],
                      "border": quality, "footer": "Clic : ouvrir sur Wowhead"})
        ui.link(cell, item_url(item["id"]))
    ui.scroll_end()


def draw_bags(ui, ctx, rect):
    x, y, w, h = rect
    inv, data = ctx.inventory, ctx.data
    left = (x, y, 340, h)
    right = (x + 356, y, w - 356, h)
    view = ui.state["bag_view"]

    ui.frame(left, "Sacs et banques")
    for i, (key, label) in enumerate((("bags", "Sacs du personnage"), ("warband", "Banque de bataillon"),
                                      ("guild", "Banque de guilde"))):
        ui.pill((x + 16, y + 48 + i * 34, 308, 28), label, view == key, lambda k=key: ui.state.update(bag_view=k, bank_tab=0))

    py = y + 160
    if view == "bags":
        used = inv.slots_used if inv.slots_used is not None else inv.get_total_items()
        percent = 100 * used / inv.capacity if inv.capacity else 0
        ui.bar((x + 16, py, 308, 16), percent, C["red"] if percent >= 95 else C["green"], (28, 46, 32))
        ui.text(f"{used}/{inv.capacity} emplacements  ·  {inv.free_slots()} libres", "small", "light_gray", (x + 16, py + 22))
        ui.text(f"{len(inv.items)} objets différents  ·  {inv.get_total_items()} au total", "small", "gray", (x + 16, py + 44))
        ui.text("Filtrer par type", "small", "label", (x + 16, py + 78))
        selected = ui.state["bag_type"]
        ui.pill((x + 16, py + 102, 308, 28), f"Tout ({len(inv.items)})", selected is None, lambda: ui.state.update(bag_type=None))
        ty = py + 136
        for type_name, count in inv.count_by_type().items():
            if ty > y + h - 40:
                break
            ui.pill((x + 16, ty, 308, 28), f"{type_name} ({count})", selected == type_name,
                    lambda t=type_name: ui.state.update(bag_type=t))
            ty += 32
        ui.frame(right, "Contenu des sacs")
        query = ui.input_box((right[0] + 16, right[1] + 46, 340, 28), "bag_search", "Rechercher un objet…")
        items = [i for i in inv.items if (selected is None or i["type"] == selected) and query in i["name"].lower()]
        items.sort(key=lambda i: (i["type"], -i.get("quality", 1), i["name"]))
        area = pygame.Rect(right[0] + 10, right[1] + 86, right[2] - 20, h - 98)
        _item_grid(ui, items, area, "bags", ["Aucun objet" if not inv.items else "Aucun objet ne correspond"])
        return

    # --- banques (lues par l'addon quand elles sont ouvertes en jeu)
    if view == "warband":
        bank = data.warbandBank
        banks_tabs = bank["tabs"]
        title, money, updated = "Banque de bataillon", bank["money"], bank["updated"]
        never = ["Banque de bataillon jamais consultée", "Ouvrez-la une fois en jeu (chez le banquier),", "puis /ha save."]
    else:
        bank = data.guildBank
        banks_tabs = bank["tabs"]
        title = f"Banque de guilde — {bank['guild']}" if bank["guild"] else "Banque de guilde"
        money, updated = bank["money"], bank["updated"]
        never = ["Banque de guilde jamais consultée", "Ouvrez-la en jeu et parcourez ses onglets", "(chaque onglet est lu à l'ouverture), puis /ha save."]
    ui.text(f"Dernière consultation : {format_age(updated)}", "small", "gray", (x + 16, py))
    ui.text("Or :  " + Character.format_money(money), "small", "gold", (x + 16, py + 24))
    ui.text("Onglets", "small", "label", (x + 16, py + 62))
    for i, tab in enumerate(banks_tabs[:10]):
        ui.pill((x + 16, py + 86 + i * 32, 308, 28), f"{tab['name'] or 'Onglet ' + str(i + 1)} ({len(tab['items'])})",
                ui.state["bank_tab"] == i, lambda n=i: ui.state.update(bank_tab=n))
    ui.frame(right, title)
    area = pygame.Rect(right[0] + 10, right[1] + 86, right[2] - 20, h - 98)
    if not banks_tabs:
        _message(ui, (right[0], right[1], right[2], h), never)
        return
    tab = banks_tabs[min(ui.state["bank_tab"], len(banks_tabs) - 1)]
    query = ui.input_box((right[0] + 16, right[1] + 46, 340, 28), "bank_search", "Rechercher un objet…")
    items = [i for i in tab["items"] if query in (i.get("name") or "").lower()]
    _item_grid(ui, items, area, "bank_" + view, ["Onglet vide" if not tab["items"] else "Aucun objet ne correspond"])


# ===========================================================================
#  Métiers
# ===========================================================================
def _material_rows(ui, ctx, recipe):
    """[(texte gauche, couleur, texte droit)] : composants avec possédé/nécessaire."""
    inv, craft = ctx.inventory, ctx.craft
    rows = [(recipe["name"], C["gold"], ""), ("Composants :", C["label"], "")]
    if not recipe["materials"]:
        rows.append(("Aucun composant connu", C["gray"], ""))
    for m in recipe["materials"]:
        ids = m.get("item_ids") or ([m["item_id"]] if m.get("item_id") is not None else [])
        name = m.get("name") or (inv.name_of(ids[0]) if ids else "") or (ui.icons.display_name(ids[0]) if ids else "")
        if not name and ids:
            ui.icons.request(ids[0])
        have = craft._owned(m, inv)
        need = m.get("quantity", 1)
        rows.append((name or (f"Objet {ids[0]}" if ids else "?"), C["green"] if have >= need else C["red"],
                     f"{have}/{need}"))
    return rows


def _recipe_url(recipe):
    """Les recettes de métier ont pour identifiant l'identifiant de sort : lien Wowhead direct."""
    if recipe.get("url"):
        return recipe["url"]
    return spell_url(recipe["id"]) if recipe.get("source") == "game" and recipe.get("id") else ""


def draw_professions(ui, ctx, rect):
    x, y, w, h = rect
    craft, inv = ctx.craft, ctx.inventory
    left = (x, y, 440, h)
    right = (x + 456, y, w - 456, h)

    ui.frame(left, "Métiers")
    names = list(craft.professions.keys())
    if not names:
        _message(ui, left, ["Aucun métier détecté"])
    selected = ui.state["profession"]
    if selected not in craft.professions and names:
        selected = names[0]
        ui.state["profession"] = selected
    py = y + 48
    for name in names:
        info = craft.professions[name]
        card = pygame.Rect(x + 12, py, 416, 72)
        active = name == selected
        pygame.draw.rect(ui.screen, (44, 40, 30) if active else C["panel_alt"], card, border_radius=5)
        pygame.draw.rect(ui.screen, C["gold"] if active else C["frame"], card, 1, border_radius=5)
        ui.text(name, "medium", "text", (card.x + 12, card.y + 8))
        level, maxl = info["level"], info.get("max_level", 0)
        ui.bar((card.x + 12, card.y + 38, 290, 12), 100 * level / maxl if maxl else 0, C["green"], (28, 46, 32))
        ui.text(f"{level}/{maxl}" if maxl else str(level), "small", "light_gray", (card.right - 12, card.y + 34), anchor="topright")
        known = len(craft.recipes_for(name))
        ui.text(f"{known} recette(s) importée(s)" if known else "Recettes non importées", "tiny",
                "gray" if not known else "label", (card.x + 12, card.y + 54))
        ui.click(card, lambda n=name: ui.state.update(profession=n))
        py += 80

    ui.frame(right, f"Recettes — {selected}" if selected else "Recettes")
    if not selected:
        return
    recipes = craft.recipes_for(selected)
    ui.pill((right[0] + 16, right[1] + 46, 190, 28), "Fabricables seulement", ui.state["craftable_only"],
            lambda: ui.state.update(craftable_only=not ui.state["craftable_only"]))
    query = ui.input_box((right[0] + 220, right[1] + 46, 320, 28), "recipe_search", "Rechercher une recette…")
    ui.text("d'après le contenu de vos sacs", "tiny", "gray", (right[0] + right[2] - 16, right[1] + 54), anchor="topright")

    area = pygame.Rect(right[0] + 10, right[1] + 86, right[2] - 20, h - 98)
    if not recipes:
        _message(ui, area, ["Recettes non importées pour ce métier",
                            "Ouvrez la fenêtre du métier en jeu : elles sont lues automatiquement,",
                            "puis tapez /ha save pour les envoyer à l'application."])
        return
    rows = []
    for recipe in recipes:
        count = craft.max_crafts(recipe, inv) if recipe["materials"] else 0
        if query and query not in recipe["name"].lower():
            continue
        if ui.state["craftable_only"] and count < 1:
            continue
        rows.append((recipe, count))
    rows.sort(key=lambda r: (-(r[1] > 0), r[0]["name"]))
    if not rows:
        _message(ui, area, ["Aucune recette ne correspond"])
        return
    top = ui.scroll_begin("recipes", area, len(rows) * 38)
    for i, (recipe, count) in enumerate(rows):
        ry = top + i * 38
        if ry + 38 < area.y or ry > area.bottom:
            continue
        row = pygame.Rect(area.x + 4, ry, area.w - 20, 34)
        if _hover(row):
            pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=4)
        ui.text(ui.fit(recipe["name"], "small", row.w - 140), "small", "green" if count else "text", (row.x + 10, ry + 8))
        ui.text(f"x{count}" if count else "—", "small", "green" if count else "gray", (row.right - 10, ry + 8), anchor="topright")
        url = _recipe_url(recipe)
        ui.tip(row, lambda r=recipe, u=url: {"rows": _material_rows(ui, ctx, r), "border": C["header_border"],
                                              "footer": "Clic : ouvrir sur Wowhead" if u else ""})
        ui.link(row, url)
    ui.scroll_end()


# ===========================================================================
#  Onglets déplacés dans tabs_data.py et tabs_collections.py
# ===========================================================================
from tabs_collections import draw_collections  # noqa: E402
from tabs_data import draw_achievements, draw_activity, draw_instances, draw_reputations  # noqa: E402
from tabs_market import draw_market  # noqa: E402

DRAWERS = [None, draw_talents, draw_quest_journal, draw_bags, draw_professions, draw_achievements,
           draw_collections, draw_activity, draw_reputations, draw_instances, draw_market]
