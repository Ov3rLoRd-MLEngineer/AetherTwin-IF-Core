"""
Onglet « Bilans » : résumé de chaque boss et de chaque clé Mythique+ (journal de combat, voir combat_report.py),
avec analyse par Hermes.
"""
import time

import pygame

import combat_report
from theme import C
from tabutil import message

COLUMNS = (("Joueur", 0), ("DPS", 190), ("HPS", 270), ("Subis", 350), ("Interr.", 450), ("Dissip.", 520),
           ("Morts", 590))


def _short_num(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} M"
    if n >= 10_000:
        return f"{n / 1000:.0f} k"
    return str(n)


def _analyse(ui, report):
    prompt = combat_report.ANALYSIS_PROMPT + combat_report.describe(report)
    chat = getattr(ui, "chat", None)
    if chat is not None and chat.uses_hermes() and "Hermes" in ui.TABS:
        import chatview
        if chatview.send_from(ui, chat, "hermes_msg", prompt):
            ui._switch_tab(ui.TABS.index("Hermes"))
        return
    ui.ask_assistant("Bilan de combat", prompt, suggestions=["Pourquoi suis-je mort ?", "Comment améliorer mon DPS ?"])


def _copy(ui, report):
    try:
        import clipboard
        clipboard.set_text(combat_report.describe(report))
        ui.notify("Bilan copié.")
    except Exception as e:          # noqa: BLE001
        ui.notify(f"Copie impossible : {e}")


def _draw_detail(ui, rect, report):
    x, y, w, h = rect
    title = report["name"] + (f" +{report['keyLevel']}" if report.get("keyLevel") else "")
    ui.frame(rect, title)
    when = time.strftime("%d/%m/%Y %H:%M", time.localtime(report.get("start", 0)))
    ui.text(f"{'Boss' if report['kind'] == 'boss' else 'Clé Mythique+'} · {report.get('difficulty', '')} · {when} · "
            f"{combat_report.format_duration(report['duration'])}", "small", "light_gray", (x + 16, y + 44))
    ui.text("Réussi" if report["success"] else "Échec / abandon", "small", "green" if report["success"] else "red",
            (x + w - 16, y + 44), anchor="topright")
    ty = y + 76
    for label, cx in COLUMNS:
        ui.text(label, "tiny", "label", (x + 16 + cx, ty))
    ty += 20
    players = report["players"][:10]
    for p in players:
        mine = p["name"] == report.get("me")
        if mine:
            pygame.draw.rect(ui.screen, (40, 36, 22), (x + 10, ty - 2, w - 20, 22), border_radius=4)
        color = "gold" if mine else "text"
        ui.text(ui.fit(p["name"], "small", 180), "small", color, (x + 16, ty))
        for value, (_label, cx) in zip((p["dps"], p["hps"], p["taken"], p["interrupts"], p["dispels"], p["deaths"]),
                                       COLUMNS[1:]):
            ui.text(_short_num(value), "small", "red" if _label == "Morts" and value else color, (x + 16 + cx, ty))
        ty += 22
    ty += 10
    col_w = (w - 48) // 2
    ui.text("Morts", "medium", "gold", (x + 16, ty), shadow=True)
    ui.text("Ce qui m'a fait le plus mal", "medium", "gold", (x + 32 + col_w, ty), shadow=True)
    ty += 30
    bottom = y + h - 56
    dy = ty
    if not report["deaths"]:
        ui.text("Aucune mort.", "small", "green", (x + 16, dy))
    for d in report["deaths"]:
        if dy > bottom - 40:
            break
        ui.text(ui.fit(f"{d['name']} à {combat_report.format_duration(d['at'])}", "small", col_w), "small", "red",
                (x + 16, dy))
        dy += 20
        for hit in d["hits"][-2:]:
            ui.text(ui.fit(f"   {hit['spell']} ({hit['from']}) : {_short_num(hit['amount'])}", "tiny", col_w), "tiny",
                    "light_gray", (x + 16, dy))
            dy += 18
    hy = ty
    for hit in report.get("hurtMe") or []:
        if hy > bottom - 20:
            break
        ui.text(ui.fit(hit["spell"], "small", col_w - 80), "small", "text", (x + 32 + col_w, hy))
        ui.text(_short_num(hit["amount"]), "small", "orange", (x + w - 16, hy), anchor="topright")
        hy += 22
    if report.get("bosses"):
        bosses = " · ".join(f"{b['name']} {'✓' if b['success'] else '✗'}" for b in report["bosses"])
        ui.text(ui.fit("Boss : " + bosses, "small", w - 32), "small", "light_gray", (x + 16, bottom - 4))
    ui.pill((x + w - 16 - 220, y + h - 44, 220, 30), "Analyser avec Hermes", True, lambda: _analyse(ui, report))
    ui.pill((x + w - 16 - 220 - 160, y + h - 44, 150, 30), "Copier le bilan", False, lambda: _copy(ui, report))


def draw_reports(ui, ctx, rect):
    x, y, w, h = rect
    builder = getattr(ui, "reports", None)
    left = (x, y, 460, h)
    right = (x + 476, y, w - 476, h)
    reports = builder.latest(40) if builder is not None else []
    ui.frame(left, f"Bilans de combat ({len(reports)})")
    if not reports:
        message(ui, left, ["Pas encore de boss ni de clé terminés.", "En jeu : /ha combatlog on",
                           "(journal de combat du jeu)."])
        ui.frame(right, "Bilan")
        message(ui, right, ["Chaque boss et chaque clé Mythique+ donnent ici un bilan, analysable par Hermes.",
                            "Analyse après coup, hors du jeu : aucun addon ne lit le combat en direct.",
                            "La « journalisation avancée » du jeu n'est pas obligatoire."])
        return
    state = ui.state
    selected = state.get("report_selected", 0)
    selected = min(selected, len(reports) - 1)
    area = pygame.Rect(x + 12, y + 44, 460 - 24, h - 56)
    top = ui.scroll_begin("reports_list", area, 64 * len(reports) + 4)
    ry = top
    for i, r in enumerate(reports):
        if area.y - 60 < ry < area.bottom:
            card = pygame.Rect(area.x, ry, area.w - 16, 58)
            active = i == selected
            pygame.draw.rect(ui.screen, (34, 32, 26) if active else C["panel_alt"], card, border_radius=6)
            pygame.draw.rect(ui.screen, C["gold"] if active else C["frame"], card, 1, border_radius=6)
            name = r["name"] + (f" +{r['keyLevel']}" if r.get("keyLevel") and r["kind"] != "boss" else "")
            ui.text(ui.fit(name, "small", card.w - 110), "small", "text", (card.x + 10, card.y + 6))
            ui.text("réussi" if r["success"] else "échec", "tiny", "green" if r["success"] else "red",
                    (card.right - 10, card.y + 8), anchor="topright")
            me = next((p for p in r["players"] if p["name"] == r.get("me")), None)
            info = (f"{time.strftime('%d/%m %H:%M', time.localtime(r.get('start', 0)))} · "
                    f"{combat_report.format_duration(r['duration'])}"
                    + (f" · {_short_num(me['dps'])} DPS" if me else "") + (f" · {len(r['deaths'])} mort(s)"
                                                                         if r["deaths"] else ""))
            ui.text(ui.fit(info, "tiny", card.w - 20), "tiny", "gray", (card.x + 10, card.y + 32))
            ui.click(card, lambda i=i: state.update(report_selected=i))
        ry += 64
    ui.scroll_end()
    _draw_detail(ui, right, reports[selected])
