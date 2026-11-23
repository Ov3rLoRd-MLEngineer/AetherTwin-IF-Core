"""
Onglet « Hermes » : Hermes Agent comme coach de jeu. À gauche, l'état de Hermes sur le PC et sa mise en place
(skill wow-coach, outils de jeu MCP, API de la passerelle) ; à droite, la conversation partagée avec le widget
Assistant de l'overlay, avec des questions toutes prêtes.

Les réglages de Hermes ne changent que par un clic du joueur sur ces boutons (copie de sauvegarde avant chaque
modification) ; la clé de l'API n'est jamais affichée.
"""
import re
import threading
import time

import pygame

import chatview
import hermes_bridge
from theme import C
from tabutil import message

LEFT_W = 400
TRANSPORTS = (("auto", "Auto"), ("api", "API"), ("cli", "CLI"))


def _run_setup(ui, label, fn):
    """Action de mise en place en arrière-plan (hermes mcp add peut prendre un moment)."""
    state = ui.state
    if state.get("hermes_busy"):
        return
    state["hermes_busy"] = label
    state["hermes_note"] = (True, label + "…")

    def work():
        try:
            ok, text = fn()
        except Exception as e:                     # fichier verrouillé, Hermes absent...
            ok, text = False, f"{label} : {e}"
        state["hermes_note"] = (ok, text)
        state["hermes_busy"] = ""
    threading.Thread(target=work, daemon=True).start()


def _open_desktop(ui, info):
    ui.state["hermes_note"] = hermes_bridge.open_desktop(info)


def _status_rows(st, mode, in_use):
    yes, no, warn = C["green"], C["red"], C["orange"]
    api_text = ("en marche" if st.get("api_up") else
                "activée, relancez la passerelle" if st.get("api_enabled") and st.get("api_key") else
                "clé manquante" if st.get("api_enabled") else "désactivée")
    return [
        ("Hermes Agent", f"trouvé {st.get('version') or ''}".strip() if st.get("found") else "introuvable",
         yes if st.get("found") else no),
        ("Passerelle", "en marche" if st.get("gateway") else "arrêtée", yes if st.get("gateway") else warn),
        ("Modèle", st.get("model") or "?", C["light_gray"]),
        ("Contexte du modèle", (f"{st['context']:,} jetons".replace(",", " ") if st.get("context") else "non précisé"),
         (yes if st.get("context", 0) >= hermes_bridge.MIN_CONTEXT else no) if st.get("context") else C["light_gray"]),
        ("API (temps réel)", api_text, yes if st.get("api_up") else warn),
        ("Mode utilisé", {"api": "API de la passerelle", "cli": "CLI (hermes -z)"}.get(mode, "indisponible"),
         yes if mode == "api" else (warn if mode else no)),
        ("Skill wow-coach", "installé" if st.get("skill") else "non installé", yes if st.get("skill") else warn),
        ("Outils de jeu (MCP)", "ajoutés" if st.get("mcp") else "non ajoutés", yes if st.get("mcp") else warn),
        ("Assistant de l'appli", "Hermes" if in_use else "autre assistant", yes if in_use else warn),
    ]


