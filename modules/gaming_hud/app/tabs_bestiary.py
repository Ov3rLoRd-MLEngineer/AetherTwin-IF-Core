"""
Onglet « Bestiaire » : créatures rencontrées et tuées (journal de combat + addon 1.9), avec leur image Battle.net,
leurs aptitudes, leur butin, l'or moyen, une note personnelle, Wowhead et Hermes.
"""
import pygame

import model3d

from character import Character
from theme import C, QUALITY_COLORS
from tabutil import format_age, hover, message
from wowhead import item_url, npc_url, spell_url

FILTERS = (("all", "Toutes"), ("killed", "Tuées"), ("loot", "Avec butin"))
SORTS = (("kills", "Plus tuées"), ("recent", "Récentes"), ("name", "Nom"))
ROW_H = 52


def _entries(ui, bestiary):
    """Fiches fusionnées, recalculées seulement quand le bestiaire change."""
    cache = ui.state.get("bestiary_cache")
    key = (bestiary.version, id(bestiary.addon))
    if not cache or cache[0] != key:
        cache = ui.state["bestiary_cache"] = (key, bestiary.entries())
    return cache[1]


def _level(e):
    if not e["levelMin"]:
        return "niveau ?"
    if e["levelMax"] > e["levelMin"]:
        return f"niveau {e['levelMin']}-{e['levelMax']}"
    return f"niveau {e['levelMin']}"


def draw_bestiary(ui, ctx, rect):
    x, y, w, h = rect
    bestiary = getattr(ui, "bestiary", None)
    left = (x, y, 560, h)
    right = (x + 576, y, w - 576, h)
    ui.frame(left, "Bestiaire")
    if bestiary is None:
        message(ui, left, ["Bestiaire indisponible"])
        return
    state = ui.state
    state.setdefault("bestiary_filter", "all")
    state.setdefault("bestiary_sort", "kills")
    entries = _entries(ui, bestiary)

    px = x + 16
    for value, label in FILTERS:
        pw = ui.width(label, "small") + 26
        ui.pill((px, y + 44, pw, 28), label, state["bestiary_filter"] == value,
                lambda v=value: state.update(bestiary_filter=v))
        px += pw + 6
    px = x + 16
    ui.text("Trier :", "tiny", "gray", (px, y + 88))
    px += 52
    for value, label in SORTS:
        pw = ui.width(label, "tiny") + 20
        ui.pill((px, y + 82, pw, 24), label, state["bestiary_sort"] == value,
                lambda v=value: state.update(bestiary_sort=v), font="tiny")
        px += pw + 4
    query = ui.input_box((x + 16, y + 116, 340, 28), "bestiary_search", "Rechercher une créature…")
    killed = sum(1 for e in entries if e["kills"])
    ui.text(f"{len(entries)} créatures  ·  {killed} tuées", "small", "gray", (x + 544, y + 48), anchor="topright")

    shown = [e for e in entries if query in e["name"].lower()
             and (state["bestiary_filter"] != "killed" or e["kills"])
             and (state["bestiary_filter"] != "loot" or e["loots"])]
    sort = state["bestiary_sort"]
    if sort == "kills":
        shown.sort(key=lambda e: (-e["kills"], e["name"]))
    elif sort == "recent":
        shown.sort(key=lambda e: (-e["seen"], e["name"]))
    else:
        shown.sort(key=lambda e: e["name"])

    area = pygame.Rect(x + 10, y + 154, 540, h - 190)
    status = ("lecture du journal de combat…" if bestiary.busy else bestiary.error
              or "Journal de combat lu automatiquement (toutes les 5 s)")
    ui.text(ui.fit(status, "tiny", 530), "tiny", "orange" if bestiary.error else "gray", (x + 16, y + h - 26))
    if not entries:
        message(ui, area, ["Bestiaire vide pour l'instant.",
                           "En jeu : /ha combatlog on (créatures tuées, aptitudes, PV),",
                           "puis ciblez, survolez et fouillez les créatures (addon 1.9).",
                           "Pensez à /ha save (ou /reload) pour envoyer le butin."])
        right_frame_empty(ui, right)
        return
    selected = state.get("bestiary_sel")
    if not any(e["id"] == selected for e in shown) and shown:
        selected = state["bestiary_sel"] = shown[0]["id"]
    top = ui.scroll_begin("bestiary", area, len(shown) * ROW_H)
    for i, e in enumerate(shown):
        ry = top + i * ROW_H
        if ry + ROW_H < area.y or ry > area.bottom:
            continue
        row = pygame.Rect(area.x, ry, area.w - 16, ROW_H - 4)
        if e["id"] == selected:
            pygame.draw.rect(ui.screen, (44, 40, 30), row, border_radius=5)
            pygame.draw.rect(ui.screen, C["gold"], row, 1, border_radius=5)
        elif hover(row):
            pygame.draw.rect(ui.screen, C["row_hover"], row, border_radius=5)
        name_color = "orange" if e["rank"] in ("Élite", "Élite rare", "Boss") else "text"
        ui.text(ui.fit(e["name"], "small", row.w - 150), "small", name_color, (row.x + 10, row.y + 4))
        sub = "  ·  ".join(t for t in (_level(e), e["rank"], e["type"]) if t)
        ui.text(ui.fit(sub, "tiny", row.w - 150), "tiny", "gray", (row.x + 10, row.y + 24))
        ui.text(f"{e['kills']} tuée(s)" if e["kills"] else "rencontrée", "small",
                "green" if e["kills"] else "gray", (row.right - 10, row.y + 12), anchor="topright")
        ui.click(row, lambda cid=e["id"]: state.update(bestiary_sel=cid))
    ui.scroll_end()
    if not shown:
        message(ui, area, ["Aucune créature ne correspond"])
        right_frame_empty(ui, right)
        return
    entry = next(e for e in shown if e["id"] == selected)
    _detail(ui, right, entry, bestiary)


