"""
Widgets fournis avec l'appli (versions compactes des panneaux) et conversation avec l'assistant.
Chaque fonction reçoit (ui, ctx, rect) ; rect est la zone de contenu du widget.
Aucun widget n'exécute de commande système ni n'accède aux fichiers de l'appli : ils dessinent des données.
"""
import json
import os
import time

import pygame

from character import EQUIPMENT_LAYOUT, Character, format_duration
from tabutil import format_remaining
from theme import C, QUALITY_COLORS
from widgets import WidgetSpec


# ===========================================================================
#  Personnage, équipement, session
# ===========================================================================
def draw_character(ui, ctx, rect):
    c = ctx.character
    x, y, w, h = rect
    ui.text(ui.fit(c.display_title, "medium", w), "medium", c.class_color, (x, y), shadow=True)
    who = " ".join(p for p in (c.class_name, c.spec) if p)
    ui.text(ui.fit(f"Niveau {c.level} · {who}", "small", w), "small", "text", (x, y + 24))
    ui.bar((x, y + 50, w, 12), c.xp_percent, C["xp"], C["xp_back"])
    ui.text(f"{c.xp_percent:.0f} %" + (f"  ·  repos {c.rested_xp:,}".replace(",", " ") if c.rested_xp else ""), "tiny",
            "light_gray", (x, y + 64))
    gold = Character.split_money(c.money)[0]
    ui.text(f"{gold:,} or".replace(",", " "), "small", "gold", (x, y + 84))
    ui.text(f"Niv. d'objet {c.ilvl:g}", "small", "text", (x + w, y + 84), anchor="topright")
    ui.text(ui.fit("Zone : " + (c.location or "—"), "small", w), "small", "light_gray", (x, y + 108))
    if c.played_total:
        ui.text("Temps de jeu : " + format_duration(c.played_total), "tiny", "gray", (x, y + 132))