def _draw_left(ui, chat, rect):
    x, y, w, h = rect
    ui.frame(rect, "Hermes Agent")
    llm = ui.llm
    client = llm.hermes
    info = client.info
    st = info.refresh()
    mode = client.transport()
    in_use = llm.uses_hermes()
    state = ui.state
    py = y + 46
    for label, value, color in _status_rows(st, mode, in_use):
        pygame.draw.circle(ui.screen, color, (x + 22, py + 9), 5)
        ui.text(label, "small", "light_gray", (x + 34, py))
        ui.text(ui.fit(value, "small", w - 210), "small", color if color != C["light_gray"] else "text",
                (x + w - 16, py), anchor="topright")
        py += 24

    py += 6
    if not in_use:
        def use_hermes():
            ui.settings.set("llm.mode", "hermes")
            ui.settings.save()
            state["hermes_note"] = (True, "Hermes répond maintenant dans l'appli et dans l'overlay.")
        ui.pill((x + 16, py, w - 32, 30), "Utiliser Hermes comme assistant", True, use_hermes)
        py += 38

    ui.text("Connexion :", "tiny", "gray", (x + 16, py + 6))
    px = x + 96
    current = ui.settings.get("hermes.transport", "auto")
    for value, label in TRANSPORTS:
        def choose(v=value):
            ui.settings.set("hermes.transport", v)
            ui.settings.save()
        ui.pill((px, py, 64, 26), label, current == value, choose, font="tiny")
        px += 70
    reason_y = py + 32
    ui.text("Réflexion :", "tiny", "gray", (x + 16, reason_y + 6))
    rx = x + 96
    level = ui.settings.get("hermes.reasoning", "medium")
    for value, label in hermes_bridge.REASONING:
        rw = ui.fonts["tiny"].size(label)[0] + 16
        def pick(v=value):
            ui.settings.set("hermes.reasoning", v)
            ui.settings.save()
        ui.pill((rx, reason_y, rw, 26), label, level == value, pick, font="tiny")
        rx += rw + 4
    ui.tip(pygame.Rect(x + 16, reason_y, w - 32, 26),
           {"rows": [("Temps de réflexion du modèle avant de répondre (Rapide = réponses plus vite).",
                      C["light_gray"], ""),
                     ("« Hermes » : le réglage de Hermes (« high » est refusé par Qwen 3.5).", C["gray"], "")]})
    tip_rect = pygame.Rect(x + 16, py, w - 32, 26)
    ui.tip(tip_rect, {"rows": [("Auto : l'API si elle tourne, sinon la CLI.", C["light_gray"], ""),
                               ("API : réponse au fil de l'eau, images, autorisations dans l'appli.", C["gray"], ""),
                               ("CLI : sans réglage, ≈ 20 s par question, outils sans danger seulement.", C["gray"], "")]})
    py += 70

    ui.text("Mise en place (un clic, sauvegarde automatique) :", "tiny", "gray", (x + 16, py))
    py += 20
    busy = bool(state.get("hermes_busy"))
    found = bool(st.get("found"))
    actions = [
        ("Mettre à jour le skill wow-coach" if st.get("skill") else "Installer le skill wow-coach",
         lambda: _run_setup(ui, "Installation du skill", lambda: hermes_bridge.install_skill(info)),
         not st.get("skill"),
         "Consignes de coach (français, données du jeu, Wowhead, pas de triche) dans les skills de Hermes."),
        ("Outils de jeu ajoutés (réinstaller)" if st.get("mcp") else "Ajouter les outils de jeu (MCP)",
         lambda: _run_setup(ui, "Ajout des outils de jeu", lambda: hermes_bridge.register_mcp(info)),
         not st.get("mcp"),
         "Outils de jeu en lecture seule (personnage, quêtes, sacs, métiers, talents...) et base de connaissances."),
        ("API activée" if st.get("api_enabled") and st.get("api_key") else "Activer l'API de Hermes",
         lambda: _run_setup(ui, "Activation de l'API", lambda: hermes_bridge.enable_api(info)),
         not (st.get("api_enabled") and st.get("api_key")),
         "Écrit API_SERVER_ENABLED et une clé aléatoire dans le .env de Hermes (jamais affichée), puis relancez Hermes."),
        ("Relancer la passerelle (API)",
         lambda: _run_setup(ui, "Relance de la passerelle", lambda: hermes_bridge.restart_gateway(info)),
         bool(st.get("api_enabled") and st.get("api_key") and not st.get("api_up")),
         "La passerelle de Hermes tourne en arrière-plan (fermer l'application ne l'arrête pas) : la relancer "
         "applique l'activation de l'API."),
        ("Ouvrir l'application Hermes", lambda: _open_desktop(ui, info), False,
         "Lance Hermes Agent, détaché de WoW Assistant."),
        ("Nouvelle conversation", chat.new_conversation, False,
         "Efface le fil ici et ouvre une nouvelle session dans Hermes."),
    ]
    for label, fn, highlight, tip in actions:
        r = pygame.Rect(x + 16, py, w - 32, 30)
        ui.pill(r, label, highlight and found and not busy, (fn if found and not busy else (lambda: None)))
        ui.tip(r, {"rows": [(tip, C["light_gray"], "")]})
        py += 36

    note = state.get("hermes_note")
    if note:
        ok, text = note
        for line in ui.wrap(text, "small", w - 32)[:3]:
            ui.text(line, "small", "green" if ok else "red", (x + 16, py + 4))
            py += 20
    elif not found:
        message(ui, (x, py, w, 80), ["Installez Hermes Agent puis revenez ici."])
    top = max(py + 18, y + h - 150)                     # l'aide prend la place qui reste, sans chevaucher
    _draw_help(ui, (x + 16, top, w - 32, y + h - 10 - top), st)


