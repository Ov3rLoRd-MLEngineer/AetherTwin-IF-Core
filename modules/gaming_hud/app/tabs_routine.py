"""
Onglet « Semaine » : routine de la semaine (voir routine.py). Ce qu'il reste à faire avant la remise à zéro pour le
personnage joué, mes tâches à cocher, les autres personnages, et un plan demandé à Hermes selon le temps de jeu.
"""
import time

import pygame

import routine
from theme import C
from tabutil import message

GROUP_ORDER = ("Grande Chambre forte", "Monnaies de la semaine", "Quêtes hebdomadaires", "Quêtes journalières",
               "Mythique+", "Verrouillages")


def store(ui):
    st = getattr(ui, "routine", None)
    if st is None:
        st = ui.routine = routine.RoutineStore()
    return st


def _check(ui, rect, done, fn=None):
    """Case à cocher : vert coché, vide, ou tiret (sans objet)."""
    box = pygame.Rect(rect)
    pygame.draw.rect(ui.screen, (26, 26, 30), box, border_radius=3)
    pygame.draw.rect(ui.screen, C["green"] if done else C["frame"], box, 1, border_radius=3)
    if done is True:
        pygame.draw.lines(ui.screen, C["green"], False, [(box.x + 3, box.centery), (box.x + 7, box.bottom - 4),
                                                         (box.right - 3, box.y + 3)], 2)
    elif done is None:
        pygame.draw.line(ui.screen, C["gray"], (box.x + 4, box.centery), (box.right - 4, box.centery), 2)
    if fn:
        ui.click(box.inflate(6, 6), fn)


def _ask_plan(ui, st, key, minutes):
    prompt = routine.plan_prompt(st, key, minutes)
    chat = getattr(ui, "chat", None)
    if chat is not None and chat.uses_hermes() and "Hermes" in ui.TABS:
        import chatview
        if chatview.send_from(ui, chat, "hermes_msg", prompt):
            ui._switch_tab(ui.TABS.index("Hermes"))
        return
    ui.ask_assistant("Ma semaine", prompt, suggestions=["Que faire en priorité avant la remise à zéro ?"])


def _draw_current(ui, rect, st, key, summary, now):
    x, y, w, h = rect
    ui.frame(rect, f"Cette semaine — {summary.get('name', '?')}" if summary else "Cette semaine")
    if not summary:
        message(ui, rect, ["Pas encore de données pour ce personnage", "(/reload ou /ha save en jeu)"])
        return
    daily, weekly = routine.next_resets(summary, now)
    ui.text(f"Remise à zéro hebdomadaire dans {routine.format_delay(weekly - now)}  ·  quotidienne dans "
            f"{routine.format_delay(daily - now)}", "small", "gold", (x + 16, y + 44))
    if routine.outdated(summary, now):
        ui.text("Données d'avant la remise à zéro : connectez ce personnage pour les mettre à jour.", "small",
                "orange", (x + 16, y + 68))
    items = routine.checklist(summary, now)
    groups = {}
    for item in items:
        groups.setdefault(item["group"], []).append(item)
    order = [g for g in GROUP_ORDER if g in groups] + [g for g in groups if g not in GROUP_ORDER]
    area = pygame.Rect(x + 12, y + 94, w - 24, h - 106)
    content = sum(34 + 26 * len(groups[g]) for g in order) + 8
    top = ui.scroll_begin("routine_items", area, content)
    ry = top
    for group in order:
        if area.y - 30 < ry < area.bottom:
            todo = sum(1 for i in groups[group] if i["done"] is False)
            done = any(i["done"] is True for i in groups[group])
            ui.text(group, "medium", "gold", (area.x + 4, ry + 4), shadow=True)
            ui.text(f"{todo} à faire" if todo else ("fait" if done else ""), "tiny", "orange" if todo else "green",
                    (area.right - 18, ry + 10), anchor="topright")
        ry += 34
        for item in groups[group]:
            if area.y - 24 < ry < area.bottom:
                _check(ui, (area.x + 8, ry + 3, 16, 16), item["done"])
                label_w = area.w - 60 - (260 if item["detail"] else 0)
                ui.text(ui.fit(item["label"], "small", label_w), "small", "gray" if item["done"] else "text",
                        (area.x + 34, ry + 1))
                if item["detail"]:
                    ui.text(ui.fit(item["detail"], "tiny", 250), "tiny", "gray", (area.right - 18, ry + 4),
                            anchor="topright")
            ry += 26
    ui.scroll_end()
    if not items:
        message(ui, area, ["Rien de suivi automatiquement pour l'instant",
                           "(chambre forte dès le niveau maximum ; quêtes hebdomadaires dans le journal)"])


