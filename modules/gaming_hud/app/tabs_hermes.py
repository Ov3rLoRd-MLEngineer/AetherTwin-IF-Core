"""
Onglet « Hermes » : Hermes Agent comme coach de jeu. À gauche, l'état de Hermes sur le PC et sa mise en place
(skill wow-coach, outils de jeu MCP, API de la passerelle) ; à droite, la conversation partagée avec le widget
Assistant de l'overlay, avec des questions toutes prêtes.

Les réglages de Hermes ne changent que par un clic du joueur sur ces boutons (copie de sauvegarde avant chaque
modification) ; la clé de l'API n'est jamais affichée.
"""
import threading

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
         "10 outils en lecture seule : personnage, quêtes, sacs, métiers, talents, progression, collections..."),
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


def _draw_right(ui, chat, rect):
    x, y, w, h = rect
    ui.frame(rect, "Coach de jeu")
    chat.poll()
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
    chatview.draw_composer(ui, chat, (x + 16, input_y, w - 32, input_h), "hermes_msg")
    ui.pill((x + 16, options_y, 200, 24), ("[x] " if chat.include_player else "[ ] ") + "Joindre mon personnage",
            False, lambda: setattr(chat, "include_player", not chat.include_player), font="tiny")
    ui.pill((x + 222, options_y, 140, 24), "Capture du jeu", False,
            lambda: ui.actions["capture"]() if "capture" in ui.actions else None, font="tiny")
    files_rect = pygame.Rect(x + 368, options_y, 150, 24)
    ui.pill(files_rect, "Joindre un fichier", False, lambda: chatview.pick_files(ui, chat), font="tiny")
    ui.tip(files_rect, {"rows": [("Texte (txt, md, lua, json, csv, log...) ou image ; ou glissez-le sur la fenêtre.",
                                  C["light_gray"], ""),
                                 ("Pour une page web : collez son lien dans la question, Hermes la lit.", C["gray"], "")]})
    ui.text(ui.fit(ui.llm.describe(), "tiny", w - 540), "tiny", "gray", (x + w - 16, options_y + 5),
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