HELP = ("Hermes lit votre personnage, vos quêtes, vos sacs, vos métiers et vos collections grâce aux outils de jeu "
        "(lecture seule), cherche sur Wowhead et retient vos objectifs d'une session à l'autre.",
        "Le même fil est dans l'overlay : widgets « Assistant (Hermes) » et « Coach Hermes ».",
        "Toute commande sensible demandée par Hermes attend votre clic (Autoriser / Refuser).")


def _draw_help(ui, rect, st):
    x, y, w, h = rect
    pygame.draw.line(ui.screen, C["frame"], (x, y - 8), (x + w, y - 8), 1)
    py = y
    for para in HELP:
        for line in ui.wrap(para, "tiny", w):
            if py + 16 > y + h:
                return
            ui.text(line, "tiny", "gray", (x, py))
            py += 16
        py += 4


def knowledge(ui):
    """Base de connaissances du coach (créée à la première utilisation, partagée avec le serveur MCP)."""
    kb = getattr(ui, "knowledge", None)
    if kb is None:
        from coach_knowledge import DEFAULT_PATH, KnowledgeBase
        kb = ui.knowledge = KnowledgeBase(DEFAULT_PATH)
    if ui.chat is not None and ui.chat.knowledge is None:
        ui.chat.knowledge = kb
    return kb


KB_FILTERS = (("all", "Tout"), ("joueur", "Corrigés par moi"), ("sourcé", "Vérifiés en ligne"),
              ("stale", "À revérifier"), ("rejeté", "Rejetés"))


def _draw_knowledge(ui, rect):
    x, y, w, h = rect
    kb = knowledge(ui)
    kb.reload_if_changed()
    state = ui.state
    state.setdefault("kb_filter", "all")
    px = x
    for value, label in KB_FILTERS:
        pw = ui.fonts["tiny"].size(label)[0] + 20
        ui.pill((px, y, pw, 26), label, state["kb_filter"] == value, lambda v=value: state.update(kb_filter=v),
                font="tiny")
        px += pw + 6
    query = ui.input_box((x + w - 300, y, 300, 26), "kb_search", "Rechercher…").lower()
    stats = kb.stats()
    ui.text(f"{stats['joueur']} corrigé(s) par vous · {stats['sourcé']} vérifié(s) en ligne · "
            f"{stats['à revérifier']} à revérifier · {stats['rejeté']} rejeté(s)", "tiny", "gray", (x, y + 34))
    flt = state["kb_filter"]
    shown = [e for e in reversed(kb.entries)
             if (flt == "all" or (flt == "stale" and kb.stale(e)) or e["status"] == flt)
             and (not query or query in (e["subject"] + " " + e["fact"]).lower())]
    area = pygame.Rect(x, y + 56, w, h - 56 - 44)
    rows = []
    for e in shown:
        lines = ui.wrap(e["fact"], "small", area.w - 200)[:6]
        rows.append((e, lines, 26 + 20 * len(lines) + 30))
    content = sum(r[2] for r in rows) + 8
    top = ui.scroll_begin("kb_list", area, content)
    py = top
    colors = {"joueur": "gold", "sourcé": "green", "rejeté": "red"}
    labels = {"joueur": "Corrigé par vous", "sourcé": "Vérifié en ligne", "rejeté": "Rejeté"}
    for e, lines, rh in rows:
        if py + rh > area.y and py < area.bottom:
            box = pygame.Rect(area.x, py, area.w - 14, rh - 6)
            pygame.draw.rect(ui.screen, (22, 22, 27), box, border_radius=6)
            status = labels[e["status"]] + (" · à revérifier" if kb.stale(e) else "")
            ui.text(ui.fit(f"{e['topic'].capitalize()} — {e['subject']}", "small", box.w - 230), "small", "text",
                    (box.x + 10, box.y + 6))
            ui.text(status, "tiny", colors[e["status"]], (box.right - 10, box.y + 8), anchor="topright")
            ly = box.y + 28
            for line in lines:
                ui.text(line, "small", "light_gray", (box.x + 10, ly))
                ly += 20
            src = e.get("source") or ""
            when = time.strftime("%d/%m/%Y", time.localtime(e.get("verified", 0)))
            src_label = ui.fit((src if src.startswith("http") else "vous") + f"  ·  {when}", "tiny", box.w - 330)
            src_rect = ui.text(src_label, "tiny", "blue" if src.startswith("http") else "gray", (box.x + 10, ly + 2))
            if src.startswith("http"):
                ui.link(src_rect, src)
            bx = box.right - 10
            for label, fn in (("Supprimer", lambda i=e["id"]: kb.delete(i)),
                              ("Rejeter", lambda i=e["id"]: kb.set_status(i, "rejeté")),
                              ("C'est juste", lambda i=e["id"]: kb.set_status(i, "joueur"))):
                if (label == "Rejeter" and e["status"] == "rejeté") or (label == "C'est juste" and e["status"] == "joueur"):
                    continue
                bw = ui.fonts["tiny"].size(label)[0] + 18
                bx -= bw
                ui.pill((bx, ly - 2, bw, 22), label, False, fn, font="tiny")
                bx -= 6
        py += rh
    ui.scroll_end()
    if not rows:
        ui.text("Rien pour l'instant : Hermes enregistre ce qu'il vérifie en ligne, et vos corrections arrivent ici.",
                "small", "gray", (area.x + 4, area.y + 4))
    iy = y + h - 36
    ui.on_submit["kb_rule"] = lambda: _add_rule(ui, kb)
    ui.input_box((x, iy, w - 170, 32), "kb_rule", "Ajouter une règle ou un fait sûr (il fera foi pour Hermes)…")
    ui.pill((x + w - 162, iy, 162, 32), "Ajouter", True, lambda: _add_rule(ui, kb), font="tiny")