def _draw_tasks(ui, rect, st, key, now):
    x, y, w, h = rect
    ui.frame(rect, "Mes tâches")
    state = ui.state
    period = state.setdefault("routine_period", "weekly")
    iy = y + 44

    def add():
        if st.add_task(ui.inputs.get("routine_task", ""), state["routine_period"]):
            ui.inputs["routine_task"] = ""

    ui.on_submit["routine_task"] = add
    ui.input_box((x + 12, iy, w - 24 - 236, 30), "routine_task", "Proie, commandes d'artisanat, logis…")
    px = x + w - 12 - 230
    for value, label in routine.PERIODS.items():
        ui.pill((px, iy, 76, 30), label, period == value, lambda v=value: state.update(routine_period=v), font="tiny")
        px += 80
    ui.pill((px, iy, 70, 30), "Ajouter", True, add, font="tiny")
    area = pygame.Rect(x + 12, iy + 40, w - 24, h - (iy + 40 - y) - 10)
    top = ui.scroll_begin("routine_tasks", area, 26 * len(st.tasks) + 4)
    ry = top
    for task in st.tasks:
        if area.y - 24 < ry < area.bottom:
            done = st.is_done(key, task, now)
            _check(ui, (area.x + 4, ry + 3, 16, 16), done, lambda t=task["id"]: st.toggle(key, t))
            ui.text(ui.fit(task["text"], "small", area.w - 170), "small", "gray" if done else "text", (area.x + 30, ry + 1))
            ui.text(routine.PERIODS[task["period"]], "tiny", "label", (area.right - 60, ry + 4), anchor="topright")
            ui.pill((area.right - 52, ry, 34, 22), "×", False, lambda t=task["id"]: st.remove_task(t), font="tiny")
        ry += 26
    ui.scroll_end()
    if not st.tasks:
        message(ui, area, ["Ce que l'addon ne voit pas : ajoutez-le ici.", "Décoché tout seul à la remise à zéro."])


def _draw_others(ui, rect, st, key, now):
    x, y, w, h = rect
    others = st.others(key)
    ui.frame(rect, f"Autres personnages ({len(others)})")
    area = pygame.Rect(x + 12, y + 44, w - 24, h - 56)
    if not others:
        message(ui, area, ["Connectez vos autres personnages une fois :", "WoW Assistant garde leur semaine ici."])
        return
    top = ui.scroll_begin("routine_alts", area, 52 * len(others) + 4)
    ry = top
    for s in others:
        if area.y - 50 < ry < area.bottom:
            card = pygame.Rect(area.x, ry, area.w - 16, 46)
            pygame.draw.rect(ui.screen, C["panel_alt"], card, border_radius=6)
            old = routine.outdated(s, now)
            vault = 0 if old else sum(r["unlocked"] for r in s.get("vault") or [])
            ui.text(ui.fit(f"{s['name']} · niv. {s.get('level', 0)} · ilvl {s.get('ilvl', 0)}", "small", card.w - 220),
                    "small", "text", (card.x + 10, card.y + 4))
            ui.text(ui.fit(f"{s.get('realm', '')} · vu le {time.strftime('%d/%m %H:%M', time.localtime(s.get('updated', 0)))}",
                           "tiny", card.w - 220), "tiny", "gray", (card.x + 10, card.y + 26))
            rewards = s.get("vaultRewards") and not old
            ui.text("Récompense à récupérer" if rewards else f"Chambre forte {vault}/9", "tiny",
                    "green" if rewards else ("gray" if old else "light_gray"), (card.right - 10, card.y + 6),
                    anchor="topright")
            if old:
                ui.text("nouvelle semaine", "tiny", "orange", (card.right - 10, card.y + 26), anchor="topright")
        ry += 52
    ui.scroll_end()


def draw_week_widget(ui, ctx, rect):
    """Widget d'overlay : ce qu'il reste à faire cette semaine (automatique + mes tâches)."""
    x, y, w, h = rect
    st = store(ui)
    st.reload_if_changed()
    now = time.time()
    key = ctx.character.key
    summary = st.characters.get(key)
    if not summary:
        ui.text("Pas encore de données (/reload en jeu)", "small", "gray", (x, y))
        return
    _daily, weekly = routine.next_resets(summary, now)
    ui.text(f"Remise à zéro dans {routine.format_delay(weekly - now)}", "tiny", "gold", (x, y))
    rows = [(i["label"], i["done"]) for i in routine.checklist(summary, now) if i["done"] is False]
    rows += [(t["text"], False) for t in st.tasks if not st.is_done(key, t, now)]
    if not rows:
        ui.text("Tout est fait cette semaine.", "small", "green", (x, y + 22))
        return
    top = ui.scroll_begin("w_week", pygame.Rect(x, y + 22, w, h - 22), 22 * len(rows))
    ry = top
    for label, done in rows:
        if y < ry < y + h:
            _check(ui, (x, ry + 3, 14, 14), done)
            ui.text(ui.fit(label, "small", w - 26), "small", "text", (x + 22, ry))
        ry += 22
    ui.scroll_end()


def draw_week(ui, ctx, rect):
    x, y, w, h = rect
    st = store(ui)
    st.reload_if_changed()
    now = time.time()
    key = ctx.character.key
    summary = st.characters.get(key)
    left_w = int(w * 0.56)
    _draw_current(ui, (x, y, left_w, h), st, key, summary, now)
    rx, rw = x + left_w + 12, w - left_w - 12
    plan_h = 84
    tasks_h = (h - plan_h - 24) // 2
    _draw_tasks(ui, (rx, y, rw, tasks_h), st, key, now)
    _draw_others(ui, (rx, y + tasks_h + 12, rw, h - tasks_h - plan_h - 24), st, key, now)
    py = y + h - plan_h
    ui.frame((rx, py, rw, plan_h), "Plan avec Hermes")
    px = rx + 16
    for minutes, label in ((30, "J'ai 30 min"), (60, "J'ai 1 h"), (120, "J'ai 2 h")):
        ui.pill((px, py + 42, 130, 30), label, False, lambda m=minutes: _ask_plan(ui, st, key, m), font="tiny")
        px += 138
