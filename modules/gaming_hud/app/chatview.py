"""
Affichage commun de la conversation avec l'assistant (onglet Hermes, widget Assistant et widget Coach de l'overlay) :
fil des messages avec la réponse qui s'écrit au fil de l'eau, outils utilisés par Hermes, demande d'autorisation,
zone de saisie avec Envoyer / Stop.
"""
import re
import threading

import pygame

import waypoints
from theme import C

ROLES = {"user": ("Vous", "gold"), "assistant": ("Hermes", "green"), "error": ("Erreur", "red"), "wait": ("", "gray")}
LINE_H = {"small": 20, "tiny": 16}
APPROVAL_H = 104
QUICK_PROMPTS = (
    ("Que faire maintenant ?", "Vu mon personnage, ma zone et mes quêtes en cours, que me conseilles-tu de faire "
                               "maintenant ? Donne un plan court et concret."),
    ("Analyse mon perso", "Analyse mon personnage (équipement, talents, métiers, progression) et donne-moi mes trois "
                          "priorités pour progresser."),
    ("Équipement", "Quelles pièces de mon équipement améliorer en premier, et où les obtenir à mon niveau ?"),
    ("Talents", "Mes talents sont-ils adaptés à mon niveau et à ma spécialisation ? Propose des ajustements."),
    ("Quêtes", "Classe mes quêtes en cours par priorité et dis-moi dans quel ordre les faire."),
    ("Niveau", waypoints.LEVELING_PROMPT),
    ("Métiers", "Comment faire progresser mes métiers efficacement d'ici mon prochain palier ?"),
    ("Or", "Quelles sont mes meilleures façons de gagner de l'or avec ce personnage et ses métiers ?"),
)
CAPTURE_PROMPT = "Analyse la capture d'écran jointe (ce que je vois en jeu) et conseille-moi."
# « Faire vérifier » : Hermes relit sa dernière réponse, la vérifie en ligne et remplit la base de connaissances
VERIFY_PROMPT = ("Vérifie en ligne (Wowhead en priorité, sinon une source fiable) les affirmations factuelles de ta "
                 "réponse précédente : quêtes (XP, niveau, étapes), niveaux requis, objets, talents, lieux. Pour chaque "
                 "fait vérifié, enregistre-le avec wow_knowledge_save (thème, sujet court, fait précis, lien de la "
                 "page). Ne contredis pas une correction du joueur. Puis dis en quelques lignes ce qui était juste, "
                 "ce qui était faux, et le conseil corrigé s'il change.")


def plain(text):
    """Texte Markdown de Hermes rendu lisible en texte simple (titres, gras, puces, code)."""
    out = []
    for line in str(text or "").replace("\r", "").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        line = re.sub(r"^\s*#{1,6}\s+", "", line)
        line = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", line)
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", line)
        out.append(line.rstrip())
    return "\n".join(out).strip("\n")