def draw_equipment(ui, ctx, rect):
    c = ctx.character
    x, y, w, h = rect
    size = max(28, min(46, (h - 20) // 9 - 4, (w - 12) // 2 - 4))
    pitch = size + 4
    for row, (slot, label) in enumerate(EQUIPMENT_LAYOUT["left"]):
        ui._draw_slot((x, y + row * pitch), slot, label, c.equipment.get(slot), size)
    for row, (slot, label) in enumerate(EQUIPMENT_LAYOUT["right"]):
        ui._draw_slot((x + w - size, y + row * pitch), slot, label, c.equipment.get(slot), size)
    mid_x = x + size + 10
    mid_w = w - 2 * size - 20
    if mid_w > 60:
        ui.text(f"{c.ilvl:g}", "large", "text", (mid_x + mid_w // 2, y + 8), anchor="midtop", shadow=True)
        ui.text("niveau d'objet", "tiny", "gray", (mid_x + mid_w // 2, y + 38), anchor="midtop")
        ui.text(f"Armure {c.armor}", "tiny", "light_gray", (mid_x + mid_w // 2, y + 64), anchor="midtop")
        ui.text(f"Critique {c.crit:g}%", "tiny", "light_gray", (mid_x + mid_w // 2, y + 82), anchor="midtop")
        ui.text(f"Hâte {c.haste:g}%", "tiny", "light_gray", (mid_x + mid_w // 2, y + 100), anchor="midtop")
        ui.text(f"Maîtrise {c.mastery:g}%", "tiny", "light_gray", (mid_x + mid_w // 2, y + 118), anchor="midtop")
    wy = y + 8 * pitch + 2
    for i, (slot, label) in enumerate(EQUIPMENT_LAYOUT["bottom"]):
        ui._draw_slot((x + w // 2 - size - 2 + i * (size + 4), wy), slot, label, c.equipment.get(slot), size)


def draw_session(ui, ctx, rect):
    x, y, w, h = rect
    s = ctx.session
    if s and (s["seconds"] or s["levels"] or s["money"]):
        money = s["money"]
        gold = abs(money) // 10000
        ui.text(f"Or : {'+' if money >= 0 else '-'}{gold} or", "small", "green" if money >= 0 else "red", (x, y))
        ui.text(f"Niveaux : +{s['levels']}", "small", "light_gray", (x, y + 24))
        ui.text("depuis " + format_duration(s["seconds"]), "tiny", "gray", (x, y + 50))
    else:
        ui.text("Rien de nouveau depuis le lancement", "small", "gray", (x, y))


# ===========================================================================
#  Quêtes, sacs, métiers, monnaies, verrouillages
# ===========================================================================
def draw_quests(ui, ctx, rect):
    x, y, w, h = rect
    tracker = ctx.quests
    quests = sorted(tracker.quests, key=lambda q: (not q.get("focus"), not q.get("tracked"), q["status"] != "complete"))
    if not quests:
        ui.text("Aucune quête", "small", "gray", (x, y))
        return
    lines = []
    for quest in quests[:12]:
        color = {"complete": "green", "failed": "red"}.get(quest["status"], "text")
        mark = "(*) " if quest.get("focus") else ""
        lines.append((ui.fit(f"{mark}[{quest['level']}] {quest['name']}", "small", w), color, 22))
        if quest["status"] == "complete":
            lines.append(("   À rendre", "green", 20))
        else:
            for obj in quest["objectives"][:3]:
                need = obj.get("need", 0)
                text = obj["text"] if not need > 1 else f"{obj['text']}"
                lines.append((ui.fit("   " + text, "tiny", w), "gray" if obj["done"] else "light_gray", 18))
        lines.append(("", "text", 6))
    total = sum(l[2] for l in lines)
    top = ui.scroll_begin("w_quests", pygame.Rect(x, y, w, h), total)
    py = top
    for text, color, lh in lines:
        if text and y - 24 < py < y + h:
            ui.text(text, "small" if lh >= 20 else "tiny", color, (x, py))
        py += lh
    ui.scroll_end()


def draw_bags(ui, ctx, rect):
    x, y, w, h = rect
    inv = ctx.inventory
    used = inv.slots_used if inv.slots_used is not None else inv.get_total_items()
    pct = 100 * used / inv.capacity if inv.capacity else 0
    ui.bar((x, y, w, 12), pct, C["red"] if pct >= 95 else C["green"], (28, 46, 32))
    ui.text(f"{used}/{inv.capacity} emplacements · {inv.free_slots()} libres", "small", "light_gray", (x, y + 18))
    py = y + 46
    for item in inv.top_items(max(1, (h - 50) // 22)):
        ui.text(ui.fit(item["name"], "small", w - 60), "small", QUALITY_COLORS.get(item.get("quality", 1), (255, 255, 255)), (x, py))
        ui.text(f"x{item['quantity']}", "small", "light_gray", (x + w, py), anchor="topright")
        py += 22


def draw_professions(ui, ctx, rect):
    x, y, w, h = rect
    craft = ctx.craft
    py = y
    for name, info in craft.professions.items():
        ui.text(ui.fit(name, "small", w - 90), "small", "text", (x, py))
        ui.text(f"{info['level']}/{info.get('max_level', 0)}", "small", "light_gray", (x + w, py), anchor="topright")
        if info.get("max_level"):
            ui.bar((x, py + 20, w, 8), 100 * info["level"] / info["max_level"], C["green"], (28, 46, 32))
        py += 38
    if not craft.professions:
        ui.text("Aucun métier", "small", "gray", (x, y))


def draw_currencies(ui, ctx, rect):
    x, y, w, h = rect
    entries = [c for c in ctx.data.currencies if c.get("quantity")][:14]
    if not entries:
        ui.text("Aucune monnaie exportée", "small", "gray", (x, y))
        return
    for i, cur in enumerate(entries):
        py = y + i * 22
        if py > y + h - 18:
            break
        ui.text(ui.fit(cur["name"], "small", w - 110), "small", "text", (x, py))
        maxq = cur.get("max", 0)
        ui.text(f"{cur['quantity']:,}".replace(",", " ") + (f"/{maxq}" if maxq else ""), "small", "gold", (x + w, py), anchor="topright")


def draw_lockouts(ui, ctx, rect):
    x, y, w, h = rect
    now = time.time()
    instances = ctx.data.lockouts["instances"]
    vault = ctx.data.vault["activities"]
    py = y
    for inst in instances[:6]:
        ui.text(ui.fit(f"{inst['name']} ({inst.get('difficulty', '')})", "small", w - 70), "small", "text", (x, py))
        ui.text(f"{inst.get('progress', 0)}/{inst.get('total', 0)}", "small", "orange", (x + w, py), anchor="topright")
        ui.text(format_remaining(inst["expires"] - now), "tiny", "gray", (x, py + 18))
        py += 40
    if vault:
        unlocked = sum(1 for a in vault if a["threshold"] and a["progress"] >= a["threshold"])
        ui.text(f"Chambre forte : {unlocked}/{len(vault)} emplacements", "small", "label", (x, py + 6))
    elif not instances:
        ui.text("Aucun verrouillage", "small", "gray", (x, y))


# ===========================================================================
#  Assistant : conversation
# ===========================================================================
class ChatState:
    """Historique de conversation (gardé dans chat_history.json) et envois à l'assistant."""

    MAX_MESSAGES = 60

    def __init__(self, path, llm):
        self.path, self.llm = path, llm
        self.messages = []        # {"role": "user"|"assistant"|"error", "text": str}
        self.job = None
        self.include_player = True
        self.scroll_bottom = True
        self.on_answer = None     # fonction appelée avec chaque réponse (lecture à voix haute)
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.messages = json.load(f)[-self.MAX_MESSAGES:]
        except (OSError, ValueError, TypeError):
            pass

    def _save(self):
        try:
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.messages[-self.MAX_MESSAGES:], f, ensure_ascii=False)
            os.replace(self.path + ".tmp", self.path)
        except OSError:
            pass

    def submit(self, text, ctx, images=None):
        text = text.strip()
        if not text or self.job is not None:
            return False
        images = list(images or [])
        self.messages.append({"role": "user", "text": text + (f"  [+{len(images)} image(s)]" if images else "")})
        prompt = text
        if self.include_player and ctx is not None:
            c = ctx.character
            prompt = (f"Contexte joueur : {c.name}, niveau {c.level} {c.class_name} {c.spec}, zone {c.location or 'inconnue'}, "
                      f"niveau d'objet {c.ilvl:g}.\n\n{text}")
        if not self.llm.is_configured():
            self.messages.append({"role": "error", "text": "Assistant non configuré : Paramètres généraux > Assistant IA."})
        else:
            self.job = self.llm.ask(prompt, images)
        self.scroll_bottom = True
        self._save()
        return True

    def poll(self):
        if self.job is not None and self.job.done:
            job, self.job = self.job, None
            self.messages.append({"role": "error" if job.error else "assistant", "text": job.error or job.text})
            self.scroll_bottom = True
            self._save()
            if self.on_answer and not job.error:
                self.on_answer(job.text)

    def clear(self):
        self.messages, self.job = [], None
        self._save()


def draw_assistant(ui, ctx, rect):
    x, y, w, h = rect
    chat = ui.chat
    if chat is None:
        ui.text("Assistant indisponible", "small", "gray", (x, y))
        return
    chat.poll()
    input_h = 34
    strip_h = ui.draw_attachments(x, y + h - input_h - 34 - 62, w, measure_only=True)
    area = pygame.Rect(x, y, w, h - input_h - 34 - strip_h)
    entries = list(chat.messages)
    if chat.job is not None:
        dots = "." * (1 + (pygame.time.get_ticks() // 400) % 3)
        entries.append({"role": "wait", "text": "Hermes réfléchit" + dots})
    rows = []   # (texte, couleur, taille)
    for m in entries:
        label, color = {"user": ("Vous", C["gold"]), "assistant": ("Hermes", C["green"]), "error": ("Erreur", C["red"]),
                        "wait": ("", C["gray"])}[m["role"]]
        if label:
            rows.append((label, color, "tiny"))
        for para in m["text"].split("\n"):
            for line in ui.wrap(para, "small", area.w - 20) if para.strip() else [""]:
                rows.append((line, C["text"] if m["role"] != "error" else C["red"], "small"))
        rows.append(("", C["text"], "tiny"))
    content_h = sum(20 if kind == "small" else 16 for _, _, kind in rows) + 8
    if chat.scroll_bottom:
        ui.scroll["w_chat"] = 10 ** 9
        chat.scroll_bottom = False
    top = ui.scroll_begin("w_chat", area, content_h)
    py = top
    for text, color, kind in rows:
        lh = 20 if kind == "small" else 16
        if text and area.y - lh < py < area.bottom:
            ui.text(text, kind, color, (area.x + 4, py))
        py += lh
    ui.scroll_end()

    if strip_h:
        ui.draw_attachments(x, area.bottom + 2, w)
    iy = area.bottom + strip_h + 4

    def send():
        images = ui.vision.payload() if ui.vision else []
        if chat.submit(ui.inputs.get("chat_msg", ""), ui.ctx, images):
            ui.inputs["chat_msg"] = ""
            if ui.vision:
                ui.vision.clear()

    ui.on_submit["chat_msg"] = send
    ui.input_box((x, iy, w - 150, input_h), "chat_msg", "Message pour Hermes (Entrée)…")
    ui.pill((x + w - 144, iy, 70, input_h), "Envoyer", True, send, font="tiny")
    ui.pill((x + w - 70, iy, 70, input_h), "Effacer", False, chat.clear, font="tiny")
    row = iy + input_h + 4
    ui.pill((x, row, 176, 24), ("[x] " if chat.include_player else "[ ] ") + "Joindre mon personnage", False,
            lambda: setattr(chat, "include_player", not chat.include_player), font="tiny")
    ui.pill((x + 182, row, 84, 24), "Capture", False, lambda: ui.actions["capture"]() if "capture" in ui.actions else None, font="tiny")
    voice_label = ui.voice.STATUS_LABELS[ui.voice.status] if ui.voice else "Micro"
    ui.pill((x + 272, row, max(110, ui.fonts["tiny"].size(voice_label)[0] + 22), 24), voice_label,
            bool(ui.voice and ui.voice.status in ("listening", "idle")),
            lambda: ui.actions["mic_cycle"]() if "mic_cycle" in ui.actions else None, font="tiny")


# ===========================================================================
#  Barre d'outils de l'overlay
# ===========================================================================
def draw_toolbar(ui, ctx, rect):
    x, y, w, h = rect
    actions = ui.actions
    manager = ui.manager
    voice_state = actions["voice_label"]() if "voice_label" in actions else "Micro"
    focus_short = {"auto": "auto", "forcé (actif)": "on", "forcé (inactif)": "off"}.get(
        actions["focus_label"]() if "focus_label" in actions else "auto", "auto")
    items = [("Fenêtre", lambda: actions["to_app"](), False, "Ramène la fenêtre principale devant"),
             ("Fermer", lambda: actions["close_overlay"]() if "close_overlay" in actions else None, False, "Ferme l'overlay (F9 pour le réafficher)"),
             ("Capture", lambda: actions["capture"]() if "capture" in actions else None, False, "Capture la fenêtre du jeu pour l'assistant"),
             (voice_state, lambda: actions["mic_cycle"]() if "mic_cycle" in actions else None, voice_state not in ("Micro : off", "Micro"), "Micro : off, appuyer pour parler, activation vocale"),
             ("Déverrouiller" if manager.locked else "Verrouiller", lambda: actions["toggle_lock"](), manager.locked, "Verrouille la position des widgets"),
             ("Focus : " + focus_short, lambda: actions["cycle_focus"](), manager.focus_active, "Mode Focus : auto, forcé actif, forcé inactif"),
             ("Widgets", lambda: actions["open_widgets"](), False, "Choisir les widgets affichés")]
    gap = 6
    widths = [ui.fonts["tiny"].size(label)[0] + 22 for label, _fn, _a, _t in items]
    needed = sum(widths) + gap * (len(items) - 1) + 28          # 28 = poignée de la barre
    entry = manager.layout.get("barre")
    if entry and entry["w"] < needed:
        entry["w"] = needed                                      # la barre s'agrandit pour que tous les boutons tiennent
    px = x
    for (label, fn, active, tip), pw in zip(items, widths):
        r = pygame.Rect(px, y, pw, h)
        ui.pill(r, label, active, fn, font="tiny")
        ui.tip(r, {"rows": [(tip, "text", "")]})
        px += pw + gap


# ===========================================================================
#  Widgets web (Open WebUI, vidéo) : la page est affichée par un processus séparé (webwidget.py)
# ===========================================================================
WEB_URL_SETTINGS = {"openwebui": "web.openwebui_url", "video": "web.video_url"}


def make_web_draw(wid):
    def draw(ui, ctx, rect):
        host = ui.webhost
        err = host.errors.get(wid) if host else "Gestionnaire web indisponible"
        if host and host.is_running(wid) and not err:
            return                      # la fenêtre web occupe la zone
        pygame.draw.rect(ui.screen, C["panel"], rect)
        x, y, w, h = rect
        url = ui.settings.get(WEB_URL_SETTINGS[wid], "") if ui.settings else ""
        if err:
            for i, line in enumerate(ui.wrap(err, "small", w - 20)[:4]):
                ui.text(line, "small", "red", (x + 10, y + 12 + i * 20))
        else:
            ui.text("Chargement de la page…", "small", "gray", (x + 10, y + 12))
        ui.text(ui.fit(url, "tiny", w - 20), "tiny", "gray", (x + 10, y + h - 78))
        ui.pill((x + 10, y + h - 52, 96, 26), "Réessayer", False, lambda: host.retry(wid) if host else None, font="tiny")
        ui.pill((x + 112, y + h - 52, 150, 26), "Ouvrir dans le navigateur", False, lambda: ui._open_url(url) if url else None, font="tiny")
        ui.pill((x + 268, y + h - 52, 76, 26), "Réglages", False, lambda: ui.open_settings("web"), font="tiny")
    return draw


# ===========================================================================
#  Catalogue
# ===========================================================================
def build_specs():
    return [
        WidgetSpec("barre", "Barre d'outils", (640, 34), draw_toolbar, min_size=(560, 30), chrome=False, closable=False,
                   note="Boutons rapides de l'overlay"),
        WidgetSpec("personnage", "Personnage", (300, 170), draw_character, focus="keep", note="Nom, niveau, expérience, or, zone"),
        WidgetSpec("equipement", "Équipement", (260, 470), draw_equipment, min_size=(200, 300), focus="hide",
                   note="Les 18 emplacements avec infobulles"),
        WidgetSpec("quetes", "Quêtes", (340, 300), draw_quests, focus="shrink", note="Quêtes suivies et objectifs"),
        WidgetSpec("assistant", "Assistant (Hermes)", (440, 420), draw_assistant, min_size=(340, 300), focus="hide",
                   note="Conversation avec l'assistant IA"),
        WidgetSpec("sacs", "Sacs", (300, 220), draw_bags, focus="hide", enabled=False, note="Remplissage et objets les plus nombreux"),
        WidgetSpec("metiers", "Métiers", (260, 180), draw_professions, focus="hide", enabled=False, note="Niveaux de métiers"),
        WidgetSpec("monnaies", "Monnaies", (280, 340), draw_currencies, focus="hide", enabled=False, note="Monnaies de l'extension"),
        WidgetSpec("instances", "Instances", (300, 260), draw_lockouts, focus="hide", enabled=False,
                   note="Verrouillages et Grande Chambre forte"),
        WidgetSpec("openwebui", "Open WebUI", (520, 560), make_web_draw("openwebui"), min_size=(320, 260), focus="hide",
                   enabled=False, web=True, note="Interface Open WebUI (processus isolé)"),
        WidgetSpec("video", "Lecteur vidéo", (480, 320), make_web_draw("video"), min_size=(280, 200), focus="hide",
                   enabled=False, web=True, note="YouTube / Twitch (processus isolé)"),
        WidgetSpec("session", "Session", (220, 110), draw_session, focus="shrink", enabled=False, note="Gains depuis le lancement"),
    ]