def _add_rule(ui, kb):
    text = ui.inputs.get("kb_rule", "").strip()
    if not text:
        return
    subject = re.split(r"[.:;!?\n]", text, maxsplit=1)[0][:90] or text[:90]
    ok, msg, _e = kb.add("règle", subject, text, source="joueur", status="joueur")
    ui.inputs["kb_rule"] = "" if ok else text
    ui.notify("Règle ajoutée : Hermes la respectera." if ok else msg)


def _send_or_correct(ui, chat):
    if ui.state.get("hermes_correcting"):
        if chat.correct(ui.inputs.get("hermes_msg", ""), ui.ctx):
            ui.inputs["hermes_msg"] = ""
            ui.state["hermes_correcting"] = False
            ui.notify("Correction enregistrée : elle fera foi pour Hermes.")
        return
    chatview.send_from(ui, chat, "hermes_msg")


def _draw_right(ui, chat, rect):
    x, y, w, h = rect
    ui.frame(rect, "Coach de jeu")
    chat.poll()
    kb = knowledge(ui)
    state = ui.state
    view = state.setdefault("hermes_view", "chat")
    tabs = (("chat", "Conversation"), ("kb", f"Connaissances ({len(kb.entries)})"))
    tx = x + w - 16
    for value, label in reversed(tabs):
        tw = ui.fonts["tiny"].size(label)[0] + 22
        tx -= tw
        ui.pill((tx, y + 9, tw, 24), label, view == value, lambda v=value: state.update(hermes_view=v), font="tiny")
        tx -= 6
    if view == "kb":
        _draw_knowledge(ui, (x + 16, y + 44, w - 32, h - 58))
        return
    px, py = x + 16, y + 44
    for label, prompt in chatview.QUICK_PROMPTS:
        pw = ui.fonts["tiny"].size(label)[0] + 20
        if px + pw > x + w - 16:
            break
        ui.pill((px, py, pw, 26), label, False, lambda p=prompt: chatview.send_from(ui, chat, "hermes_msg", p),
                font="tiny")
        px += pw + 6
    if ui.vision and ui.vision.attachments and chat.job is None and px + 140 < x + w - 16:
        ui.pill((px, py, 134, 26), "Analyser la capture", True,
                lambda: chatview.send_from(ui, chat, "hermes_msg", chatview.CAPTURE_PROMPT), font="tiny")

    input_h = 34
    bottom = y + h - 14
    options_y = bottom - 24
    input_y = options_y - 6 - input_h
    approval_h = chatview.APPROVAL_H if chat.job is not None and getattr(chat.job, "approval", None) else 0
    strip_h = ui.draw_attachments(x + 16, 0, w - 32, measure_only=True)
    files_h = chatview.FILE_STRIP_H if chat.files else 0
    area = pygame.Rect(x + 16, py + 36, w - 32, input_y - 8 - strip_h - files_h - approval_h - (py + 36))
    pygame.draw.rect(ui.screen, (14, 14, 18), area.inflate(8, 8), border_radius=6)
    chatview.draw_transcript(ui, chat, area, "hermes_chat",
                             empty="Hermes voit votre personnage, vos quêtes, vos sacs et vos collections (outils de "
                                   "jeu), cherche sur Wowhead et se souvient de vos échanges. Choisissez une "
                                   "question ci-dessus ou écrivez la vôtre.")
    ay = area.bottom + 6
    if approval_h:
        chatview.draw_approval(ui, chat, (x + 16, ay, w - 32, approval_h))
        ay += approval_h
    if strip_h:
        ui.draw_attachments(x + 16, ay, w - 32)
        ay += strip_h
    chatview.draw_files(ui, chat, (x + 16, ay + 2, w - 32, files_h))
    correcting = bool(state.get("hermes_correcting"))
    chatview.draw_composer(ui, chat, (x + 16, input_y, w - 32, input_h), "hermes_msg",
                           "Votre correction de la dernière réponse (elle fera foi)…" if correcting else
                           "Message pour Hermes (Entrée)…", on_send=lambda: _send_or_correct(ui, chat),
                           label="Corriger" if correcting else "Envoyer")
    ui.pill((x + 16, options_y, 200, 24), ("[x] " if chat.include_player else "[ ] ") + "Joindre mon personnage",
            False, lambda: setattr(chat, "include_player", not chat.include_player), font="tiny")
    ui.pill((x + 222, options_y, 140, 24), "Capture du jeu", False,
            lambda: ui.actions["capture"]() if "capture" in ui.actions else None, font="tiny")
    files_rect = pygame.Rect(x + 368, options_y, 150, 24)
    ui.pill(files_rect, "Joindre un fichier", False, lambda: chatview.pick_files(ui, chat), font="tiny")
    ui.tip(files_rect, {"rows": [("Texte (txt, md, lua, json, csv, log...) ou image ; ou glissez-le sur la fenêtre.",
                                  C["light_gray"], ""),
                                 ("Pour une page web : collez son lien dans la question, Hermes la lit.", C["gray"], "")]})
    has_answer = any(m["role"] == "assistant" for m in chat.messages)
    if has_answer and chat.job is None:
        fix_rect = pygame.Rect(x + 524, options_y, 150, 24)
        ui.pill(fix_rect, "Annuler la correction" if correcting else "Corriger la réponse", correcting,
                lambda: state.update(hermes_correcting=not correcting), font="tiny")
        ui.tip(fix_rect, {"rows": [("Une erreur dans la dernière réponse ? Écrivez ce qui est juste :", C["light_gray"], ""),
                                   ("enregistré comme correction qui fait foi, rappelé à Hermes à chaque question.",
                                    C["gray"], "")]})
    ui.text(ui.fit(ui.llm.describe(), "tiny", w - 700), "tiny", "gray", (x + w - 16, options_y + 5),
            anchor="topright")


def draw_hermes(ui, ctx, rect):
    x, y, w, h = rect
    chat = ui.chat
    if chat is None or ui.llm is None:
        ui.frame(rect, "Hermes")
        message(ui, rect, ["Assistant indisponible"])
        return
    _draw_left(ui, chat, (x, y, LEFT_W, h))
    _draw_right(ui, chat, (x + LEFT_W + 16, y, w - LEFT_W - 16, h))