def _dots():
    return "." * (1 + (pygame.time.get_ticks() // 400) % 3)


def transcript_rows(ui, chat, width, last_only=False):
    """Lignes à afficher : (texte, couleur, police)."""
    entries = list(chat.messages)
    job = chat.job
    if last_only:
        entries = [] if job is not None else [m for m in entries if m["role"] != "user"][-1:]
    if job is not None:
        partial = getattr(job, "text", "")
        if partial:
            entries.append({"role": "assistant", "text": partial})
        status = job.status() if hasattr(job, "status") else "Hermes réfléchit…"
        steps = [t for _t, kind, t in getattr(job, "events", []) if kind in ("tool", "fail", "approval")][-3:]
        if steps and steps[-1] == status:
            steps = steps[:-1]
        entries.append({"role": "wait", "text": status.rstrip("…. ") + _dots(), "tools": steps})
    rows = []
    for m in entries:
        label, color = ROLES.get(m["role"], ("", "gray"))
        if label:
            rows.append((label, C[color], "tiny"))
        text_color = C["red"] if m["role"] == "error" else (C["gray"] if m["role"] == "wait" else C["text"])
        text = plain(m["text"]) if m["role"] == "assistant" else m["text"]
        for para in text.split("\n"):
            for line in ui.wrap(para, "small", width) if para.strip() else [""]:
                rows.append((line, text_color, "small"))
        tools = m.get("tools") or []
        if m["role"] == "wait":
            for t in tools:
                rows.append((ui.fit("› " + t, "tiny", width), C["gray"], "tiny"))
        elif tools:
            names = list(dict.fromkeys(t.split(" : ")[0] for t in tools))
            rows.append((ui.fit("Outils : " + " · ".join(names), "tiny", width), C["gray"], "tiny"))
        rows.append(("", C["text"], "tiny"))
    return rows


def draw_transcript(ui, chat, area, key, last_only=False, empty=""):
    """Fil de la conversation dans area (défilant). Descend tout seul quand un message arrive ou s'écrit."""
    area = pygame.Rect(area)
    rows = transcript_rows(ui, chat, area.w - 22, last_only)
    if not rows and empty:
        for i, line in enumerate(ui.wrap(empty, "small", area.w - 20)):
            ui.text(line, "small", "gray", (area.x + 4, area.y + 4 + i * 20))
        return
    content_h = sum(LINE_H[kind] for _, _, kind in rows) + 8
    job = chat.job
    signature = (len(chat.messages), len(getattr(job, "text", "") or ""), len(getattr(job, "events", []) or []),
                 job is None)
    if ui.state.get(key + "_sig") != signature:
        ui.state[key + "_sig"] = signature
        ui.scroll[key] = 10 ** 9
    top = ui.scroll_begin(key, area, content_h)
    py = top
    for text, color, kind in rows:
        lh = LINE_H[kind]
        if text and area.y - lh < py < area.bottom:
            ui.text(text, kind, color, (area.x + 4, py))
        py += lh
    ui.scroll_end()


def draw_approval(ui, chat, rect):
    """Demande d'autorisation de Hermes (commande sensible) : rien n'est accordé sans un clic du joueur."""
    job = chat.job
    pending = getattr(job, "approval", None) if job is not None else None
    if not pending:
        return 0
    x, y, w, _h = rect
    box = pygame.Rect(x, y, w, APPROVAL_H - 6)
    pygame.draw.rect(ui.screen, (44, 34, 20), box, border_radius=6)
    pygame.draw.rect(ui.screen, C["orange"], box, 1, border_radius=6)
    ui.text("Hermes demande une autorisation", "small", "orange", (x + 10, y + 6))
    detail = pending.get("description") or ""
    command = pending.get("command") or ""
    ui.text(ui.fit(detail or command, "tiny", w - 20), "tiny", "light_gray", (x + 10, y + 28))
    if command and detail:
        ui.text(ui.fit(command, "tiny", w - 20), "tiny", "gray", (x + 10, y + 44))
    choices = pending.get("choices") or ["once", "deny"]
    labels = [("once", "Autoriser une fois"), ("session", "Pour cette session"), ("deny", "Refuser")]
    px = x + 10
    for choice, label in labels:
        if choice not in choices and choice != "deny":
            continue
        pw = ui.fonts["tiny"].size(label)[0] + 20
        ui.pill((px, y + 70, pw, 24), label, choice == "deny", lambda c=choice: chat.approve(c), font="tiny")
        px += pw + 6
    return APPROVAL_H


FILE_STRIP_H = 30


def last_waypoints(chat):
    """Points de route (/ha way, /way) cités dans la dernière réponse."""
    answer = next((m for m in reversed(chat.messages) if m["role"] == "assistant"), None)
    return waypoints.extract(answer["text"]) if answer else []


def draw_waypoints(ui, ways, rect):
    """Barre « Points de route » : un clic copie la commande à coller dans la discussion du jeu."""
    x, y, w, h = rect
    ui.text("Points de route :", "tiny", "label", (x, y + 6))
    px = x + 104
    for way in ways:
        label = way["cmd"].replace("/ha way ", "") + (f" · {way['label']}" if way["label"] else "")
        pw = min(ui.fonts["tiny"].size(label)[0] + 20, 260)
        if px + pw > x + w:
            break
        rect_w = pygame.Rect(px, y + 2, pw, 22)
        ui.pill(rect_w, ui.fit(label, "tiny", pw - 14), False, lambda wy=way: waypoints.copy(ui, wy), font="tiny")
        ui.tip(rect_w, {"rows": [(way["cmd"], C["light_gray"], ""),
                                 ("Copié d'un clic : collez-le dans la discussion du jeu (addon 1.10).", C["gray"], "")]})
        px += pw + 6
    return h


def draw_files(ui, chat, rect):
    """Rangée des fichiers joints (× pour retirer). Retourne la hauteur utilisée."""
    files = getattr(chat, "files", None)
    if not files:
        return 0
    x, y, w, _h = rect
    px = x
    for i, f in enumerate(list(files)):
        label = ("Image : " if "image" in f else "Fichier : ") + f["name"]
        pw = min(260, ui.fonts["tiny"].size(label)[0] + 40)
        if px + pw > x + w:
            ui.text(f"+{len(files) - i}", "tiny", "gray", (px, y + 5))
            break
        box = pygame.Rect(px, y, pw, 24)
        pygame.draw.rect(ui.screen, (30, 30, 36), box, border_radius=5)
        pygame.draw.rect(ui.screen, C["frame_hi"], box, 1, border_radius=5)
        ui.text(ui.fit(label, "tiny", pw - 34), "tiny", "light_gray", (px + 8, y + 5))
        close = pygame.Rect(box.right - 22, y + 2, 20, 20)
        ui.text("×", "small", "gray", close.center, anchor="center")
        ui.click(close, lambda n=i: chat.remove_file(n))
        px += pw + 6
    return FILE_STRIP_H


def pick_files(ui, chat):
    """Sélecteur de fichiers Windows (en arrière-plan, comme celui du dossier du jeu)."""
    def work():
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            chosen = filedialog.askopenfilenames(title="Fichiers à joindre à la question pour Hermes")
            root.destroy()
        except Exception as e:
            ui.notify(f"Sélecteur de fichiers indisponible ({e}) : glissez le fichier sur la fenêtre.")
            return
        for path in chosen or ():
            ok, text = chat.attach_file(path)
            ui.notify(text, 6)
    threading.Thread(target=work, daemon=True).start()


def send_from(ui, chat, key, text=None):
    """Envoie la saisie (ou un texte tout prêt) avec les captures jointes."""
    images = ui.vision.payload() if ui.vision else []
    message = ui.inputs.get(key, "") if text is None else text
    if chat.submit(message, ui.ctx, images):
        if text is None:
            ui.inputs[key] = ""
        if ui.vision:
            ui.vision.clear()
        return True
    return False


def draw_composer(ui, chat, rect, key, placeholder="Message pour Hermes (Entrée)…", on_send=None, label="Envoyer"):
    """Saisie + Envoyer (ou Stop pendant une réponse) + Effacer."""
    x, y, w, h = rect
    send = on_send or (lambda: send_from(ui, chat, key))
    ui.on_submit[key] = send
    ui.input_box((x, y, w - 150, h), key, placeholder)
    if chat.job is not None:
        ui.pill((x + w - 144, y, 70, h), "Stop", True, chat.stop, font="tiny")
    else:
        ui.pill((x + w - 144, y, 70, h), label, True, send, font="tiny")
    ui.pill((x + w - 70, y, 70, h), "Effacer", False, chat.new_conversation, font="tiny")