def right_frame_empty(ui, rect):
    ui.frame(rect, "Fiche")


def _detail(ui, rect, e, bestiary):
    x, y, w, h = rect
    ui.frame(rect, "Fiche")
    box = (x + 16, y + 46, 300, 300)
    if ui.media is not None and ui.media.available():
        key = f"npc:{e['id']}"
        ui.media.request(key, lambda cid=e["id"]: ui.media.bnet.creature_image(cid))
        ui.media_view(box, key, "Image de la créature", (50, 40, 40), "object")
        ui.view3d_box(box, key,
                      lambda cid=e["id"], n=e["name"]: model3d.creature_model(ui.media.bnet, cid, n))
    else:
        ui.model_placeholder(box, "Image de la créature", (50, 40, 40), "object",
                             note="image : API Battle.net (Paramètres > Jeu)")

    ix, iy, iw = x + 332, y + 48, w - 348
    ui.text(ui.fit(e["name"], "large", iw), "large", "orange" if e["rank"] else "gold", (ix, iy), shadow=True)
    iy += 40
    facts = [
        ("Niveau", _level(e).replace("niveau ", "") if e["levelMin"] else "inconnu"),
        ("Rang", e["rank"] or "normal"),
        ("Type", " / ".join(t for t in (e["type"], e["family"]) if t) or "inconnu"),
        ("Points de vie", f"{e['hp']:,}".replace(",", " ") if e["hp"] else "inconnus"),
        (e["powerName"] or "Ressource", f"{e['power']:,}".replace(",", " ") if e["power"] else "aucune connue"),
        ("Tuée", f"{e['kills']} fois" if e["kills"] else "jamais (d'après le journal de combat)"),
        ("Lieu", ", ".join(e["zones"][:3]) or (f"carte n° {e['maps'][0]}" if e["maps"] else "inconnu")),
        ("Corps fouillés", f"{e['loots']}" + (f"  ·  or moyen : {Character.format_money(int(e['avgMoney']))}"
                                              if e["loots"] else "")),
        ("Vue", format_age(e["seen"])),
    ]
    for label, value in facts:
        ui.text(label, "small", "label", (ix, iy))
        ui.text(ui.fit(value, "small", iw - 150), "small", "text", (ix + 150, iy))
        iy += 25

    # aptitudes et butin, côte à côte sous l'image
    ty = y + 362
    bottom = y + h - 128
    col_w = (w - 48) // 2
    _spells(ui, (x + 16, ty, col_w, bottom - ty), e)
    _loot(ui, (x + 32 + col_w, ty, col_w, bottom - ty), e)

    # note personnelle
    if ui.state.get("bestiary_note_for") != e["id"]:
        ui.state["bestiary_note_for"] = e["id"]
        ui.inputs["bestiary_note"] = e["note"]
    ny = y + h - 112
    ui.text("Note", "small", "label", (x + 16, ny + 6))
    ui.input_box((x + 70, ny, w - 70 - 16 - 186, 30), "bestiary_note", "Une note sur cette créature…")
    ui.pill((x + w - 196, ny, 180, 30), "Enregistrer la note", False,
            lambda cid=e["id"]: (bestiary.set_note(cid, ui.inputs.get("bestiary_note", "")),
                                 ui.notify("Note enregistrée")))
    url = npc_url(e["id"])
    ui.detail_buttons(x + 16, y + h - 50, url, f"Créature : {e['name']}", _context(e, url))


def _spells(ui, rect, e):
    x, y, w, h = rect
    ui.text("Aptitudes (journal de combat)", "small", "gold", (x, y))
    if not e["spells"]:
        ui.text("Aucune vue pour l'instant", "small", "gray", (x, y + 26))
        return
    area = pygame.Rect(x, y + 26, w, h - 26)
    top = ui.scroll_begin("bestiary_spells", area, len(e["spells"]) * 24)
    for i, s in enumerate(e["spells"]):
        row = pygame.Rect(x, top + i * 24, w - 14, 22)
        ui.icon("spell", s["id"], (row.x, row.y, 20, 20), fallback=s["name"])
        ui.text(ui.fit(s["name"] or f"Sort {s['id']}", "small", w - 110), "small",
                "gold" if hover(row) else "text", (row.x + 28, row.y))
        ui.text(f"×{s['count']}", "tiny", "gray", (row.right, row.y + 3), anchor="topright")
        ui.tip(row, {"rows": [(s["name"], C["gold"], ""), (f"Vue {s['count']} fois", C["light_gray"], "")],
                     "footer": "Clic : ouvrir sur Wowhead"})
        ui.link(row, spell_url(s["id"]))
    ui.scroll_end()


def _loot(ui, rect, e):
    x, y, w, h = rect
    ui.text("Butin" + (f" ({e['loots']} corps)" if e["loots"] else ""), "small", "gold", (x, y))
    if not e["loot"]:
        ui.text("Aucun butin relevé" if not e["loots"] else "Seulement de l'or", "small", "gray", (x, y + 26))
        return
    area = pygame.Rect(x, y + 26, w, h - 26)
    top = ui.scroll_begin("bestiary_loot", area, len(e["loot"]) * 26)
    for i, it in enumerate(e["loot"]):
        row = pygame.Rect(x, top + i * 26, w - 14, 24)
        quality = QUALITY_COLORS.get(it["quality"], C["text"])
        ui.icon("item", it["id"], (row.x, row.y, 22, 22), border=quality, fallback=it["name"])
        ui.text(ui.fit(it["name"] or f"Objet {it['id']}", "small", w - 120), "small", quality, (row.x + 30, row.y + 1))
        ui.text(f"{it['rate'] * 100:.0f} %", "tiny", "light_gray", (row.right, row.y + 4), anchor="topright")
        ui.tip(row, {"rows": [(it["name"], quality, ""),
                              (f"Obtenu sur {it['times']} corps sur {e['loots']} ({it['rate'] * 100:.0f} %)",
                               C["light_gray"], ""), (f"Quantité totale : {it['count']}", C["gray"], "")],
                     "border": quality, "footer": "Clic : ouvrir sur Wowhead"})
        ui.link(row, item_url(it["id"]))
    ui.scroll_end()


def _context(e, url):
    lines = [f"Créature World of Warcraft : « {e['name']} » ({_level(e)}"
             + (f", {e['rank']}" if e["rank"] else "") + (f", {e['type']}" if e["type"] else "") + ")."]
    if e["zones"]:
        lines.append("Rencontrée à : " + ", ".join(e["zones"][:5]))
    if e["hp"]:
        lines.append(f"Points de vie max. : {e['hp']}")
    lines.append(f"Tuée {e['kills']} fois par le joueur.")
    if e["spells"]:
        lines.append("Aptitudes vues : " + ", ".join(s["name"] for s in e["spells"][:12]))
    if e["loot"]:
        lines.append(f"Butin sur {e['loots']} corps : "
                     + ", ".join(f"{i['name']} ({i['rate'] * 100:.0f} %)" for i in e["loot"][:12]))
        lines.append(f"Or moyen par corps : {Character.format_money(int(e['avgMoney']))}")
    if e["note"]:
        lines.append(f"Note du joueur : {e['note']}")
    lines.append(f"Lien Wowhead : {url}")
    return "\n".join(lines)
