"""
Interface utilisateur pour WoW Assistant
Style inspiré de l'interface de WoW : cadres sombres à bordure métallique, titres dorés,
fenêtre de personnage avec emplacements d'équipement, infobulles et onglets en bas.

Ce fichier contient le "moteur" (polices, cadres, clics, infobulles, défilement, saisie)
et l'onglet Personnage. Les autres onglets sont dans tabs.py.
"""
import os
import threading
import time
import webbrowser

import clipboard
import features
import i18n
import mousepos
import overlay as overlay_win
import pygame
import tabs
import voice as voice_mod
from character import EQUIPMENT_LAYOUT, Character, format_duration
from llm import PROVIDERS, STRATA_ENDPOINT, enabled_servers, guess_provider, list_models_at
from media import fit_image
from quests import QuestTracker
from theme import QUALITY_COLORS, C, clean_wow_text, hex_to_rgb
from wowhead import IconCache, LinkResolver

from config import WoWConfig

SLOT_SHORT = {1: "Tête", 2: "Cou", 3: "Épaul.", 15: "Dos", 5: "Torse", 4: "Chem.", 19: "Tabard", 9: "Poign.",
              10: "Mains", 6: "Taille", 7: "Jambes", 8: "Pieds", 11: "Ann. 1", 12: "Ann. 2",
              13: "Bij. 1", 14: "Bij. 2", 16: "Main D.", 17: "Main G."}

TAB_NAMES = ["Personnage", "Talents et grimoire", "Journal des quêtes", "Sacs", "Métiers",
             "Hauts Faits", "Collections du bataillon", "Historique d'activité",
             "Réputations et monnaies", "Semaine", "Instances et Chambre", "Hôtel des ventes", "Bilans", "Bestiaire", "Hermes"]


class UI:
    """Affichage Pygame"""

    W, H = 1620, 860
    TABS = TAB_NAMES
    FONT_SCALE = 1.0   # à ajuster si la police du jeu paraît trop petite / grande
    TOP, BOTTOM = 62, 776
    SLOT, PITCH = 54, 64

    def __init__(self, links=None, icons=None, settings=None, llm=None):
        pygame.init()
        UI.instance = self      # (utilisé par les tests automatiques)
        self._track_y = None              # (suivi de la hauteur du contenu des réglages)
        self.cur = "app"                  # fenêtre en cours de traitement : "app" ou "overlay"
        self._modals = {}                 # une fenêtre modale par fenêtre (app / overlay)
        self._quit_now = False            # « Oui » dans la confirmation : la boucle principale s'arrête
        self._ctx_store = {"overlay": None}
        self.overlay_win = self.overlay_ren = None   # 2e fenêtre SDL (overlay), indépendante de la fenêtre principale
        self.overlay_on = False
        self.overlay_visible = True
        self.overlay_error = ""
        self._ov_mouse = None
        mousepos.provider = self.mouse_pos
        try:
            self.screen = pygame.display.set_mode((self.W, self.H), pygame.SCALED | pygame.RESIZABLE)
        except pygame.error:
            self.screen = pygame.display.set_mode((self.W, self.H))
        pygame.display.set_caption("WoW Assistant")

        self.links = links or LinkResolver()
        self.icons = icons or IconCache()
        self.settings = settings
        self.llm = llm
        self.media = None                 # MediaStore (rendus Battle.net), branché par main.py
        self.bestiary = None              # Bestiary (journal de combat + addon), branché par main.py
        self.viewer3d = None              # Viewer3D (vue 3D facultative de Wowhead), branché par main.py
        self._view3d = None               # (clé, chargeur) de ce que la vue 3D doit montrer (image en cours)
        self._embed = None                # cadre (logique) où incruster la vue 3D sur cette image
        self._can_embed = None
        self.market = None                # Market (prix HdV : Battle.net, TSM, Auctionator), branché par main.py
        self.manager = None               # WidgetManager (mode overlay)
        self.chat = None                  # ChatState (widget Assistant)
        self.webhost = None               # WebHost (widgets web dans des processus isolés)
        self.vision = None                # VisionManager (captures d'écran)
        self.voice = None                 # VoiceManager (micro, STT, TTS)
        self.actions = {}                 # fonctions fournies par main.py (changer de mode, verrouiller, focus...)
        self.on_submit = {}               # touche Entrée dans un champ de saisie -> fonction
        self._clip_stack = []
        self.overlay_active = False       # True si le style transparent Windows est appliqué
        self.refresh_requested = False
        self.refresh_note = ("", 0.0)
        self._scrollbars = []
        self._drag = None
        self._cache = {}
        self.using_game_font = False
        self.fonts = self._load_fonts()
        self.background = self._build_background()

        self.W, self.H = UI.W, UI.H
        self.active_tab = 0
        self.scroll = {}                 # clé de zone -> décalage
        self.inputs = {}                 # clé de champ -> texte saisi
        self.focus = None                # champ de saisie actif
        self.state = {"spell_line": 0, "quest_id": None, "bag_type": None, "bag_view": "bags", "bank_tab": 0,
                      "profession": None, "craftable_only": False, "collection": "mounts", "range": "7d",
                      "ach_cat": None, "ach_open": [], "ach_filter": "all", "mount_filter": "all",
                      "pet_filter": "all", "pet_type": None, "toy_filter": "all", "sel": {},
                      "tm_open": [], "tm_class": None, "tm_sel": None, "activity_view": "evolution",
                      "event_filter": "all", "stat_cat": None, "rep_group": None}
        self._buttons, self._tips, self._scroll_regions = [], [], []
        self._clip = None
        self._scrollbar = None
        self.ctx = None
        # saisie : curseur, « tout sélectionner », répétition des touches, menu du clic droit
        self._caret = (None, 0)          # (champ, position du curseur dans le texte)
        self._focus_prev = None          # champ qui avait la saisie à l'image précédente
        self.select_all = None           # champ dont tout le texte est sélectionné (Ctrl+A)
        self._keys_down = set()          # touches enfoncées : distingue un appui d'une répétition
        self._input_rects = {}           # champ -> (fenêtre, rect, image, début affiché) pour le clic droit / le clic
        self._masked = set()             # champs masqués (clés API) : jamais copiés
        self._frame = 0
        self._menu = None                # menu contextuel : {"win", "key", "rect"}
        try:
            pygame.key.set_repeat(400, 35)   # rester appuyé répète la touche (effacer, flèches, lettres)
        except pygame.error:
            pass

    # ================================================================== ressources
    def _load_fonts(self):
        sizes = {"tiny": 12, "small": 15, "medium": 18, "large": 24, "title": 30, "huge": 34}
        friz = WoWConfig.font_path("FRIZQT__.TTF")   # police du jeu si elle est installée
        fonts = {}
        for key, size in sizes.items():
            size = int(size * self.FONT_SCALE)
            font = None
            if friz:
                try:
                    font = pygame.font.Font(friz, size)
                except (pygame.error, OSError):
                    font = None
            if font is None:
                font = pygame.font.SysFont("segoeui,arial,dejavusans", size + 1, bold=key in ("title", "huge"))
            else:
                self.using_game_font = True
            fonts[key] = font
        return fonts

    # La police du jeu (Friz Quadrata) ne contient que les caractères latins : on remplace les symboles
    _GLYPHS = (("⚙  ", ""), ("↻  ", ""), ("🎤  ", ""), ("▸ ", "> "), ("▾ ", "v "), ("→", "->"), ("•", "-"))

    def _glyphs(self, text):
        text = str(text)
        for old, new in self._GLYPHS:
            if old in text:
                text = text.replace(old, new)
        return text

    @property
    def ellipsis(self):
        return "..." if self.using_game_font else "…"

    def _build_background(self):
        # Texture personnalisée si elle existe et est valide (background.tga / png / jpg)
        for ext in ("tga", "png", "jpg"):
            path = os.path.join(WoWConfig.ADDON_TEXTURES_DIR or "", f"background.{ext}")
            if os.path.isfile(path):
                try:
                    image = pygame.image.load(path).convert()
                    image = pygame.transform.smoothscale(image, (self.W, self.H))
                    shade = pygame.Surface((self.W, self.H))
                    shade.set_alpha(150)
                    image.blit(shade, (0, 0))
                    return image
                except pygame.error:
                    pass   # fichier de remplacement non valide : dégradé par défaut
        surface = pygame.Surface((self.W, self.H))
        top, bottom = C["bg_top"], C["bg_bottom"]
        for y in range(self.H):
            t = y / self.H
            color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
            pygame.draw.line(surface, color, (0, y), (self.W, y))
        return surface

    # ================================================================== outils publics (utilisés par tabs.py)
    def color(self, color):
        return C[color] if isinstance(color, str) else color

    def text(self, text, font, color, pos, anchor="topleft", shadow=False, raw=False):
        """Affiche un texte (traduit si l'interface est en anglais ; `raw` : saisie de l'utilisateur, telle quelle)."""
        color = self.color(color)
        text = self._glyphs(text if raw else i18n.tr(text))
        surface = self.fonts[font].render(text, True, color)
        rect = surface.get_rect(**{anchor: pos})
        if self._track_y is not None:
            self._track_y = max(self._track_y, rect.bottom)
        if shadow:
            self.screen.blit(self.fonts[font].render(text, True, (0, 0, 0)), rect.move(1, 1))
        self.screen.blit(surface, rect)
        return rect

    def width(self, text, font):
        """Largeur à l'écran d'un libellé, une fois traduit (pour dimensionner boutons et onglets)."""
        return self.fonts[font].size(self._glyphs(i18n.tr(text)))[0]

    def fit(self, text, font, max_width, raw=False):
        f = self.fonts[font]
        text = self._glyphs(text if raw else i18n.tr(text))
        if f.size(text)[0] <= max_width:
            return text
        dots = self.ellipsis
        while text and f.size(text + dots)[0] > max_width:
            text = text[:-1]
        return text + dots

    def wrap(self, text, font, width):
        lines, current = [], ""
        for word in self._glyphs(i18n.tr(text)).split(" "):
            test = (current + " " + word).strip()
            if not current or self.fonts[font].size(test)[0] <= width:
                current = test
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def frame(self, rect, title=None):
        """Cadre à bordure métallique, comme les fenêtres du jeu."""
        x, y, w, h = rect
        pygame.draw.rect(self.screen, C["frame_lo"], (x - 2, y - 2, w + 4, h + 4), border_radius=7)
        pygame.draw.rect(self.screen, C["frame"], (x - 1, y - 1, w + 2, h + 2), 2, border_radius=7)
        pygame.draw.rect(self.screen, C["panel"], (x + 1, y + 1, w - 2, h - 2), border_radius=6)
        pygame.draw.line(self.screen, C["frame_hi"], (x + 6, y), (x + w - 6, y), 1)
        if title:
            self.header((x + 10, y + 8, w - 20, 26), title)

    def header(self, rect, text):
        """Bandeau de section (titre doré centré)."""
        x, y, w, h = rect
        pygame.draw.rect(self.screen, C["header"], rect, border_radius=6)
        pygame.draw.rect(self.screen, C["header_border"], rect, 1, border_radius=6)
        self.text(text, "medium", "gold", (x + w // 2, y + h // 2), anchor="center", shadow=True)

    def bar(self, rect, percent, fill, back):
        x, y, w, h = rect
        pygame.draw.rect(self.screen, back, rect, border_radius=4)
        if percent > 0:
            pygame.draw.rect(self.screen, fill, (x, y, max(4, int(w * min(percent, 100) / 100)), h), border_radius=4)
        pygame.draw.rect(self.screen, C["frame"], rect, 1, border_radius=4)

    def _register(self, bucket, rect, payload):
        rect = pygame.Rect(rect)
        visible = rect.clip(self._clip) if self._clip else rect
        if visible.w > 0 and visible.h > 0:
            bucket.append((visible, payload))

    def click(self, rect, fn):
        """Zone cliquable (clic gauche)."""
        self._register(self._buttons, rect, fn)

    def tip(self, rect, tip):
        """Infobulle au survol : dict {'rows': [(texte, couleur, texte_droit)], 'border': couleur, 'footer': texte}
        ou fonction qui le renvoie (calculé seulement au survol)."""
        self._register(self._tips, rect, tip)

    def link(self, rect, url):
        if url:
            self.click(rect, lambda u=url: self._open_url(u))

    def pill(self, rect, label, active, fn, font="small"):
        """Petit bouton / sous-onglet."""
        rect = pygame.Rect(rect)
        if self._track_y is not None:
            self._track_y = max(self._track_y, rect.bottom)
        hover = rect.collidepoint(self.mouse_pos())
        pygame.draw.rect(self.screen, (44, 40, 30) if active else (28, 28, 33), rect, border_radius=5)
        pygame.draw.rect(self.screen, C["gold"] if active else (C["frame_hi"] if hover else C["frame"]), rect,
                         2 if active else 1, border_radius=5)
        self.text(self.fit(label, font, rect.w - 12), font, "text" if active else "light_gray", rect.center,
                  anchor="center")
        self.click(rect, fn)

    def icon(self, kind, ident, rect, border=None, fallback=""):
        """Icône (objet, sort, haut fait) dans rect ; repère coloré tant qu'elle n'est pas disponible."""
        rect = pygame.Rect(rect)
        surf = self.icons.get(ident, rect.w - 4, kind) if ident else None
        pygame.draw.rect(self.screen, (9, 9, 12), rect, border_radius=4)
        if surf:
            self.screen.blit(surf, (rect.x + 2, rect.y + 2))
        elif fallback:
            self.text(fallback[:2].upper(), "small", border or C["gray"], rect.center, anchor="center")
        pygame.draw.rect(self.screen, border or C["frame"], rect, 2, border_radius=4)

    # ------------------------------------------------------------------ zones de découpe (clip)
    def clip_push(self, rect):
        rect = pygame.Rect(rect)
        if self._clip is not None:
            rect = rect.clip(self._clip)
        self._clip_stack.append(self._clip)
        self._clip = rect
        self.screen.set_clip(rect)

    def clip_pop(self):
        self._clip = self._clip_stack.pop() if self._clip_stack else None
        self.screen.set_clip(self._clip)

    # ------------------------------------------------------------------ défilement
    def scroll_begin(self, key, rect, content_h):
        """Ouvre une zone défilante ; retourne l'ordonnée où dessiner le contenu."""
        rect = pygame.Rect(rect)
        max_scroll = max(0, int(content_h - rect.h))
        offset = max(0, min(self.scroll.get(key, 0), max_scroll))
        self.scroll[key] = offset
        self._scroll_regions.append((rect, key, max_scroll))
        self.clip_push(rect)
        self._scrollbar = (rect, content_h, offset) if max_scroll else None
        return rect.y - offset

    def scroll_end(self):
        self.clip_pop()
        if self._scrollbar:
            rect, content_h, offset = self._scrollbar
            key = self._scroll_regions[-1][1]
            track = pygame.Rect(rect.right - 12, rect.y, 10, rect.h)
            thumb_h = max(30, int(rect.h * rect.h / content_h))
            thumb_y = rect.y + int((rect.h - thumb_h) * offset / max(1, content_h - rect.h))
            thumb = pygame.Rect(track.x, thumb_y, 10, thumb_h)
            hovered = thumb.collidepoint(self.mouse_pos()) or (self._drag and self._drag["key"] == key)
            pygame.draw.rect(self.screen, (30, 30, 36), track, border_radius=5)
            pygame.draw.rect(self.screen, C["gold"] if hovered else C["frame_hi"], thumb, border_radius=5)
            # zone d'accroche élargie : glisser la poignée, ou cliquer dans la piste pour y sauter
            self._scrollbars.append({"hit": pygame.Rect(rect.right - 18, rect.y, 18, rect.h), "key": key,
                                     "track": track, "thumb": thumb, "max": content_h - rect.h})
        self._scrollbar = None

    # ------------------------------------------------------------------ saisie
    def input_box(self, rect, key, placeholder, mask=False):
        rect = pygame.Rect(rect)
        if self._track_y is not None:
            self._track_y = max(self._track_y, rect.bottom)
        focused = self.focus == key
        pygame.draw.rect(self.screen, (10, 10, 14), rect, border_radius=4)
        pygame.draw.rect(self.screen, C["gold"] if focused else C["frame"], rect, 1, border_radius=4)
        value = self.inputs.get(key, "")
        (self._masked.add if mask else self._masked.discard)(key)
        shown = "•" * len(value) if mask else value
        start = 0
        if focused and self._focus_prev != key:      # le champ vient de recevoir la saisie (clic, pré-remplissage) :
            self._caret = (key, len(value))          # curseur à la fin
            self._focus_prev = key
        elif not focused and self._focus_prev == key:
            self._focus_prev = None
        if focused:
            # le texte défile pour que le curseur reste visible, même dans un champ plus court que le texte
            font, inner = self.fonts["small"], rect.w - 18
            width = lambda s: font.size(self._glyphs(s))[0]
            caret = self._caret_pos(key)
            while start < caret and width(shown[start:caret]) > inner:
                start += 1
            end = len(shown)
            while end > caret and width(shown[start:end]) > inner:
                end -= 1
            visible = shown[start:end]
            mid = rect.y + rect.h // 2
            if self.select_all == key and visible:
                pygame.draw.rect(self.screen, (58, 78, 120), (rect.x + 6, rect.y + 5, width(visible) + 4, rect.h - 10), border_radius=3)
            if visible:
                self.text(visible, "small", "text", (rect.x + 8, mid), anchor="midleft", raw=True)
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                cx = rect.x + 8 + width(shown[start:caret])
                pygame.draw.line(self.screen, C["gold"], (cx, rect.y + 6), (cx, rect.bottom - 7), 1)
        elif value:
            self.text(self.fit(shown, "small", rect.w - 16, raw=True), "small", "text",
                      (rect.x + 8, rect.y + rect.h // 2), anchor="midleft", raw=True)
        else:
            self.text(placeholder, "small", "gray", (rect.x + 8, rect.y + rect.h // 2), anchor="midleft")
        self._input_rects[key] = (self.cur, rect.copy(), self._frame, start)
        self.click(rect, lambda k=key: self._focus_input(k, self.mouse_pos()[0]))
        return value.strip().lower()

    # ------------------------------------------------------------------ saisie : curseur, presse-papier, menu
    def _caret_pos(self, key):
        """Position du curseur dans le champ (à la fin du texte si le champ vient de recevoir la saisie)."""
        text = self.inputs.get(key, "")
        if self._caret[0] != key:
            self._caret = (key, len(text))
        return max(0, min(self._caret[1], len(text)))

    def _focus_input(self, key, mouse_x=None):
        """Donne la saisie au champ ; un clic place le curseur à l'endroit cliqué."""
        self.focus = key
        self.select_all = None
        text = self.inputs.get(key, "")
        index = len(text)
        entry = self._input_rects.get(key)
        if mouse_x is not None and entry:
            _win, rect, _frame, start = entry
            shown = "•" * len(text) if key in self._masked else text
            font = self.fonts["small"]
            index = start
            while index < len(shown):
                left = font.size(self._glyphs(shown[start:index]))[0]
                right = font.size(self._glyphs(shown[start:index + 1]))[0]
                if rect.x + 8 + (left + right) / 2 >= mouse_x:
                    break
                index += 1
        self._caret = (key, index)
        self._focus_prev = key

    def _input_limit(self, key):
        return 400 if key == "llm_msg" else 200

    def _set_input(self, key, text, caret):
        self.inputs[key] = text
        self._caret = (key, max(0, min(caret, len(text))))
        self.select_all = None
        self.scroll.clear()

    def edit_action(self, action, key=None):
        """Couper / Copier / Coller / Tout sélectionner sur un champ (raccourcis clavier et menu du clic droit)."""
        key = key or self.focus
        if not key:
            return
        self.focus = key
        text = self.inputs.get(key, "")
        caret = self._caret_pos(key)
        if action == "select_all":
            self.select_all = key if text else None
        elif action in ("copy", "cut"):
            if text and key not in self._masked:          # un champ masqué (clé API) n'est jamais copié
                clipboard.set_text(text)
                if action == "cut":
                    self._set_input(key, "", 0)
        elif action == "paste":
            pasted = "".join(ch if ch.isprintable() else " " for ch in clipboard.get_text().replace("\r\n", "\n")).strip()
            if not pasted:
                return
            if self.select_all == key:
                text, caret = "", 0
            pasted = pasted[:max(0, self._input_limit(key) - len(text))]
            self._set_input(key, text[:caret] + pasted + text[caret:], caret + len(pasted))

    _MENU_ITEMS = (("Couper", "cut"), ("Copier", "copy"), ("Coller", "paste"), ("Tout sélectionner", "select_all"))

    def _open_menu(self, pos):
        """Clic droit : ouvre le menu Couper / Copier / Coller sur le champ de saisie visé. True si un champ est visé."""
        for key, (win, rect, frame, _start) in self._input_rects.items():
            if win == self.cur and frame >= self._frame - 1 and rect.collidepoint(pos):
                if self.focus != key:
                    self._focus_input(key)
                w, h = 196, 8 + 28 * len(self._MENU_ITEMS)
                x = max(4, min(pos[0], self.W - w - 4))
                y = max(4, min(pos[1], self.H - h - 4))
                self._menu = {"win": self.cur, "key": key, "rect": pygame.Rect(x, y, w, h)}
                return True
        self._menu = None
        return False

    def _draw_menu(self):
        m = self._menu
        if not m or m["win"] != self.cur:
            return
        rect, key = m["rect"], m["key"]
        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, (18, 18, 24), rect, border_radius=6)
        pygame.draw.rect(self.screen, C["gold"], rect, 1, border_radius=6)
        self.click(rect, lambda: None)                       # un clic dans le menu ne traverse pas vers ce qui est dessous
        has_text = bool(self.inputs.get(key, ""))
        mouse = self.mouse_pos()
        for i, (label, action) in enumerate(self._MENU_ITEMS):
            item = pygame.Rect(rect.x + 4, rect.y + 4 + i * 28, rect.w - 8, 28)
            enabled = (action == "paste" or (has_text and (action == "select_all" or key not in self._masked)))
            if enabled and item.collidepoint(mouse):
                pygame.draw.rect(self.screen, (48, 48, 60), item, border_radius=4)
            self.text(label, "small", "text" if enabled else "gray", (item.x + 10, item.centery), anchor="midleft")
            if enabled:
                self.click(item, lambda a=action, k=key: self.edit_action(a, k))

    # ------------------------------------------------------------------ graphique
    def chart(self, rect, points, color, fmt, title):
        """Courbe simple. points = [(timestamp, valeur)] triés par temps."""
        import time as _time
        x, y, w, h = rect
        points = sorted(points)   # par date croissante
        self.frame(rect, title)
        plot = pygame.Rect(x + 70, y + 46, w - 90, h - 82)
        if len(points) < 2:
            self.text("Pas encore assez de données (au moins 2 points)", "small", "gray", plot.center, anchor="center")
            return
        t0, t1 = points[0][0], points[-1][0]
        values = [p[1] for p in points]
        vmin, vmax = min(values), max(values)
        if vmax == vmin:
            vmin, vmax = vmin - 1, vmax + 1
        pad = (vmax - vmin) * 0.1
        vmin, vmax = vmin - pad, vmax + pad
        for i in range(5):
            gy = plot.y + int(plot.h * i / 4)
            pygame.draw.line(self.screen, (34, 34, 40), (plot.x, gy), (plot.right, gy), 1)
            value = vmax - (vmax - vmin) * i / 4
            self.text(fmt(value), "tiny", "gray", (plot.x - 8, gy), anchor="midright")
        coords = []
        for t, v in points:
            px = plot.x + int(plot.w * (t - t0) / max(1, t1 - t0))
            py = plot.bottom - int(plot.h * (v - vmin) / (vmax - vmin))
            coords.append((px, py))
        pygame.draw.lines(self.screen, color, False, coords, 2)
        for c in coords[-60:]:
            pygame.draw.circle(self.screen, color, c, 3)
        self.text(_time.strftime("%d/%m %H:%M", _time.localtime(t0)), "tiny", "gray", (plot.x, plot.bottom + 8))
        self.text(_time.strftime("%d/%m %H:%M", _time.localtime(t1)), "tiny", "gray", (plot.right, plot.bottom + 8),
                  anchor="topright")
        last_t, last_v = points[-1]
        self.text(fmt(last_v), "small", color, (plot.right, y + 14), anchor="topright")

    # ================================================================== pièces jointes, notifications, micro
    def draw_attachments(self, x, y, width, measure_only=False):
        """Rangée de miniatures des captures jointes (avec bouton de retrait). Retourne la hauteur utilisée (0 si aucune)."""
        vision = self.vision
        if not vision or not vision.attachments:
            return 0
        if measure_only:
            return 62
        px = x
        for i, att in enumerate(list(vision.attachments)):
            thumb = att.thumb_surface((96, 54))
            rect = pygame.Rect(px, y, thumb.get_width(), thumb.get_height())
            self.screen.blit(thumb, rect)
            pygame.draw.rect(self.screen, C["gold"], rect, 1)
            close = pygame.Rect(rect.right - 16, rect.y, 16, 16)
            pygame.draw.rect(self.screen, (20, 20, 24), close)
            pygame.draw.line(self.screen, C["light_gray"], (close.x + 4, close.y + 4), (close.right - 4, close.bottom - 4), 1)
            pygame.draw.line(self.screen, C["light_gray"], (close.x + 4, close.bottom - 4), (close.right - 4, close.y + 4), 1)
            self.click(close, lambda n=i: vision.remove(n))
            px += rect.w + 8
            if px > x + width - 130:
                break
        self.text(f"{len(vision.attachments)} image(s) jointe(s)", "tiny", "gray", (px + 4, y + 20))
        return 62

    def _draw_toasts(self):
        """Notification : nouvelle image détectée dans le presse-papier (Win + Maj + S)."""
        vision = self.vision
        toast = vision.active_toast() if vision else None
        if toast is None:
            return
        rect = pygame.Rect(self.W - 410, 64 if self.mode == "app" else 52, 390, 118)
        self.frame(rect)
        self.text("Capture détectée dans le presse-papier", "small", "gold", (rect.x + 14, rect.y + 10))
        thumb = toast.thumb_surface((128, 72))
        self.screen.blit(thumb, (rect.x + 14, rect.y + 34))
        pygame.draw.rect(self.screen, C["frame_hi"], (rect.x + 14, rect.y + 34, thumb.get_width(), thumb.get_height()), 1)
        self.text("La joindre à votre prochaine question ?", "tiny", "light_gray", (rect.x + 156, rect.y + 38))

        def accept():
            vision.accept_toast()
            self.notify("Capture jointe à votre prochaine question")
            if "after_attach" in self.actions:
                self.actions["after_attach"]()
        self.pill((rect.x + 156, rect.y + 62, 100, 30), "Joindre", True, accept, font="tiny")
        self.pill((rect.x + 264, rect.y + 62, 100, 30), "Ignorer", False, vision.dismiss_toast, font="tiny")

    def _draw_voice_chip(self):
        """État du micro (écoute, transcription, lecture) avec niveau sonore."""
        voice = self.voice
        if not voice or (voice.status == "off" and not voice.error):
            return
        status = voice.status
        text = "Micro indisponible — détails : Paramètres > Voix" if status == "error" else voice.STATUS_LABELS[status]
        if status == "idle":
            key = self.settings.get("voice.ptt_key", "F8") if self.settings else "F8"
            text += (f" · maintenir {key}" if voice.mode == "ptt" else " · activation vocale")
        color = {"listening": C["red"], "transcribing": C["orange"], "speaking": C["blue"], "error": C["red"]}.get(status, C["green"])
        width = max(210, min(self.W - 40, self.width(text, "tiny") + 90))
        rect = (pygame.Rect(300, 12, width, 28) if self.mode == "app" else pygame.Rect(20, self.H - 44, width, 28))
        pygame.draw.rect(self.screen, (16, 16, 20), rect, border_radius=14)
        pygame.draw.rect(self.screen, color, rect, 1, border_radius=14)
        pygame.draw.circle(self.screen, color, (rect.x + 14, rect.centery), 5)
        self.text(self.fit(text, "tiny", width - 90), "tiny", "text", (rect.x + 26, rect.centery), anchor="midleft")
        meter = pygame.Rect(rect.right - 54, rect.centery - 4, 44, 8)
        pygame.draw.rect(self.screen, (40, 40, 46), meter, border_radius=3)
        pygame.draw.rect(self.screen, color, (meter.x, meter.y, int(meter.w * min(1.0, voice.level * 2)), meter.h), border_radius=3)

    # ================================================================== fenêtres : application + overlay
    OVERLAY_TITLE = "WoW Assistant - overlay"
    _CTX_KEYS = ("screen", "W", "H", "_buttons", "_tips", "_scroll_regions", "_scrollbars", "_clip_stack", "_clip", "_drag")

    @property
    def mode(self):
        """Fenêtre en cours de traitement : "app" (onglets) ou "overlay" (widgets transparents)."""
        return self.cur

    @property
    def modal(self):
        return self._modals.get(self.cur)

    @modal.setter
    def modal(self, value):
        if value is None:
            self._modals.pop(self.cur, None)
        else:
            self._modals[self.cur] = value

    def any_modal(self, kind):
        """(fenêtre, modale) de la première modale du type demandé, ou (None, None)."""
        for name in ("app", "overlay"):
            m = self._modals.get(name)
            if m and m["type"] == kind:
                return name, m
        return None, None

    def use(self, name):
        """Bascule le contexte de dessin/événements sur la fenêtre « app » ou « overlay »."""
        if name == self.cur:
            return
        if name == "overlay" and not self._ctx_store.get("overlay"):
            return
        self._ctx_store[self.cur] = {k: getattr(self, k) for k in self._CTX_KEYS}
        self.cur = name
        for k, v in self._ctx_store[name].items():
            setattr(self, k, v)

    def mouse_pos(self):
        """Position de la souris dans la fenêtre courante (hors de la fenêtre : très loin)."""
        if self.cur == "overlay":
            return self._ov_mouse or (-9999, -9999)
        if self._ov_mouse is None or pygame.mouse.get_focused():
            return pygame.mouse.get_pos()
        return (-9999, -9999)

    def open_overlay(self, size, pos, opacity=100):
        """Ouvre l'overlay dans une 2e fenêtre : la fenêtre principale reste telle quelle, sur son écran."""
        size = (max(200, int(size[0])), max(150, int(size[1])))
        pos = (int(pos[0]), int(pos[1]))
        self.use("app")
        try:
            from pygame._sdl2.video import Renderer, Window
            if self.overlay_win is None:
                win = Window(self.OVERLAY_TITLE, size=size, position=pos, borderless=True)
                try:
                    ren = Renderer(win, accelerated=0)      # rendu logiciel : compatible avec la transparence Windows
                except Exception:
                    ren = Renderer(win)
                self.overlay_win, self.overlay_ren = win, ren
            else:
                self.overlay_win.size = size
                self.overlay_win.position = pos
            self.overlay_win.show()
        except Exception as e:
            self.overlay_error = f"Overlay impossible : {e}"
            self.overlay_on = False
            return False
        surface = pygame.Surface(size).convert()
        surface.fill(overlay_win.COLOR_KEY)
        self._ctx_store["overlay"] = {"screen": surface, "W": size[0], "H": size[1], "_buttons": [], "_tips": [],
                                      "_scroll_regions": [], "_scrollbars": [], "_clip_stack": [], "_clip": None,
                                      "_drag": None}
        self.overlay_hwnd = overlay_win.find_window(self.OVERLAY_TITLE)
        self.overlay_active = overlay_win.apply_overlay_style(self.overlay_hwnd, opacity)
        self.overlay_on = self.overlay_visible = True
        self.overlay_error = ""
        if self.manager:
            self.manager.set_screen_size(size)
        return True

    def close_overlay(self):
        self.use("app")
        self._modals.pop("overlay", None)
        self.overlay_on = False
        if self.overlay_win is not None:
            try:
                self.overlay_win.hide()
            except Exception:
                pass

    def set_overlay_visible(self, visible):
        self.overlay_visible = bool(visible)
        if self.overlay_win is not None and self.overlay_on:
            try:
                (self.overlay_win.show if visible else self.overlay_win.hide)()
                if visible:
                    overlay_win.set_topmost(self.overlay_hwnd, True)
            except Exception:
                pass

    def set_overlay_opacity(self, opacity):
        if self.overlay_on:
            overlay_win.apply_overlay_style(getattr(self, "overlay_hwnd", None), opacity)

    def move_overlay(self, pos):
        """Déplace la fenêtre overlay (suit la fenêtre de WoW)."""
        try:
            self.overlay_win.position = (int(pos[0]), int(pos[1]))
        except Exception:
            pass

    def raise_app(self):
        """Remet la fenêtre principale au premier plan."""
        try:
            from pygame._sdl2.video import Window
            win = Window.from_display_module()
            win.restore()
            win.focus()
        except Exception:
            pass

    def app_window_position(self):
        try:
            from pygame._sdl2.video import Window
            return tuple(Window.from_display_module().position)
        except Exception:
            return None

    def move_app(self, pos):
        try:
            from pygame._sdl2.video import Window
            Window.from_display_module().position = (int(pos[0]), int(pos[1]))
        except Exception:
            pass

    def set_mode(self, mode, size=None, pos=None, opacity=100):
        """Compatibilité : "overlay" ouvre l'overlay (2e fenêtre), "app" le ferme."""
        if mode == "overlay":
            size = size or pygame.display.get_desktop_sizes()[0]
            return self.open_overlay(size, pos or (0, 0), opacity)
        self.close_overlay()
        return True

    def draw_overlay(self, ctx):
        """Dessine uniquement les widgets sur fond transparent (couleur-clé) dans la fenêtre overlay."""
        if not self.overlay_on or not self._ctx_store.get("overlay"):
            return
        self.use("overlay")
        try:
            self.ctx = ctx
            self.screen.set_clip(None)
            self.screen.fill(overlay_win.COLOR_KEY)
            self._buttons, self._tips, self._scroll_regions, self._scrollbars = [], [], [], []
            self._clip_stack, self._clip = [], None
            mouse = self.mouse_pos()
            if self.manager:
                self.manager.draw(self, ctx)
            self._draw_toasts()
            self._draw_voice_chip()
            if self.modal:
                self._buttons, self._tips, self._scroll_regions, self._scrollbars = [], [], [], []
                self._draw_modal()
            self._draw_menu()
            for rect, tip in reversed(self._tips):
                if rect.collidepoint(mouse) and not self._menu:
                    self._draw_tip(tip() if callable(tip) else tip, mouse)
                    break
            self._present_overlay()
        finally:
            self.use("app")

    def _present_overlay(self):
        if not (self.overlay_visible and self.overlay_ren):
            return
        try:
            from pygame._sdl2.video import Texture
            texture = Texture.from_surface(self.overlay_ren, self.screen)
            self.overlay_ren.clear()
            texture.draw()
            self.overlay_ren.present()
        except Exception as e:
            self.overlay_error = f"Affichage de l'overlay : {e}"

    # ================================================================== image complète
    def draw(self, ctx):
        self.ctx = ctx
        self._frame += 1
        self.screen.blit(self.background, (0, 0))
        self._buttons, self._tips, self._scroll_regions = [], [], []
        self._clip = None
        self._view3d = self._embed = None
        mouse = self.mouse_pos()

        self.text("WoW Assistant", "huge", "gold", (28, 12), shadow=True)
        flavor = features.flavor()
        if flavor != "retail":
            self.text(features.label(), "medium", "label", (self.fonts["huge"].size("WoW Assistant")[0] + 44, 22))
        pygame.draw.line(self.screen, C["header_border"], (24, 50), (self.W - 24, 50), 1)

        self._scrollbars = []
        rect = pygame.Rect(20, self.TOP, self.W - 40, self.BOTTOM - self.TOP)
        if self.active_tab == 0:
            self._draw_dashboard(ctx)
        else:
            tabs.DRAWERS[self.active_tab](self, ctx, rect)
        self._draw_tab_bar(ctx)
        self._draw_toasts()
        self._draw_voice_chip()
        self._sync_view3d()

        if self.modal:
            self._buttons, self._tips, self._scroll_regions, self._scrollbars = [], [], [], []
            self._draw_modal()
        self._draw_menu()
        for rect, tip in reversed(self._tips):
            if rect.collidepoint(mouse) and not self._menu:
                self._draw_tip(tip() if callable(tip) else tip, mouse)
                break

    # ------------------------------------------------------------------ barre d'onglets + état
    def _draw_tab_bar(self, ctx):
        x, y = 24, self.BOTTOM + 8
        # les onglets tiennent sur la largeur : marges réduites, puis police plus petite si besoin
        available = self.W - 48 - 5 * (len(self.TABS) - 1)
        font, pad, min_w = "small", 26, 92
        for font, pad, min_w in (("small", 26, 92), ("small", 16, 70), ("small", 10, 56), ("tiny", 10, 48)):
            if sum(max(min_w, self.width(n, font) + pad) for n in self.TABS) <= available:
                break
        for index, name in enumerate(self.TABS):
            width = max(min_w, self.width(name, font) + pad)
            active = index == self.active_tab
            rect = pygame.Rect(x, y - (4 if active else 0), width, 38 if active else 34)
            pygame.draw.rect(self.screen, (34, 32, 26) if active else (22, 22, 26), rect,
                             border_bottom_left_radius=6, border_bottom_right_radius=6)
            pygame.draw.rect(self.screen, C["gold"] if active else C["frame"], rect, 2 if active else 1,
                             border_bottom_left_radius=6, border_bottom_right_radius=6)
            self.text(name, font, "text" if active else "gray", rect.center, anchor="center", shadow=True)
            self.click(rect, lambda i=index: self._switch_tab(i))
            x += width + 5

        # en-tête : état de la synchronisation (à gauche des boutons de l'onglet Personnage)
        right_edge = self.W - 24
        if self.active_tab == 0:
            right_edge = self._draw_header_buttons()
        ry = 8
        for i, line in enumerate(getattr(ctx, "status_lines", None) or []):
            self.text(self.fit(line, "small", max(200, right_edge - 360)), "small", "gray" if i == 0 else "orange",
                      (right_edge, ry), anchor="topright")
            ry += 20
        note, until = self.refresh_note
        if note and time.time() < until:
            self.text(note, "small", "green", (right_edge, ry), anchor="topright")
        ids = [it["id"] for it in ctx.character.equipment.values()]
        if ids:
            ready, total = self.icons.stats(ids)
            self.text(f"Icônes équipement : {ready}/{total}", "tiny", "gray",
                      (self.W - 24, self.H - 18), anchor="topright")

    def _draw_header_buttons(self):
        """Onglet Personnage : Overlay + Actualiser + Paramètres généraux, en haut à droite. Retourne le bord gauche utilisé."""
        settings_rect = pygame.Rect(self.W - 24 - 210, 10, 210, 34)
        refresh_rect = pygame.Rect(settings_rect.x - 8 - 130, 10, 130, 34)
        overlay_rect = pygame.Rect(refresh_rect.x - 8 - 150, 10, 150, 34)
        self.pill(settings_rect, "Paramètres généraux", False, self.open_settings, font="small")
        self.pill(refresh_rect, "Actualiser", False, lambda: setattr(self, "refresh_requested", True), font="small")
        self.pill(overlay_rect, "Mode overlay", False, lambda: self.actions["to_overlay"]() if "to_overlay" in self.actions else None,
                  font="small")
        self.tip(refresh_rect, {"rows": [("Relit le fichier de l'addon tout de suite.", C["light_gray"], ""),
                                          ("WoW n'écrit ses données qu'au /reload ou /ha save.", C["gray"], "")]})
        self.tip(overlay_rect, {"rows": [("Fenêtre transparente au premier plan avec des widgets déplaçables.", C["light_gray"], ""),
                                          ("Raccourcis globaux (Windows) : voir Paramètres généraux > Overlay.", C["gray"], "")]})
        return overlay_rect.x - 16

    def _draw_raidbots_buttons(self, rect):
        """Cadre d'équipement : « Profil Raidbots » / « Résultat Raidbots » (simc.py). Absent sur Forever."""
        if not features.has("raidbots"):
            return
        x, y, w, h = rect
        half = (w - 6) // 2
        simc_rect, paste_rect = pygame.Rect(x, y, half, h), pygame.Rect(x + half + 6, y, w - half - 6, h)
        self.pill(simc_rect, "Profil Raidbots", False, self.copy_simc_profile, font="tiny")
        self.pill(paste_rect, "Résultat Raidbots", False, self.paste_raidbots_result, font="tiny")
        self.tip(simc_rect, {"rows": [("Copie votre profil SimulationCraft (équipement porté, talents)", C["light_gray"], ""),
                                       ("et ouvre raidbots.com : collez-le dans Droptimizer ou Top Gear.", C["gray"], "")]})
        self.tip(paste_rect, {"rows": [("Sur le rapport Raidbots : Ctrl+A, Ctrl+C, puis cliquez ici :", C["light_gray"], ""),
                                        ("gardé dans les connaissances du coach et analysé par Hermes.", C["gray"], "")]})

    def copy_simc_profile(self):
        import clipboard
        import simc
        region = (self.settings.get("bnet.region") if self.settings else "") or "eu"
        text = simc.profile(getattr(self, "last_snapshot", None) or {}, region=region)
        if not text:
            self.notify("Pas encore de données du personnage (/reload en jeu).")
            return
        try:
            clipboard.set_text(text)
        except Exception as e:                        # noqa: BLE001
            self.notify(f"Copie impossible : {e}")
            return
        self.notify("Profil SimulationCraft copié : collez-le sur raidbots.com (Droptimizer, Top Gear).", 8)
        self._open_url(simc.RAIDBOTS_URL)

    def paste_raidbots_result(self):
        import clipboard
        import simc
        try:
            text = clipboard.get_text() or ""
        except Exception:                             # noqa: BLE001
            text = ""
        if not simc.looks_like_result(text):
            self.notify("Copiez d'abord la page du rapport Raidbots (Ctrl+A puis Ctrl+C dans le navigateur).", 8)
            return
        text = text.strip()[:6000]
        link = simc.report_link(text)
        kb = getattr(self, "knowledge", None)
        if kb is not None:
            when = time.strftime("%d/%m/%Y")
            kb.add("équipement", f"Simulation Raidbots du {when}", text[:1100], source=link or "joueur",
                   status="joueur")
        chat = getattr(self, "chat", None)
        if chat is not None and chat.uses_hermes() and "Hermes" in self.TABS:
            import chatview
            if chatview.send_from(self, chat, "hermes_msg", simc.RESULT_PROMPT + text):
                self._switch_tab(self.TABS.index("Hermes"))
                return
        self.ask_assistant("Simulation Raidbots", simc.RESULT_PROMPT + text)

    def set_language(self, code):
        """Français ou anglais : appliqué tout de suite, gardé dans settings.json."""
        i18n.load(code)
        if self.settings is not None:
            self.settings.set("ui.language", code)
            self.settings.save()
        self.notify("Langue : français." if code == "fr" else "Language: English.")

    def notify(self, text, seconds=5):
        self.refresh_note = (text, time.time() + seconds)

    def _switch_tab(self, index):
        self.active_tab = index
        self.focus = None

    # ================================================================== onglet Personnage
    def _draw_dashboard(self, ctx):
        c = ctx.character
        self._draw_character(c, (20, self.TOP, 460, 300))
        self._draw_professions(ctx.craft, (20, self.TOP + 310, 460, 200))
        self._draw_session(ctx.session, (20, self.TOP + 520, 460, self.BOTTOM - self.TOP - 520))
        self._draw_sheet(c, (972, self.TOP, 628, self.BOTTOM - self.TOP))
        self._draw_quests(ctx.quests, (496, self.TOP, 460, 400))
        self._draw_inventory(ctx.inventory, ctx.craft, (496, self.TOP + 410, 460, self.BOTTOM - self.TOP - 410))

    def _draw_character(self, c, rect):
        x, y, w, h = rect
        self.frame(rect)
        self.text(self.fit(c.name or "—", "title", w - 30), "title", c.class_color, (x + 16, y + 10), shadow=True)
        who = " ".join(part for part in (c.class_name, c.spec) if part)
        self.text(f"Niveau {c.level}  ·  {who}", "medium", "text", (x + 16, y + 52))
        line = f"{c.race or '—'}  ·  "
        self.text(line, "small", "light_gray", (x + 16, y + 82))
        offset = self.fonts["small"].size(line)[0]
        self.text(c.faction or "—", "small", c.faction_color, (x + 16 + offset, y + 82))
        if c.realm:
            self.text(c.realm, "small", "gray", (x + w - 16, y + 82), anchor="topright")

        self.bar((x + 16, y + 112, w - 32, 18), c.xp_percent, C["xp"], C["xp_back"])
        if c.xp_max:
            text = f"{c.xp:,} / {c.xp_max:,}  ({c.xp_percent:.0f} %)".replace(",", " ")
            if c.rested_xp:
                text += f"   repos : {c.rested_xp:,}".replace(",", " ")
        else:
            text = "Niveau maximum"
        self.text(text, "small", "light_gray", (x + 16, y + 134))

        gold, silver, cop = Character.split_money(c.money)
        self.text("Or", "small", "gray", (x + 16, y + 168))
        self.text(f"{gold:,} or".replace(",", " "), "medium", "gold", (x + 28 + self.width("Or", "small"), y + 164))
        self.text(f"{silver} arg  {cop} cu", "small", "light_gray", (x + 180, y + 168))
        self.text(self.fit(f"Zone : {c.location or '—'}", "small", w - 32), "small", "light_gray", (x + 16, y + 200))

        self.text("Temps de jeu", "small", "gray", (x + 16, y + 238))
        if c.played_total:
            self.text(format_duration(c.played_total), "medium", "text", (x + 130, y + 234))
            self.text(f"Ce niveau : {format_duration(c.played_level)}", "small", "light_gray", (x + 16, y + 266))
        else:
            self.text("en attente (reçu après la connexion en jeu)", "small", "gray", (x + 130, y + 238))

    def _draw_professions(self, craft, rect):
        x, y, w, h = rect
        self.frame(rect, "Métiers")
        py = y + 48
        if craft and craft.professions:
            for name, info in list(craft.professions.items())[:6]:
                level, maxl = info["level"], info.get("max_level", 0)
                self.text(self.fit(name, "small", 170), "small", "text", (x + 16, py))
                if maxl:
                    self.bar((x + 200, py + 3, 190, 12), 100 * level / maxl, C["green"], (28, 46, 32))
                self.text(f"{level}/{maxl}" if maxl else str(level), "small", "light_gray",
                          (x + w - 16, py), anchor="topright")
                py += 24
        else:
            self.text("Aucun métier détecté", "small", "gray", (x + 16, py))

    def _draw_session(self, session, rect):
        x, y, w, h = rect
        self.frame(rect, "Session")
        if session and (session["seconds"] or session["levels"] or session["money"]):
            money = session["money"]
            sign = "+" if money >= 0 else "-"
            gold, silver, _ = Character.split_money(abs(money))
            self.text(f"Or : {sign}{gold} or {silver} arg", "small", "green" if money >= 0 else "red", (x + 16, y + 48))
            self.text(f"Niveaux gagnés : {session['levels']}", "small", "light_gray", (x + 16, y + 72))
        else:
            self.text("Pas encore de changement depuis le lancement", "small", "gray", (x + 16, y + 48))

    def _draw_quests(self, tracker, rect):
        x, y, w, h = rect
        self.frame(rect, f"Quêtes ({tracker.count()}/{tracker.max_quests})")
        if not tracker.quests:
            self.text("Aucune quête dans le journal", "small", "gray", (x + 16, y + 48))
            return
        ready = len(tracker.ready_to_turn_in())
        if ready:
            self.text(f"{ready} à rendre", "small", "green", (x + w - 16, y + 40), anchor="topright")
        ordered = sorted(tracker.quests, key=lambda q: 0 if q["status"] == "complete" else 1)
        py = y + 62
        for quest in ordered[:12]:
            done, count = QuestTracker.progress(quest)
            color = {"complete": "green", "failed": "red"}.get(quest["status"], "text")
            self.text(self.fit(f"[{quest['level']}] {quest['name']}", "small", w - 290), "small", color, (x + 16, py))
            label = QuestTracker.status_label(quest)
            if count and quest["status"] == "incomplete":
                label = f"{done}/{count}"
            self.text(label, "small", color, (x + w - 250, py))
            self.text(self.fit(quest["zone"], "small", 120), "small", "gray", (x + w - 135, py))
            py += 26
        if len(tracker.quests) > 12:
            self.text(f"… et {len(tracker.quests) - 12} autres  (onglet Journal des quêtes)", "small", "gray", (x + 16, py))

    def _draw_inventory(self, inv, craft, rect):
        x, y, w, h = rect
        self.frame(rect, "Sacs")
        total = inv.capacity
        used = inv.slots_used if inv.slots_used is not None else inv.get_total_items()
        percent = 100 * used / total if total else 0
        self.bar((x + 16, y + 46, w - 32, 14), percent, C["red"] if percent >= 95 else C["green"], (28, 46, 32))
        self.text(f"{used}/{total} emplacements  ·  {inv.free_slots()} libres", "small", "light_gray", (x + 16, y + 66))
        py = y + 96
        for item in inv.top_items(6):
            color = QUALITY_COLORS.get(item.get("quality", 1), (255, 255, 255))
            self.text(self.fit(item["name"], "small", w - 130), "small", color, (x + 16, py))
            self.text(f"x{item['quantity']}", "small", "light_gray", (x + w - 16, py), anchor="topright")
            py += 22
        if craft is not None and craft.recipes:
            self.text(f"Recettes fabricables : {len(craft.craftable_recipes(inv))}", "small", "gold",
                      (x + 16, y + h - 28))

    # ------------------------------------------------------------------ fenêtre de personnage
    def _draw_sheet(self, c, rect):
        x, y, w, h = rect
        self.frame(rect)
        self.text(self.fit(c.display_title, "large", w - 40), "large", "text", (x + w // 2, y + 12),
                  anchor="midtop", shadow=True)
        self.text(self.fit(c.subtitle, "medium", w - 40), "medium", c.class_color, (x + w // 2, y + 42),
                  anchor="midtop", shadow=True)

        top = y + 84
        left_x = x + 14
        model_x = left_x + self.SLOT + 8
        model_w = 218
        right_x = model_x + model_w + 8
        stats_x = right_x + self.SLOT + 12
        stats_w = x + w - 14 - stats_x

        for row, (slot_id, label) in enumerate(EQUIPMENT_LAYOUT["left"]):
            self._draw_slot((left_x, top + row * self.PITCH), slot_id, label, c.equipment.get(slot_id))
        for row, (slot_id, label) in enumerate(EQUIPMENT_LAYOUT["right"]):
            self._draw_slot((right_x, top + row * self.PITCH), slot_id, label, c.equipment.get(slot_id))

        model_h = 8 * self.PITCH - (self.PITCH - self.SLOT)
        self._draw_model_placeholder((model_x, top, model_w, model_h), c)
        if c.name and c.realm:
            self.view3d_box((model_x, top, model_w, model_h), f"char:{c.realm}:{c.name}",
                            lambda: self.character_3d(c.realm, c.name))

        bottom_y = top + 8 * self.PITCH + 4
        weapons = EQUIPMENT_LAYOUT["bottom"]
        total_w = len(weapons) * self.SLOT + (len(weapons) - 1) * 10
        wx = model_x + (model_w - total_w) // 2
        for i, (slot_id, label) in enumerate(weapons):
            self._draw_slot((wx + i * (self.SLOT + 10), bottom_y), slot_id, label, c.equipment.get(slot_id))

        self._draw_stats((stats_x, top, stats_w, model_h + 70), c)
        self._draw_raidbots_buttons((stats_x, y + h - 42, stats_w, 28))

    def _draw_model_placeholder(self, rect, c):
        tint = tuple(int(v * 0.16) + 18 for v in c.class_color)
        if c.name and c.realm and self.media is not None and self.media.available():
            key = f"char:{c.realm}:{c.name}"
            self.media.request(key, lambda: self.media.bnet.character_render(c.realm, c.name))
            if self.media_view(rect, key, "Rendu officiel du personnage", tint, "person"):
                return
        self.model_placeholder(rect, "Modèle 3D", tint, shape="person")

    # ------------------------------------------------------------------ vue 3D (facultative)
    VIEW3D_STRIP = 28        # bandeau au-dessus de la vue incrustée (aide + bouton Image / 3D)

    def view3d_enabled(self):
        return bool(self.settings and self.settings.get("model3d.enabled", False) and self.viewer3d is not None
                    and self.media is not None and self.media.available())

    def view3d_embeddable(self):
        if self._can_embed is None:
            self._can_embed = bool(self.viewer3d is not None and self.viewer3d.can_embed() and self._main_hwnd())
        return self._can_embed

    def _main_hwnd(self):
        try:
            return pygame.display.get_wm_info().get("window")
        except pygame.error:
            return None

    def view3d_box(self, box, key, loader):
        """Vue 3D (option activée) sur le cadre d'un aperçu : incrustée dans la fenêtre (rotation à la souris, molette :
        zoom, Ctrl+clic : déplacer), sinon bouton qui ouvre la page dans le navigateur. Rien si l'option est coupée."""
        if not self.view3d_enabled():
            return
        box = pygame.Rect(box)
        self._view3d = (key, loader)
        if not self.view3d_embeddable():
            rect = (box.right - 84, box.y + 6, 78, 24)
            self.pill(rect, "Vue 3D", self.viewer3d.window_open(), self._open_view3d, font="tiny")
            self.tip(pygame.Rect(rect), {"rows": [("Vue 3D (visionneuse de Wowhead)", C["gold"], ""),
                                                  ("Ouvre la page dans le navigateur ; elle suit la sélection.",
                                                   C["light_gray"], "")]})
            return
        flat = bool(self.state.get("view3d_flat"))
        strip = pygame.Rect(box.x, box.y, box.w, self.VIEW3D_STRIP)
        if not flat:
            pygame.draw.rect(self.screen, (11, 11, 14), strip, border_top_left_radius=6, border_top_right_radius=6)
        if self.viewer3d.error:
            hint, color = "Vue 3D : " + self.viewer3d.error, "red"
        elif flat:
            hint, color = "", "gray"
        else:
            hint, color = ("Glisser : tourner  ·  molette : zoom  ·  Ctrl+glisser : déplacer" if box.w >= 420
                           else "Souris · molette · Ctrl"), "gray"
            self.tip(strip, {"rows": [("Vue 3D (visionneuse de Wowhead)", C["gold"], ""),
                                      ("Glisser : tourner · molette : zoom", C["light_gray"], ""),
                                      ("Ctrl + glisser : déplacer le modèle", C["light_gray"], "")]})
            self._embed = pygame.Rect(box.x + 1, box.y + self.VIEW3D_STRIP, box.w - 2, box.h - self.VIEW3D_STRIP - 1)
        if hint:
            self.text(self.fit(hint, "tiny", box.w - 100), "tiny", color, (box.x + 8, box.y + 7))
        pill = (box.right - 76, box.y + 3, 72, 22)
        self.pill(pill, "Image" if not flat else "3D", False,
                  lambda: self.state.update(view3d_flat=not self.state.get("view3d_flat")), font="tiny")
        self.tip(pygame.Rect(pill), {"rows": [("Image Battle.net" if not flat else "Vue 3D (Wowhead)", C["gold"], ""),
                                              ("Bascule entre l'image fixe et la vue 3D.", C["light_gray"], "")]})

    def _open_view3d(self):
        try:
            self.viewer3d.open_window()
        except OSError as e:
            self.notify(f"Vue 3D impossible : {e}")

    def character_3d(self, realm, name):
        import model3d
        return model3d.character_model(self.media.bnet, realm, name)

    def _sync_view3d(self):
        """En fin d'image : place (ou masque) la vue incrustée et lui donne le modèle de l'aperçu affiché."""
        if self.viewer3d is None:
            return
        embedded = False
        if self.view3d_embeddable():
            rect = None
            hwnd = self._main_hwnd()
            if self._embed is not None and not self.modal and not self._menu and self.view3d_enabled():
                import model3d
                rect = model3d.client_rect(hwnd, (self.W, self.H), self._embed)
            embedded = self.viewer3d.embed(hwnd, rect) or rect is not None
        if not self._view3d or not (embedded or self.viewer3d.window_open()):
            return
        key, loader = self._view3d
        media_key = "3d:" + key
        self.media.request(media_key, loader)
        model = self.media.value(media_key)
        if model:
            self.viewer3d.show(model)
        elif self.media.state(media_key) == "erreur":
            self.viewer3d.show({"kind": "none", "message": "Vue 3D : " + self.media.error(media_key)})
        else:
            self.viewer3d.show({"kind": "none", "message": "Chargement du modèle…"})

    def media_view(self, rect, key, caption, tint, shape="object"):
        """Image Battle.net dans un emplacement de modèle ; False si elle n'est pas affichable (placeholder alors
        dessiné ici avec l'état : chargement ou erreur)."""
        x, y, w, h = rect
        image = self.media.surface(key)
        if image is None:
            state = self.media.state(key)
            self.model_placeholder(rect, caption, tint, shape,
                                   note="chargement…" if state in ("en cours", "absente") else "indisponible")
            if state == "erreur":
                self.tip(pygame.Rect(rect), {"rows": [(self.media.error(key), C["orange"], "")],
                                             "footer": "Clic : réessayer"})
                self.click(pygame.Rect(rect), lambda: self.media.retry(key))
            return True
        pygame.draw.rect(self.screen, (8, 8, 11), rect, border_radius=4)
        cached = self._cache.get(("media", key, w, h))
        if cached is None:
            cached = self._cache[("media", key, w, h)] = fit_image(image, w - 8, h - 8)
        self.screen.blit(cached, (x + (w - cached.get_width()) // 2, y + (h - cached.get_height()) // 2))
        pygame.draw.rect(self.screen, C["frame_lo"], rect, 1, border_radius=4)
        self.text("Rendu Battle.net", "tiny", "gray", (x + w - 6, y + h - 4), anchor="bottomright")
        return True

    def model_placeholder(self, rect, caption="Modèle 3D", tint=(40, 40, 46), shape="object", note="à venir"):
        """Emplacement réservé au futur modèle 3D (personnage, monture, mascotte, objet...)."""
        x, y, w, h = rect
        pygame.draw.rect(self.screen, (8, 8, 11), rect, border_radius=4)
        pygame.draw.rect(self.screen, C["frame_lo"], rect, 1, border_radius=4)
        cx, cy = x + w // 2, y + h // 2 - 10
        scale = min(w, h) / 440
        if shape == "person":
            pygame.draw.circle(self.screen, tint, (cx, cy - int(110 * scale * 1.4)), int(34 * scale * 1.4))
            pygame.draw.polygon(self.screen, tint, [(cx - int(70 * scale * 1.4), cy + int(120 * scale * 1.4)),
                                                    (cx - int(46 * scale * 1.4), cy - int(70 * scale * 1.4)),
                                                    (cx + int(46 * scale * 1.4), cy - int(70 * scale * 1.4)),
                                                    (cx + int(70 * scale * 1.4), cy + int(120 * scale * 1.4))])
        else:
            r = int(min(w, h) * 0.22)
            pygame.draw.circle(self.screen, tint, (cx, cy), r)
            pygame.draw.circle(self.screen, tuple(min(255, v + 14) for v in tint), (cx, cy), r, 3)
        self.text(caption, "medium", "gray", (cx, y + h - 46), anchor="center")
        self.text(note, "small", "gray", (cx, y + h - 24), anchor="center")

    def detail_buttons(self, x, y, url, title, context):
        """Deux boutons standard : ouvrir sur Wowhead / envoyer à l'assistant (Hermes)."""
        if url:
            self.pill((x, y, 190, 32), "Ouvrir sur Wowhead", False, lambda u=url: self._open_url(u))
            x += 200
        self.pill((x, y, 210, 32), "Envoyer à Hermes", False,
                  lambda: self.ask_assistant(title, context, url))

    def _draw_slot(self, pos, slot_id, label, item, size=None):
        size = size or self.SLOT
        rect = pygame.Rect(pos[0], pos[1], size, size)
        pygame.draw.rect(self.screen, (9, 9, 12), rect, border_radius=4)
        if not item:
            pygame.draw.rect(self.screen, (52, 52, 58), rect, 1, border_radius=4)
            self.text(SLOT_SHORT.get(slot_id, label[:4]), "tiny", (78, 78, 86), rect.center, anchor="center")
            return
        quality = QUALITY_COLORS.get(item.get("quality", 1), (255, 255, 255))
        icon = self.icons.get(item["id"], size - 6)
        if icon:
            self.screen.blit(icon, (rect.x + 3, rect.y + 3))
        else:
            dark = tuple(int(v * 0.22) for v in quality)
            pygame.draw.rect(self.screen, dark, rect.inflate(-6, -6), border_radius=3)
            self.text((item.get("name") or label)[:2].upper(), "medium", quality, rect.center, anchor="center")
        pygame.draw.rect(self.screen, quality, rect, 2, border_radius=4)
        ilvl = item.get("ilvl")
        if ilvl:
            self.text(f"{int(ilvl)}", "tiny", (255, 255, 255), (rect.right - 4, rect.bottom - 3),
                      anchor="bottomright", shadow=True)
        self.tip(rect, lambda it=item: self._equipment_tip(it))
        self.link(rect, self.links.url_for(item))

    def _draw_stats(self, rect, c):
        x, y, w, _ = rect
        self.header((x, y, w, 28), "Niveau d'objet")
        pygame.draw.rect(self.screen, C["panel_alt"], (x, y + 32, w, 44), border_radius=4)
        self.text(f"{c.ilvl:g}", "title", "text", (x + w // 2, y + 54), anchor="center", shadow=True)

        y += 88
        label, value = c.primary_stat()
        self.header((x, y, w, 28), "Caractéristiques")
        y = self._stat_rows(x, y + 32, w, [
            (f"{label} :", f"{value}"),
            ("Endurance :", f"{c.get_stat('stamina')}"),
            ("Armure :", f"{c.armor}"),
        ])

        y += 12
        self.header((x, y, w, 28), "Améliorations")
        rows = [("Coup critique :", f"{c.crit:g}%"), ("Hâte :", f"{c.haste:g}%"),
                ("Maîtrise :", f"{c.mastery:g}%")]
        if c.versatility:
            rows.append(("Polyvalence :", f"{c.versatility:g}%"))
        self._stat_rows(x, y + 32, w, rows)

    def _stat_rows(self, x, y, w, rows):
        for i, (label, value) in enumerate(rows):
            if i % 2 == 0:
                pygame.draw.rect(self.screen, C["panel_alt"], (x, y, w, 24))
            self.text(label, "small", "label", (x + 8, y + 3))
            self.text(value, "small", "text", (x + w - 8, y + 3), anchor="topright")
            y += 24
        return y

    # ================================================================== infobulles
    def _equipment_tip(self, item):
        quality = QUALITY_COLORS.get(item.get("quality", 1), (255, 255, 255))
        rows = []
        for line in item.get("tooltip", []):
            rows.append((clean_wow_text(str(line.get("l", ""))), hex_to_rgb(line.get("c")),
                         clean_wow_text(str(line.get("r", "")))))
        if not rows:   # pas d'infobulle exportée : résumé minimal
            rows.append((item.get("name", ""), quality, ""))
            if item.get("ilvl"):
                rows.append((f"Niveau d'objet {int(item['ilvl'])}", C["gold"], ""))
            if item.get("maxDurability"):
                rows.append((f"Durabilité : {int(item.get('durability', 0))} / {int(item['maxDurability'])}",
                             C["text"], ""))
        url = self.links.url_for(item)
        return {"rows": rows, "border": quality, "footer": "Clic : ouvrir sur Wowhead" if url else ""}

    def _draw_tip(self, tip, mouse):
        max_w = 400
        font = self.fonts["small"]
        line_h = font.get_linesize() + 2
        rows = []
        for left, color, right in tip.get("rows", []):
            color = self.color(color)
            right = i18n.tr(right) if right else right
            right_w = font.size(right)[0] + 16 if right else 0
            for i, piece in enumerate(self.wrap(left, "small", max_w - right_w)):
                rows.append((piece, color, right if i == 0 else ""))
        footer = i18n.tr(tip.get("footer", ""))
        border = self.color(tip.get("border") or C["frame_hi"])

        width = 140
        for left, _, right in rows:
            width = max(width, font.size(left)[0] + (font.size(right)[0] + 24 if right else 0))
        width = min(width, max_w) + 20
        height = len(rows) * line_h + 16 + (line_h + 4 if footer else 0)

        tx, ty = mouse[0] + 18, mouse[1] + 14
        if tx + width > self.W - 8:
            tx = mouse[0] - width - 14
        if ty + height > self.H - 8:
            ty = self.H - height - 8
        tx, ty = max(8, tx), max(8, ty)

        box = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(box, (10, 10, 16, 238), (0, 0, width, height), border_radius=5)
        pygame.draw.rect(box, (*border, 255), (0, 0, width, height), 1, border_radius=5)
        self.screen.blit(box, (tx, ty))

        py = ty + 8
        for left, color, right in rows:
            self.screen.blit(font.render(left, True, color), (tx + 10, py))
            if right:
                surf = font.render(right, True, color)
                self.screen.blit(surf, (tx + width - 10 - surf.get_width(), py))
            py += line_h
        if footer:
            self.screen.blit(self.fonts["tiny"].render(footer, True, C["gray"]), (tx + 10, py + 4))

    # ================================================================== événements
    def _event_context(self, event):
        win = getattr(event, "window", None)
        if win is not None and self.overlay_win is not None and getattr(win, "id", None) == self.overlay_win.id:
            return "overlay"
        return "app"

    def handle_events(self, events):
        try:
            for event in events:
                if event.type == pygame.QUIT:
                    self.request_quit()
                    continue
                if event.type == getattr(pygame, "WINDOWCLOSE", -1):
                    # Dès que l'overlay a existé (même masqué), SDL gère deux fenêtres : la croix de la fenêtre
                    # principale n'envoie plus QUIT mais WINDOWCLOSE. Il faut donc quitter ici.
                    if self._event_context(event) == "overlay":
                        self.close_overlay()    # fermer l'overlay ne quitte pas l'application
                        continue
                    self.request_quit()
                    continue
                if event.type == getattr(pygame, "WINDOWFOCUSLOST", -1):
                    self._keys_down.clear()     # les relâchements de touches ne nous parviendront pas
                name = self._event_context(event)
                if name == "overlay":
                    if event.type == pygame.MOUSEMOTION or event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                        self._ov_mouse = tuple(event.pos)
                elif event.type == getattr(pygame, "WINDOWLEAVE", -1) and name == "overlay":
                    self._ov_mouse = None
                if event.type == getattr(pygame, "WINDOWLEAVE", -1):
                    if name == "overlay":
                        self._ov_mouse = None
                    continue
                if event.type == getattr(pygame, "WINDOWENTER", -1):
                    continue
                self.use(name)
                if not self._handle_event(event):
                    self.request_quit()
                if self._quit_now:
                    return False
            return not self._quit_now
        finally:
            self.use("app")

    def _handle_event(self, event):
        in_menu = (self._menu is not None and self._menu["win"] == self.cur and hasattr(event, "pos")
                   and self._menu["rect"].collidepoint(event.pos))
        if (self.mode == "overlay" and self.manager and not self.modal and not in_menu
                and event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP)
                and self.manager.on_event(event, self)):
            return True

        if event.type == pygame.KEYUP:
            self._keys_down.discard(event.key)
            return True

        if event.type == pygame.DROPFILE and self.chat is not None:   # fichier glissé sur la fenêtre : joint à Hermes
            ok, text = self.chat.attach_file(event.file)
            self.notify(text, 6)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self._open_menu(event.pos)          # clic droit sur un champ : Couper / Copier / Coller
            return True

        if event.type == pygame.KEYDOWN:
            repeated = event.key in self._keys_down
            self._keys_down.add(event.key)
            self._menu = None
            # la répétition ne sert qu'à l'édition d'un champ : jamais pour Échap / Entrée ni hors saisie
            if repeated and not (self.focus and event.key not in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER)):
                return True
            if self.focus:
                self._type(event)
                return True
            if self.modal:
                if self.modal.get("type") == "quit" and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._quit_now = True
                elif event.key == pygame.K_ESCAPE:
                    self.close_modal()
                return True
            if event.key == pygame.K_ESCAPE:
                if self.mode == "overlay":
                    return True            # l'overlay ne se ferme pas avec Échap
                return False
            if self.mode == "overlay":
                return True
            if pygame.K_1 <= event.key <= pygame.K_9 and event.key - pygame.K_1 < len(self.TABS):
                self._switch_tab(event.key - pygame.K_1)
            elif event.key == pygame.K_0 and len(self.TABS) >= 10:
                self._switch_tab(9)

        elif event.type == pygame.MOUSEWHEEL:
            pos = self.mouse_pos()
            for rect, key, _ in reversed(self._scroll_regions):
                if rect.collidepoint(pos):
                    self.scroll[key] = max(0, self.scroll.get(key, 0) - event.y * 48)
                    break

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.focus = None   # un clic ailleurs ferme la saisie (le champ la rouvre s'il est cliqué)
            self.select_all = None
            if not in_menu and self._start_scrollbar_drag(event.pos):
                self._menu = None
                return True
            for rect, fn in reversed(self._buttons):
                if rect.collidepoint(event.pos):
                    fn()
                    break
            self._menu = None   # tout clic referme le menu contextuel

        elif event.type == pygame.MOUSEMOTION and self._drag:
            self._drag_scrollbar(event.pos[1])

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag = None
        return True

    # ------------------------------------------------------------------ barres de défilement glissables
    def _start_scrollbar_drag(self, pos):
        for bar in reversed(self._scrollbars):
            if bar["hit"].collidepoint(pos):
                thumb = bar["thumb"]
                grab = pos[1] - thumb.y if thumb.collidepoint(pos) else thumb.h // 2   # clic dans la piste : on saute
                self._drag = {"key": bar["key"], "track": bar["track"], "thumb_h": thumb.h, "max": bar["max"], "grab": grab}
                self._drag_scrollbar(pos[1])
                return True
        return False

    def _drag_scrollbar(self, mouse_y):
        d = self._drag
        track_range = max(1, d["track"].h - d["thumb_h"])
        ratio = (mouse_y - d["grab"] - d["track"].y) / track_range
        self.scroll[d["key"]] = max(0, min(d["max"], int(ratio * d["max"])))

    def _type(self, event):
        key = self.focus
        text = self.inputs.get(key, "")
        caret = self._caret_pos(key)
        selected = self.select_all == key
        mods = getattr(event, "mod", 0) or 0
        # AltGr est vu comme Ctrl+Alt sous Windows : AltGr+0 (« @ » en AZERTY) n'est pas un raccourci
        ctrl = bool(mods & pygame.KMOD_CTRL) and not mods & pygame.KMOD_ALT
        shift = bool(mods & pygame.KMOD_SHIFT)
        k = event.key
        if k in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
            self.focus = None
            self.select_all = None
            callback = self.on_submit.get(key)
            if callback and k != pygame.K_ESCAPE:
                callback()
                if key == "chat_msg":
                    self.focus = key      # on garde la main sur le champ pour enchaîner les messages
        elif ctrl and k == pygame.K_a:
            self.edit_action("select_all", key)
        elif ctrl and k == pygame.K_c:
            self.edit_action("copy", key)
        elif ctrl and k == pygame.K_x:
            self.edit_action("cut", key)
        elif (ctrl and k == pygame.K_v) or (shift and k == pygame.K_INSERT):
            self.edit_action("paste", key)
        elif ctrl:
            pass                           # autre raccourci Ctrl : ne rien écrire dans le champ
        elif k == pygame.K_BACKSPACE:
            if selected:
                self._set_input(key, "", 0)
            elif caret > 0:
                self._set_input(key, text[:caret - 1] + text[caret:], caret - 1)
        elif k == pygame.K_DELETE:
            if selected:
                self._set_input(key, "", 0)
            elif caret < len(text):
                self._set_input(key, text[:caret] + text[caret + 1:], caret)
        elif k in (pygame.K_LEFT, pygame.K_HOME, pygame.K_RIGHT, pygame.K_END):
            if k == pygame.K_HOME or (selected and k == pygame.K_LEFT):
                caret = 0
            elif k == pygame.K_END or (selected and k == pygame.K_RIGHT):
                caret = len(text)
            else:
                caret += -1 if k == pygame.K_LEFT else 1
            self._caret = (key, max(0, min(caret, len(text))))
            self.select_all = None
        elif event.unicode and event.unicode.isprintable():
            if selected:
                text, caret = "", 0
            if len(text) < self._input_limit(key):
                self._set_input(key, text[:caret] + event.unicode + text[caret:], caret + len(event.unicode))

    # ================================================================== fenêtres modales
    def request_quit(self):
        """Croix de la fenêtre, Alt+F4 ou Échap : on demande confirmation ; seuls « Oui » et Entrée quittent.
        Windows envoie DEUX événements pour un seul clic sur la croix (WINDOWCLOSE puis QUIT) : une demande alors
        que la question est déjà posée est ignorée (elle valait « Oui » : l'appli se fermait aussitôt)."""
        previous = self.cur
        self.use("app")
        try:
            m = self.modal
            if m and m.get("type") == "quit":
                return
            self.focus = None
            self._menu = None
            self.modal = {"type": "quit", "previous": m}
        finally:
            self.use(previous)

    def close_modal(self):
        m = self.modal
        if m and m.get("type") == "quit" and m.get("previous"):
            self.modal = m["previous"]          # « Non » : on retrouve la fenêtre qui était ouverte
            return
        self.modal = None
        self.focus = None

    def ask_assistant(self, title, context, url="", suggestions=None, prefill=""):
        """Ouvre la fenêtre d'envoi à l'assistant (Hermes) avec le contexte fourni (quête, objet, ensemble...)."""
        self.modal = {"type": "compose", "title": title, "context": context, "url": url,
                      "suggestions": suggestions or ["Explique-moi ça simplement.", "Comment l'obtenir ou le faire ?",
                                                     "Que me conseilles-tu ?"],
                      "stage": "input", "job": None, "answer": "", "error": ""}
        self.inputs["llm_msg"] = prefill
        self.on_submit["llm_msg"] = self._modal_send
        self.focus = "llm_msg"
        self.scroll.pop("llm_answer", None)

    def _modal_send(self):
        m = self.modal
        if not m or m["type"] != "compose" or m["stage"] != "input":
            return
        message = self.inputs.get("llm_msg", "").strip() or "Explique-moi et guide-moi."
        if not self.llm or not self.llm.is_configured():
            m["stage"], m["error"] = "answer", ("Assistant non configuré : ouvrez les Paramètres généraux "
                                                 "(onglet Personnage) pour choisir l'endpoint API ou l'exécutable.")
            return
        images = self.vision.payload() if self.vision else []
        note = features.coach_note()
        m["job"] = self.llm.ask(f"{m['context']}\n\n" + (f"{note}\n\n" if note else "") + f"Question : {message}"
                                + i18n.answer_note(), images)
        if self.vision:
            self.vision.clear()
        m["stage"] = "wait"

    def _draw_modal(self):
        if self.mode != "overlay":      # en overlay, un voile noir cacherait la transparence
            dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 175))
            self.screen.blit(dim, (0, 0))
        self.click(pygame.Rect(0, 0, self.W, self.H), lambda: None)   # les clics hors de la fenêtre sont ignorés
        if self.modal["type"] == "quit":
            self._draw_quit()
        elif self.modal["type"] == "compose":
            self._draw_compose(self.modal)
        else:
            self._draw_settings(self.modal)

    def _draw_quit(self):
        w, h = 460, 190
        rect = pygame.Rect((self.W - w) // 2, (self.H - h) // 2, w, h)
        self.frame(rect, "WoW Assistant")
        self.text("Quitter WoW Assistant ?", "large", "gold", (rect.centerx, rect.y + 62), anchor="center",
                  shadow=True)
        self.text("Entrée : oui  —  Échap : non", "tiny", "gray", (rect.centerx, rect.y + 92), anchor="center")
        by = rect.bottom - 62
        self.pill((rect.centerx - 140, by, 130, 38), "Oui", True, lambda: setattr(self, "_quit_now", True))
        self.pill((rect.centerx + 10, by, 130, 38), "Non", False, self.close_modal)

    def _draw_compose(self, m):
        w, h = 960, 640
        rect = pygame.Rect((self.W - w) // 2, (self.H - h) // 2, w, h)
        self.frame(rect, "Assistant — Hermes")
        x, y = rect.x + 24, rect.y + 50
        self.text(self.fit(m["title"], "large", w - 48), "large", "gold", (x, y), shadow=True)

        if m["stage"] == "wait" and m["job"].done:
            m["answer"], m["error"], m["stage"] = m["job"].text, m["job"].error, "answer"
            self.scroll.pop("llm_answer", None)
            if not m["error"] and "speak" in self.actions:
                self.actions["speak"](m["answer"])

        if m["stage"] == "answer":
            area = pygame.Rect(x, y + 44, w - 48, h - 190)
            pygame.draw.rect(self.screen, (10, 10, 14), area, border_radius=5)
            lines = []
            body = m["error"] or m["answer"]
            for paragraph in body.split("\n"):
                lines += self.wrap(paragraph, "small", area.w - 40) if paragraph.strip() else [""]
            top = self.scroll_begin("llm_answer", area.inflate(-8, -8), len(lines) * 22 + 16)
            for i, line in enumerate(lines):
                ry = top + 8 + i * 22
                if area.y - 22 < ry < area.bottom:
                    self.text(line, "small", "red" if m["error"] else "text", (area.x + 14, ry))
            self.scroll_end()
            by = rect.bottom - 64
            self.pill((x, by, 190, 36), "Nouvelle question", False, lambda: m.update(stage="input", answer="", error=""))
            self.pill((x + 200, by, 120, 36), "Fermer", False, self.close_modal)
            return

        # --- contexte envoyé
        self.text("Contexte joint à votre message", "small", "label", (x, y + 44))
        box = pygame.Rect(x, y + 68, w - 48, 170)
        pygame.draw.rect(self.screen, (10, 10, 14), box, border_radius=5)
        pygame.draw.rect(self.screen, C["frame"], box, 1, border_radius=5)
        lines = []
        for paragraph in m["context"].split("\n"):
            lines += self.wrap(paragraph, "small", box.w - 28) if paragraph.strip() else [""]
        for i, line in enumerate(lines[:7]):
            self.text(self.fit(line, "small", box.w - 28), "small", "light_gray", (box.x + 14, box.y + 8 + i * 22))
        if len(lines) > 7:
            self.text(f"… (+{len(lines) - 7} lignes)", "small", "gray", (box.x + 14, box.bottom - 24))

        if m["stage"] == "wait":
            dots = "." * (1 + (pygame.time.get_ticks() // 400) % 3)
            self.text("Réflexion en cours" + dots, "large", "gold", (rect.centerx, rect.centery + 80), anchor="center")
            self.text("(l'assistant peut mettre plusieurs secondes à répondre)", "small", "gray",
                      (rect.centerx, rect.centery + 116), anchor="center")
            self.pill((x, rect.bottom - 64, 120, 36), "Annuler", False, self.close_modal)
            return

        # --- saisie du message
        py = y + 256
        px = x
        for suggestion in m["suggestions"]:
            pw = self.width(suggestion, "small") + 26
            if px + pw > rect.right - 24:
                px, py = x, py + 34
            self.pill((px, py, pw, 28), suggestion, False,
                      lambda t=suggestion: (self.inputs.update(llm_msg=t), setattr(self, "focus", "llm_msg")))
            px += pw + 8
        self.input_box((x, py + 42, w - 48, 40), "llm_msg", "Votre message (Entrée pour envoyer)…")
        info = self.llm.describe() if self.llm else "Assistant non configuré"
        self.text(self.fit("Assistant : " + info, "small", w - 48), "small", "gray", (x, py + 92))
        if self.voice and self.voice.status == "listening":
            self.text("● J'écoute…", "small", "red", (rect.right - 24, py + 92), anchor="topright")
        self.draw_attachments(x, py + 118, w - 48)
        by = rect.bottom - 64
        self.pill((x, by, 160, 36), "Envoyer", True, self._modal_send)
        self.pill((x + 170, by, 120, 36), "Annuler", False, self.close_modal)
        self.pill((x + 300, by, 150, 36), "Capture", False,
                  lambda: self.actions["capture"]() if "capture" in self.actions else None)
        self.pill((x + 460, by, 190, 36), "Message vocal", False, self._modal_voice)

    def _modal_voice(self):
        """Enregistre une phrase (arrêt au silence) et la transcrit. Le résultat s'affiche dans le champ de message
        (fenêtre d'envoi) ou dans l'état du test (réglages)."""
        if not self.voice:
            self.notify("Module vocal indisponible")
            return
        m = self.modal
        if m and m["type"] == "settings":
            m["status"], m["status_ok"] = "", True
        if not self.voice.record_once():
            if m and m["type"] == "settings":
                m["status"], m["status_ok"] = self.voice.error or "Micro indisponible", False
            else:
                self.notify(self.voice.error or "Micro indisponible", 7)
        else:
            self.focus = None

    # ------------------------------------------------------------------ paramètres généraux
    _SETTINGS_FIELDS = (("set_endpoint", "llm.endpoint"), ("set_model", "llm.model"), ("set_key", "llm.api_key"),
                        ("set_exe", "llm.exe_path"), ("set_args", "llm.exe_args"), ("set_system", "llm.system_prompt"),
                        ("set_hk_overlay", "overlay.hotkeys.overlay"), ("set_hk_lock", "overlay.hotkeys.lock"),
                        ("set_hk_focus", "overlay.hotkeys.focus"), ("set_hk_capture", "overlay.hotkeys.capture"),
                        ("set_v_ptt", "voice.ptt_key"), ("set_v_stt_endpoint", "voice.stt.endpoint"),
                        ("set_v_stt_model", "voice.stt.model"), ("set_v_stt_key", "voice.stt.api_key"),
                        ("set_v_stt_exe", "voice.stt.exe"), ("set_v_stt_args", "voice.stt.args"),
                        ("set_v_stt_lang", "voice.stt.language"), ("set_v_tts_exe", "voice.tts.piper_exe"),
                        ("set_v_tts_model", "voice.tts.piper_model"), ("set_w_openwebui", "web.openwebui_url"),
                        ("set_w_video", "web.video_url"), ("set_w_allowed", "web.allowed_hosts"))

    def open_settings(self, page="llm"):
        if not self.settings:
            self.notify("Réglages indisponibles")
            return
        for key, path in self._SETTINGS_FIELDS:
            self.inputs[key] = str(self.settings.get(path, ""))
        self.modal = {"type": "settings", "page": page, "mode": self.settings.get("llm.mode", "api"),
                      "icons": bool(self.settings.get("online_icons", True)),
                      "models": [], "status": "", "status_ok": True, "bg": None, "test": None,
                      "found": None, "scan": None, "checks": [], "chk_path": None, "chk_at": 0.0,
                      "devices": None, "dev_error": "", "monitors": overlay_win.list_monitors()}
        self.inputs["set_game_path"] = str(self.settings.get("game.path", "") or WoWConfig.WOW_PATH)
        self.focus = None

    def _clear_key(self, input_key, path):
        """Efface une clé API du champ ET de settings.json, tout de suite (sans attendre « Enregistrer »)."""
        had_key = bool(self.inputs.get(input_key) or self.settings.get(path, ""))
        self.inputs[input_key] = ""
        self.settings.set(path, "")
        self.settings.save()
        self.focus = None
        self.notify("Clé API effacée de settings.json" if had_key else "Aucune clé API enregistrée")

    def _clear_key_button(self, rect, input_key, path):
        """Petit bouton « × » à droite d'un champ de clé API : supprime la clé du fichier de réglages."""
        rect = pygame.Rect(rect)
        present = bool(self.inputs.get(input_key) or self.settings.get(path, ""))
        self.pill(rect, "×", present, lambda: self._clear_key(input_key, path))
        self.tip(rect, {"rows": [("Effacer la clé API (du champ et de settings.json)", "text", "")]})

    def _apply_settings_inputs(self, save):
        m = self.modal
        for key, path in self._SETTINGS_FIELDS:
            value = self.inputs.get(key, "")
            self.settings.set(path, value if key == "set_system" else value.strip())
        self.settings.set("llm.mode", m["mode"])
        self.settings.set("online_icons", m["icons"])
        self.icons.enabled = m["icons"]
        if "bn_id" in self.inputs:   # identifiants Battle.net (page Jeu) : « Enregistrer » du bas les garde aussi
            self.settings.set("bnet.client_id", self.inputs.get("bn_id", "").strip())
            self.settings.set("bnet.client_secret", self.inputs.get("bn_secret", "").strip())
        if save:
            ok = self.settings.save()
            m["status"], m["status_ok"] = ("Réglages enregistrés." if ok else "Impossible d'enregistrer settings.json"), ok
            if "settings_changed" in self.actions:
                self.actions["settings_changed"]()

    def _move_app_to(self, index):
        """Place la fenêtre principale sur l'écran choisi (et mémorise le choix)."""
        monitors = overlay_win.list_monitors()
        if index >= len(monitors):
            return
        mx, my, mw, mh = monitors[index]
        self.move_app((mx + max(0, (mw - self.W) // 2), my + max(0, (mh - self.H) // 2)))
        self.settings.set("overlay.app_monitor", index)
        self.settings.save()

    def _toggle_setting(self, path):
        """Interrupteur appliqué tout de suite (et enregistré)."""
        self.settings.set(path, not self.settings.get(path, False))
        self.settings.save()
        if "settings_changed" in self.actions:
            self.actions["settings_changed"]()

    def _set_setting(self, path, value):
        self.settings.set(path, value)
        self.settings.save()
        if "settings_changed" in self.actions:
            self.actions["settings_changed"]()

    def _load_models(self):
        """Modèles de tous les serveurs actifs (liste « Serveurs enregistrés » + endpoint en cours) : chaque
        modèle garde son serveur, le choisir sélectionne aussi le serveur."""
        m = self.modal
        self._apply_settings_inputs(False)
        m["bg"] = {"done": False, "models": [], "error": ""}
        job = m["bg"]
        servers = enabled_servers(self.settings, self.inputs.get("set_endpoint", ""), self.inputs.get("set_key", ""))

        def work():
            errors = []
            for server in servers:
                names, error = list_models_at(server["url"], server["api_key"])
                job["models"] += [(name, server["url"], server["api_key"]) for name in names]
                job.setdefault("providers", {})[server["url"]] = server["provider"]
                if error and not names:
                    errors.append(f"{server['url']} : {error}")
            job["error"] = " ; ".join(errors) or ("aucun serveur actif" if not servers else "")
            job["done"] = True
        threading.Thread(target=work, daemon=True).start()
        m["status"], m["status_ok"] = "Recherche des modèles…", True

    def _test_llm(self):
        m = self.modal
        self._apply_settings_inputs(False)
        m["test"] = self.llm.ask("Réponds uniquement par le mot : OK")
        m["status"], m["status_ok"] = "Test en cours…", True

    def _draw_settings(self, m):
        w, h = 960, 780
        rect = pygame.Rect((self.W - w) // 2, max(0, (self.H - h) // 2), w, min(h, self.H))
        self.frame(rect, "Paramètres généraux")
        x, y = rect.x + 24, rect.y + 48
        px = x
        for key, label in (("game", "Jeu"), ("llm", "Assistant IA"), ("overlay", "Overlay"), ("widgets", "Widgets"),
                           ("focus", "Mode Focus"), ("voice", "Voix"), ("vision", "Vision"), ("web", "Web")):
            self.pill((px, y, 108, 30), label, m["page"] == key, lambda k=key: m.update(page=k))
            px += 113
        y += 46

        # résultats des tâches de fond (liste de modèles, test)
        if m["bg"] and m["bg"]["done"]:
            job, m["bg"] = m["bg"], None
            m["models"] = job["models"]
            m["providers"] = job.get("providers", {})
            hosts = len({url for _name, url, _key in job["models"]})
            m["status"], m["status_ok"] = ((f"{len(job['models'])} modèle(s) trouvé(s) sur {hosts} serveur(s)."
                                            + (f"  Injoignable : {job['error']}" if job["error"] else ""))
                                           if job["models"] else f"Aucun modèle : {job['error']}"), bool(job["models"])
        if m["test"] and m["test"].done:
            job, m["test"] = m["test"], None
            m["status"], m["status_ok"] = ((f"Réponse reçue : {job.text[:80]}" if not job.error else f"Échec : {job.error[:120]}"),
                                           not job.error)

        by = rect.bottom - 62
        body = pygame.Rect(rect.x + 12, y - 4, rect.w - 24, by - 12 - (y - 4))
        key = "settings_" + m["page"]
        top = self.scroll_begin(key, body, m.setdefault("heights", {}).get(key, body.h))
        self._track_y = 0
        {"game": self._settings_game, "llm": self._settings_llm, "overlay": self._settings_overlay, "widgets": self._settings_widgets,
         "focus": self._settings_focus, "voice": self._settings_voice, "vision": self._settings_vision,
         "web": self._settings_web}[m["page"]](m, x, top + 4, rect)
        m["heights"][key] = int(self._track_y - top + 16)
        self._track_y = None
        self.scroll_end()

        self.pill((x, by, 180, 36), "Enregistrer", True, lambda: self._apply_settings_inputs(True))
        self.pill((x + 190, by, 120, 36), "Fermer", False, self.close_modal)
        footer = "settings.json (clé API stockée en clair sur ce PC)"
        if m["page"] != "llm" and m["status"]:
            # le message s'arrête avant la mention de droite : il est abrégé au lieu de la chevaucher
            room = rect.right - 24 - self.fonts["tiny"].size(self._glyphs(footer))[0] - 16 - (x + 330)
            self.text(self.fit(m["status"], "small", max(60, room)), "small", "green" if m["status_ok"] else "red", (x + 330, by + 10))
        self.text(footer, "tiny", "gray", (rect.right - 24, by + 12), anchor="topright")

    def _field(self, x, y, label, key, placeholder, label_w, field_w, mask=False):
        self.text(label, "small", "label", (x, y + 8))
        self.input_box((x + label_w, y, field_w, 34), key, placeholder, mask=mask)
        return y + 48

    def _toggle_row(self, x, y, label, path, width=520):
        value = bool(self.settings.get(path, False))
        self.pill((x, y, width, 32), f"{label} : " + ("oui" if value else "non"), value, lambda p=path: self._toggle_setting(p))
        return y + 44

    # ------------------------------------------------------------------ page « Jeu »
    def _game_apply(self, path=None):
        """Applique le dossier du jeu tout de suite (sans redémarrer) et l'enregistre."""
        m = self.modal
        path = (path if path is not None else self.inputs.get("set_game_path", "")).strip()
        retail = WoWConfig.normalize_path(path)
        if not retail:
            m["status"], m["status_ok"] = "Dossier invalide : il doit contenir WTF (ou Interface).", False
            return
        self.inputs["set_game_path"] = retail
        self.settings.set("game.path", retail)
        self.settings.save()
        if "game_path_changed" in self.actions:
            self.actions["game_path_changed"](retail)
        m["chk_path"] = None
        m["status"], m["status_ok"] = "Dossier du jeu appliqué.", True

    def _game_scan(self):
        m = self.modal
        job = {"done": False, "paths": []}
        m["scan"] = job
        m["status"], m["status_ok"] = "Recherche de World of Warcraft sur les disques…", True

        def work():
            try:
                job["paths"] = WoWConfig.detect_installs()
            finally:
                job["done"] = True
        threading.Thread(target=work, daemon=True).start()

    def _game_browse(self):
        m = self.modal

        def work():
            try:
                import tkinter
                from tkinter import filedialog
                root = tkinter.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen = filedialog.askdirectory(title="Dossier de World of Warcraft (ou _retail_)")
                root.destroy()
                if chosen:
                    m["picked"] = chosen
            except Exception as e:
                m["status"], m["status_ok"] = f"Sélecteur de dossier indisponible ({e}) : colle le chemin dans le champ.", False
        threading.Thread(target=work, daemon=True).start()

    def _settings_game(self, m, x, y, rect):
        self.text("Langue de l'interface", "medium", "gold", (x, y), shadow=True)
        lang_x = x + 260
        for code, name in i18n.LANGUAGES.items():
            self.pill((lang_x, y - 2, 130, 30), name, i18n.language() == code, lambda c=code: self.set_language(c))
            lang_x += 138
        y += 44
        self.text("Jeu : emplacement de World of Warcraft", "medium", "gold", (x, y), shadow=True)
        y += 34
        for line in ("Choisis le dossier « _retail_ » (celui qui contient WTF et Interface). Le dossier du jeu ou même",
                     "WTF/Account est accepté : l'appli retrouve _retail_. Le changement est appliqué tout de suite."):
            self.text(line, "small", "gray", (x, y))
            y += 22
        y += 8
        if m.get("picked"):
            self.inputs["set_game_path"] = m.pop("picked")
            self._game_apply()
        if m["scan"] and m["scan"]["done"]:
            job, m["scan"] = m["scan"], None
            m["found"] = job["paths"]
            m["status"], m["status_ok"] = (f"{len(job['paths'])} installation(s) trouvée(s)." if job["paths"]
                                           else "Aucune installation trouvée : utilise Parcourir ou colle le chemin."), bool(job["paths"])
        self.text("Dossier _retail_", "small", "label", (x, y + 8))
        self.input_box((x + 150, y, rect.w - 48 - 150, 34), "set_game_path", "F:/World of Warcraft/_retail_")
        y += 46
        self.pill((x, y, 170, 32), "Appliquer", True, self._game_apply)
        self.pill((x + 180, y, 170, 32), "Parcourir…", False, self._game_browse)
        self.pill((x + 360, y, 230, 32), "Détecter automatiquement", False, self._game_scan)
        y += 46
        if m["found"] is not None:
            self.text("Installations détectées (clique pour choisir) :", "small", "label", (x, y))
            y += 24
            for path in m["found"][:5]:
                self.pill((x, y, rect.w - 48, 28), path, WoWConfig.normalize_path(self.inputs.get("set_game_path", "")) == path,
                          lambda p=path: self._game_apply(p), font="tiny")
                y += 32
            if not m["found"]:
                self.text("Rien trouvé.", "small", "gray", (x, y))
                y += 24
            y += 6
        # vérifications (mises en cache : on ne scanne pas le disque à chaque image)
        typed = self.inputs.get("set_game_path", "")
        if m["chk_path"] != typed or time.time() - m["chk_at"] > 4:
            m["chk_path"], m["chk_at"] = typed, time.time()
            m["checks"] = WoWConfig.inspect_path(typed)
        self.text("Vérifications", "medium", "gold", (x, y), shadow=True)
        y += 32
        for label, ok, detail in m["checks"]:
            pygame.draw.circle(self.screen, C["green"] if ok else C["red"], (x + 8, y + 10), 6)
            self.text(label, "small", "text", (x + 24, y))
            self.text(self.fit(detail, "small", rect.w - 48 - 280), "small", "gray" if ok else "orange", (x + 270, y))
            y += 26
        y += 10
        connected = WoWConfig.is_wow_installed()
        self.text("Dossier actuellement utilisé : " + WoWConfig.WOW_PATH, "tiny", "green" if connected else "red", (x, y))
        from tabs_market import bnet_settings
        y += 34
        pygame.draw.line(self.screen, C["header_border"], (x, y), (x + rect.w - 48, y), 1)
        bnet_settings(self, (x, y + 14, rect.w - 48, 220))

    def _settings_llm(self, m, x, y, rect):
        w = rect.w
        label_w, field_w = 190, rect.w - 48 - 190
        self.text("Assistant IA (orchestrateur : Hermes pour le moment)", "medium", "gold", (x, y), shadow=True)
        y += 38
        self.pill((x, y, 380, 32), "Hermes Agent  (recommandé)", m["mode"] != "api", lambda: m.update(mode="hermes"))
        self.pill((x + 390, y, 420, 32), "Serveur API  (Ollama, LM Studio, Omniroute…)", m["mode"] == "api",
                  lambda: m.update(mode="api"))
        y += 48
        if m["mode"] != "api":
            describe = self.llm.hermes.describe() if self.llm else "Hermes Agent"
            self.text(describe, "small", "text", (x, y + 4))
            self.text("Session dédiée, skills, mémoire et outils de jeu de Hermes. Réglages, installation du skill "
                      "« wow-coach » et des outils de jeu : onglet Hermes.", "tiny", "gray", (x, y + 30))
            self.pill((x + w - 48 - 200, y, 200, 30), "Ouvrir l'onglet Hermes", False,
                      lambda: (self._apply_settings_inputs(True), self.close_modal(),
                               self._switch_tab(self.TABS.index("Hermes"))))
            y += 60
        elif m["mode"] == "api":
            y = self._field(x, y, "Endpoint API", "set_endpoint", "http://127.0.0.1:11434/v1   (ou Open WebUI / Omniroute)", label_w, field_w)
            y = self._settings_servers(x, y, label_w, rect)
            y = self._field(x, y, "Modèle", "set_model", "nom du modèle (ex. claude-sonnet, llama3…)", label_w, field_w)
            self.pill((x + label_w, y, 230, 30), "Charger la liste des modèles", False, self._load_models)
            y += 38
            if m["models"]:
                px = x + label_w
                several = len({url for _n, url, _k in m["models"]}) > 1
                for name, url, key in m["models"][:24]:
                    label = f"{name}  · {m.get('providers', {}).get(url) or self._server_label(url)}" if several else name
                    pw = self.width(label, "small") + 24
                    if px + pw > rect.right - 24:
                        px, y = x + label_w, y + 32
                    chosen = self.inputs.get("set_model") == name and self.inputs.get("set_endpoint", "").rstrip("/") == url
                    self.pill((px, y, pw, 28), label, chosen,
                              lambda n=name, u=url, k=key: self.inputs.update(set_model=n, set_endpoint=u, set_key=k))
                    px += pw + 6
                y += 38
            self._clear_key_button((x + label_w + field_w - 38, y, 38, 34), "set_key", "llm.api_key")
            y = self._field(x, y, "Clé API (facultative)", "set_key", "laisser vide si le serveur n'en demande pas", label_w, field_w - 46, mask=True)
        if m["mode"] == "api":    # Hermes : le rôle vient du skill wow-coach et de sa propre configuration
            y = self._field(x, y, "Consigne système", "set_system", "rôle donné à l'assistant", label_w, field_w)
        self.pill((x, y, 230, 32), "Tester la connexion", False, self._test_llm)
        if m["status"]:
            self.text(self.fit(m["status"], "small", w - 330), "small", "green" if m["status_ok"] else "red", (x + 244, y + 8))
        y += 52
        pygame.draw.line(self.screen, C["header_border"], (x, y), (rect.right - 24, y), 1)
        y += 14
        self.text("Interface", "medium", "gold", (x, y), shadow=True)
        y += 34
        self.pill((x, y, 440, 32), "Icônes en ligne (Wowhead) : " + ("activées" if m["icons"] else "désactivées"), m["icons"],
                  lambda: m.update(icons=not m["icons"]))
        self.text("Désactivez pour ne faire aucune requête vers Wowhead (icônes déjà en cache conservées).", "tiny", "gray", (x, y + 42))

    @staticmethod
    def _server_label(url):
        """Nom court d'un serveur pour les boutons : « 127.0.0.1:5750 »."""
        return url.split("://", 1)[-1].split("/", 1)[0]

    def _servers(self):
        return [dict(s) for s in (self.settings.get("llm.servers", []) or []) if isinstance(s, dict)]

    def _save_servers(self, servers):
        self.settings.set("llm.servers", servers)
        self.settings.save()

    def _add_strata(self):
        """Ajoute le serveur Strata local (moteur des gros modèles MoE) à la liste, sans clé."""
        servers = self._servers()
        if any(s.get("url", "").rstrip("/") == STRATA_ENDPOINT for s in servers):
            self.notify("Ce serveur est déjà dans la liste")
            return
        servers.append({"url": STRATA_ENDPOINT, "api_key": "", "enabled": True, "provider": "Strata"})
        self._save_servers(servers)
        self.notify("Strata ajouté à la liste : « Charger la liste des modèles » pour le voir")

    def _add_server(self):
        url = self.inputs.get("set_endpoint", "").strip().rstrip("/")
        if not url:
            self.notify("Renseignez d'abord l'endpoint")
            return
        servers = self._servers()
        if any(s.get("url", "").rstrip("/") == url for s in servers):
            self.notify("Ce serveur est déjà dans la liste")
            return
        servers.append({"url": url, "api_key": self.inputs.get("set_key", "").strip(), "enabled": True,
                        "provider": guess_provider(url)})
        self._save_servers(servers)
        self.notify("Serveur ajouté à la liste")

    def _toggle_server(self, index):
        servers = self._servers()
        servers[index]["enabled"] = not servers[index].get("enabled", True)
        self._save_servers(servers)

    def _cycle_provider(self, index):
        """Fournisseur suivant de la liste (Ollama, Hub AetherTwin, Strata, Open WebUI, OmniRoute, LM Studio...)."""
        servers = self._servers()
        current = servers[index].get("provider") or guess_provider(servers[index].get("url", ""))
        position = PROVIDERS.index(current) if current in PROVIDERS else -1
        servers[index]["provider"] = PROVIDERS[(position + 1) % len(PROVIDERS)]
        self._save_servers(servers)

    def _remove_server(self, index):
        servers = self._servers()
        del servers[index]
        self._save_servers(servers)

    def _use_server(self, index):
        server = self._servers()[index]
        self.inputs.update(set_endpoint=server.get("url", ""), set_key=server.get("api_key", ""))

    def _settings_servers(self, x, y, label_w, rect):
        """Serveurs enregistrés : plusieurs endpoints gardés en mémoire, chacun actif ou non ; « Charger la liste
        des modèles » interroge tous les serveurs actifs. L'endpoint utilisé pour répondre reste celui du champ."""
        servers = self._servers()
        self.text("Serveurs enregistrés", "small", "gray", (x, y + 6))
        self.pill((x + label_w, y, 300, 28), "Ajouter l'endpoint ci-dessus à la liste", False, self._add_server)
        srect = pygame.Rect(x + label_w + 310, y, 170, 28)
        self.pill(srect, "Ajouter Strata", False, self._add_strata)
        self.tip(srect, {"rows": [("Strata : gros modèles « mélange d'experts » en local", "text", ""),
                                  (STRATA_ENDPOINT, "gray", "")]})
        y += 36
        for i, server in enumerate(servers[:5]):
            on = server.get("enabled", True)
            self.pill((x + label_w, y, 70, 26), "actif" if on else "inactif", on, lambda i=i: self._toggle_server(i))
            provider = server.get("provider") or guess_provider(server.get("url", ""))
            prect = pygame.Rect(x + label_w + 78, y, 132, 26)
            self.pill(prect, provider, False, lambda i=i: self._cycle_provider(i))
            self.tip(prect, {"rows": [("Fournisseur : cliquer pour changer", "text", "")]})
            self.text(self.fit(server.get("url", ""), "small", rect.right - x - label_w - 470), "small",
                      "text" if on else "gray", (x + label_w + 220, y + 3))
            self.pill((rect.right - 24 - 160, y, 100, 26), "Utiliser", False, lambda i=i: self._use_server(i))
            self.pill((rect.right - 24 - 52, y, 52, 26), "×", False, lambda i=i: self._remove_server(i))
            y += 32
        if len(servers) > 5:
            self.text(f"… et {len(servers) - 5} autre(s) dans settings.json", "tiny", "gray", (x + label_w, y))
            y += 22
        return y + 6

    def _settings_overlay(self, m, x, y, rect):
        self.text("Overlay : fenêtre transparente au premier plan", "medium", "gold", (x, y), shadow=True)
        y += 34
        for line in ("Seuls les widgets sont visibles : les zones vides laissent passer les clics vers WoW.",
                     "WoW doit tourner en mode « Fenêtré » ou « Fenêtré (plein écran) » (pas en plein écran exclusif)."):
            self.text(line, "small", "gray", (x, y))
            y += 22
        y += 10
        y = self._toggle_row(x, y, "Démarrer directement en mode overlay", "overlay.start_in_overlay")
        y = self._toggle_row(x, y, "Se placer sur la fenêtre de WoW", "overlay.anchor_game")
        y = self._toggle_row(x, y, "Verrouiller les widgets (plus de déplacement)", "overlay.locked")
        self.text("Opacité globale", "small", "label", (x, y + 6))
        px = x + 190
        current = int(self.settings.get("overlay.opacity", 100))
        for value in (40, 60, 80, 100):
            self.pill((px, y, 80, 30), f"{value} %", current == value, lambda v=value: self._set_setting("overlay.opacity", v))
            px += 88
        y += 48
        monitors = m.get("monitors") or [(0, 0, 1920, 1080)]
        self.text("Fenêtre principale sur l'écran", "small", "label", (x, y + 6))
        px = x + 270
        current = int(self.settings.get("overlay.app_monitor", -1))
        for i, (mx, my, mw, mh) in enumerate(monitors[:4]):
            self.pill((px, y, 190, 30), f"Écran {i + 1}  ({mw}×{mh})", current == i, lambda idx=i: self._move_app_to(idx), font="tiny")
            px += 196
        y += 40
        self.text("Overlay si WoW est introuvable", "small", "label", (x, y + 6))
        px = x + 270
        current = int(self.settings.get("overlay.monitor", 0))
        for i, (mx, my, mw, mh) in enumerate(monitors[:4]):
            self.pill((px, y, 190, 30), f"Écran {i + 1}  ({mw}×{mh})", current == i, lambda idx=i: self._set_setting("overlay.monitor", idx), font="tiny")
            px += 196
        y += 40
        self.text("La fenêtre principale reste en place quand l'overlay s'ouvre ; sa position est mémorisée à la fermeture.", "tiny", "gray", (x, y))
        y += 26
        self.text("Raccourcis globaux (Windows) — fonctionnent même dans WoW", "medium", "gold", (x, y), shadow=True)
        y += 36
        y = self._field(x, y, "Afficher / masquer", "set_hk_overlay", "F9", 190, 220)
        y = self._field(x, y, "Verrouiller / déverrouiller", "set_hk_lock", "F10", 190, 220)
        y = self._field(x, y, "Mode Focus (manuel)", "set_hk_focus", "F11", 190, 220)
        self.text("Exemples : F9, Ctrl+Alt+H, Shift+F12 (puis Enregistrer)", "tiny", "gray", (x + 430, y - 120))
        self.pill((x, y + 6, 280, 34), "Lancer l'overlay maintenant", False,
                  lambda: (self.close_modal(), self.actions["to_overlay"]()) if "to_overlay" in self.actions else None)
        self.pill((x + 292, y + 6, 280, 34), "Réinitialiser la disposition", False,
                  lambda: (self.manager.reset(), self.notify("Disposition réinitialisée")) if self.manager else None)

    def _settings_widgets(self, m, x, y, rect):
        self.text("Widgets : activation et comportement en mode Focus", "medium", "gold", (x, y), shadow=True)
        y += 36
        if not self.manager:
            self.text("Gestionnaire de widgets indisponible", "small", "gray", (x, y))
            return
        self.text("Widget", "small", "label", (x, y))
        self.text("Pendant un combat (Mode Focus)", "small", "label", (x + 520, y))
        y += 26
        for wid in self.manager.order:
            spec, entry = self.manager.specs[wid], self.manager.entry(wid)
            if not spec.closable:
                continue
            self.text(spec.title, "small", "text", (x, y + 4))
            self.text(self.fit(spec.note, "tiny", 300), "tiny", "gray", (x, y + 22))
            self.pill((x + 330, y, 120, 30), "Actif" if entry["enabled"] else "Masqué", entry["enabled"],
                      lambda i=wid, v=not entry["enabled"]: self.manager.set_enabled(i, v))
            px = x + 520
            for value, label in (("keep", "Garder"), ("shrink", "Réduire"), ("hide", "Masquer")):
                self.pill((px, y, 130, 30), label, entry["focus"] == value,
                          lambda i=wid, v=value: self.manager.set_focus_behaviour(i, v))
                px += 136
            y += 50

    def _pill_choice(self, x, y, label, path, choices, label_w=230, pw=150):
        """Choix exclusif appliqué tout de suite : [(valeur, libellé)]."""
        self.text(label, "small", "label", (x, y + 6))
        current = self.settings.get(path)
        px = x + label_w
        for value, text in choices:
            self.pill((px, y, pw, 30), text, current == value, lambda v=value: self._set_setting(path, v))
            px += pw + 8
        return y + 46

    def _voice_device_row(self, m, x, y, rect):
        """Choix du micro : ◀ nom ▶ + actualiser."""
        self.text("Micro (périphérique)", "small", "label", (x, y + 6))
        if m["devices"] is None:
            try:
                m["devices"], m["dev_error"] = self.voice.list_input_devices(), ""
            except Exception as e:
                m["devices"], m["dev_error"] = [], ("sounddevice absent ou illisible : " + str(e)[:80])
        names = [""] + [name for name, _default in m["devices"]]
        current = str(self.settings.get("voice.device", "") or "")
        index = names.index(current) if current in names else 0

        def pick(step):
            self._set_setting("voice.device", names[(index + step) % len(names)])
            if self.voice:
                self.voice.restart()
                m["status"], m["status_ok"] = (self.voice.error, False) if self.voice.error else ("Micro changé.", True)
        label = current or "Micro par défaut de Windows"
        if not current:
            default = [n for n, d in m["devices"] if d]
            if default:
                label += f"  ({default[0][:28]})"
        self.pill((x + 270, y, 34, 30), "<", False, lambda: pick(-1), font="tiny")
        self.pill((x + 308, y, 360, 30), self.fit(label, "tiny", 340), bool(current), lambda: pick(1), font="tiny")
        self.pill((x + 672, y, 34, 30), ">", False, lambda: pick(1), font="tiny")
        self.pill((x + 712, y, 130, 30), "Actualiser", False, lambda: m.update(devices=None), font="tiny")
        problem = m["dev_error"] or ("" if m["devices"] else "Aucun micro détecté par Windows.")
        if problem:
            lines = self.wrap(problem, "tiny", rect.w - 48 - 270)[:2]
            for i, line in enumerate(lines):
                self.text(line, "tiny", "red", (x + 270, y + 36 + i * 16))
            return y + 44 + 16 * len(lines)
        return y + 48

    def _voice_test_status(self, m, x, y, width):
        """État en direct du test du micro (sous les boutons) : écoute, niveau, transcription, résultat. Retourne la hauteur."""
        v = self.voice
        if not v:
            return 0
        testing = bool(v._oneshot) or v.status in ("transcribing",)
        if v.error:
            line, color = v.error, "red"
        elif testing:
            line, color = (v.STATUS_LABELS["transcribing"] if v.status == "transcribing" else "Parle maintenant…"), "orange"
        else:
            line, color = (m["status"] if m["status"] else "Clique sur « Tester le micro », puis dis une phrase."), ("green" if m["status_ok"] else "red")
        meter = pygame.Rect(x, y + 4, 220, 10)
        pygame.draw.rect(self.screen, (40, 40, 46), meter, border_radius=4)
        pygame.draw.rect(self.screen, C["green"], (meter.x, meter.y, int(meter.w * min(1.0, v.level * 2)), meter.h), border_radius=4)
        yy = y + 22
        for text in self.wrap(line, "tiny", width)[:3]:
            self.text(text, "tiny", color, (x, yy))
            yy += 17
        if v.notice:
            self.text(self.fit(v.notice, "tiny", width), "tiny", "orange", (x, yy))
            yy += 17
        return yy - y

    def _settings_voice(self, m, x, y, rect):
        self.text("Voix : micro, reconnaissance et lecture des réponses", "medium", "gold", (x, y), shadow=True)
        y += 34
        y = self._toggle_row(x, y, "Micro activé", "voice.enabled", 380)
        y = self._pill_choice(x, y, "Mode du micro", "voice.mode", (("ptt", "Appuyer pour parler"), ("vad", "Activation vocale")), pw=190)
        y = self._voice_device_row(m, x, y, rect)
        y = self._field(x, y, "Touche (appuyer pour parler)", "set_v_ptt", "F8, Ctrl+Space, Mouse4…", 270, 240)
        self.text("F8, Ctrl+Space, Mouse4/Mouse5… puis Enregistrer", "tiny", "gray", (x + 526, y - 34))
        self.text("Sensibilité", "small", "label", (x, y + 6))
        px = x + 270
        for value in (1, 2, 3, 4, 5):
            self.pill((px, y, 60, 30), str(value), int(self.settings.get("voice.sensitivity", 3)) == value,
                      lambda v=value: self._set_setting("voice.sensitivity", v))
            px += 68
        if self.voice:
            meter = pygame.Rect(px + 20, y + 10, 160, 12)
            pygame.draw.rect(self.screen, (40, 40, 46), meter, border_radius=4)
            pygame.draw.rect(self.screen, C["green"], (meter.x, meter.y, int(meter.w * min(1.0, self.voice.level * 2)), meter.h), border_radius=4)
        y += 44
        y = self._toggle_row(x, y, "Envoyer le message dès qu'il est transcrit", "voice.auto_send", 520)
        y = self._toggle_row(x, y, "Lire les réponses de l'assistant à voix haute", "voice.speak_answers", 520)
        y = self._pill_choice(x, y, "Reconnaissance (STT)", "voice.stt.backend",
                              (("api", "Serveur API"), ("exe", "Programme local"), ("faster-whisper", "faster-whisper")), pw=190)
        backend = self.settings.get("voice.stt.backend", "api")
        if backend == "api":
            y = self._field(x, y, "Endpoint (…/v1)", "set_v_stt_endpoint", "http://127.0.0.1:8000/v1  (Open WebUI, faster-whisper-server…)", 270, 640)
            y = self._field(x, y, "Modèle / clé API", "set_v_stt_model", "whisper-1", 270, 300)
            self.input_box((x + 270 + 310, y - 44, 284, 34), "set_v_stt_key", "clé API (facultative)", mask=True)
            self._clear_key_button((x + 270 + 310 + 292, y - 44, 38, 34), "set_v_stt_key", "voice.stt.api_key")
        elif backend == "exe":
            y = self._field(x, y, "Programme", "set_v_stt_exe", "whisper-cli.exe (whisper.cpp) ou chemin complet", 270, 640)
            y = self._field(x, y, "Arguments", "set_v_stt_args", "-m modele.bin -f {audio} -l fr -nt", 270, 640)
        else:
            # choix parmi les tailles acceptées par faster-whisper (« whisper-1 » est un nom de l'API, il y est refusé)
            y = self._pill_choice(x, y, "Modèle faster-whisper", "voice.stt.fw_model",
                                  tuple((name, name) for name in voice_mod.FASTER_WHISPER_MODELS), label_w=270, pw=112)
            self.text("Du plus rapide (tiny) au plus précis (large-v3). Le modèle est téléchargé à la première utilisation.",
                      "tiny", "gray", (x + 270, y - 8))
            y += 18
        y = self._pill_choice(x, y, "Voix (TTS)", "voice.tts.backend",
                              (("sapi", "Voix Windows"), ("piper", "Piper"), ("off", "Désactivée")), pw=190)
        if self.settings.get("voice.tts.backend") == "piper":
            y = self._field(x, y, "Piper : programme", "set_v_tts_exe", "piper.exe", 270, 300)
            y = self._field(x, y, "Piper : modèle (.onnx)", "set_v_tts_model", "C:\\...\\fr_FR-siwis-medium.onnx", 270, 640)
        self.pill((x, y + 4, 200, 32), "Tester la voix", False,
                  lambda: self.voice.speak("Bonjour, ceci est un test de la voix de l'assistant.") if self.voice else None)
        self.pill((x + 212, y + 4, 260, 32), "Tester le micro (une phrase)", False, self._modal_voice)
        self._voice_test_status(m, x, y + 46, rect.w - 48)

    def _settings_web(self, m, x, y, rect):
        self.text("Widgets web : Open WebUI et lecteur vidéo", "medium", "gold", (x, y), shadow=True)
        y += 34
        for line in ("Chaque page s'affiche dans un processus séparé (aucun code web ne s'exécute dans l'appli), sans pont vers",
                     "l'appli, limitée aux domaines autorisés ci-dessous. Ce n'est pas un bac à sable Windows complet.",
                     "Nécessite pywebview :  pip install pywebview   (WebView2 est déjà présent sur Windows 10/11)."):
            self.text(line, "small", "gray", (x, y))
            y += 22
        y += 10
        y = self._field(x, y, "Adresse d'Open WebUI", "set_w_openwebui", "http://localhost:3000", 230, 660)
        y = self._field(x, y, "Adresse du lecteur vidéo", "set_w_video", "https://www.youtube.com/", 230, 660)
        y = self._field(x, y, "Domaines autorisés", "set_w_allowed", "localhost, youtube.com, twitch.tv   (sous-domaines inclus)", 230, 660)
        y = self._pill_choice(x, y, "Échelle Windows", "web.scale", ((1.0, "100 %"), (1.25, "125 %"), (1.5, "150 %"), (2.0, "200 %")), pw=110)
        self.text("À ajuster si la fenêtre web n'est pas alignée avec son widget (mise à l'échelle de l'affichage).", "tiny", "gray", (x + 230, y - 8))
        y += 18
        for wid, label in (("openwebui", "Open WebUI"), ("video", "Lecteur vidéo")):
            enabled = bool(self.manager and self.manager.entry(wid)["enabled"])
            state = ""
            if self.webhost:
                state = ("  —  " + self.webhost.errors[wid]) if wid in self.webhost.errors else (
                    "  —  en cours" if self.webhost.is_running(wid) else "")
            self.pill((x, y, 330, 32), f"Widget {label} : " + ("affiché" if enabled else "masqué"), enabled,
                      lambda w=wid, v=not enabled: self.manager.set_enabled(w, v) if self.manager else None)
            self.text(self.fit(state, "small", 520), "small", "red" if "—  " in state and wid in (self.webhost.errors if self.webhost else {}) else "gray",
                      (x + 346, y + 8))
            y += 42
        self.text("Les widgets web s'affichent dans l'overlay (Paramètres > Overlay > Lancer l'overlay).", "small", "gray", (x, y + 6))

    def _settings_vision(self, m, x, y, rect):
        self.text("Vision : captures d'écran jointes aux questions", "medium", "gold", (x, y), shadow=True)
        y += 36
        for line in ("Bouton « Capture » : l'overlay se masque un instant, la fenêtre de WoW est capturée, puis il réapparaît.",
                     "Win + Maj + S : toute image copiée dans le presse-papier vous est proposée (notification « Joindre »).",
                     "Nécessite la bibliothèque Pillow (pip install pillow). Le modèle de l'assistant doit accepter les images."):
            self.text(line, "small", "gray", (x, y))
            y += 24
        y += 10
        y = self._toggle_row(x, y, "Surveiller le presse-papier (Win + Maj + S)", "vision.watch_clipboard", 560)
        y = self._pill_choice(x, y, "Masquage avant capture", "vision.hide_ms", ((50, "50 ms"), (80, "80 ms"), (150, "150 ms"), (300, "300 ms")), pw=110)
        y = self._pill_choice(x, y, "Taille maximale de l'image", "vision.max_edge", ((1024, "1024 px"), (1600, "1600 px"), (2048, "2048 px")), pw=120)
        y = self._field(x, y, "Raccourci de capture", "set_hk_capture", "F7", 230, 220)
        self.pill((x, y + 6, 240, 34), "Tester la capture", False,
                  lambda: self.actions["capture"]() if "capture" in self.actions else None)
        if self.vision and self.vision.attachments:
            self.draw_attachments(x + 260, y + 4, 600)

    def _settings_focus(self, m, x, y, rect):
        self.text("Mode Focus : se faire discret pendant les combats", "medium", "gold", (x, y), shadow=True)
        y += 38
        y = self._toggle_row(x, y, "Détection automatique du combat", "focus.auto")
        self.text("Silence avant de réafficher", "small", "label", (x, y + 6))
        px = x + 230
        current = int(self.settings.get("focus.quiet_seconds", 5))
        for value in (3, 5, 8, 12):
            self.pill((px, y, 90, 30), f"{value} s", current == value, lambda v=value: self._set_setting("focus.quiet_seconds", v))
            px += 98
        y += 52
        status = self.actions["focus_status"]() if "focus_status" in self.actions else "inconnu"
        self.text("État actuel : " + status, "medium", "text", (x, y))
        y += 40
        for line in ("WoW n'envoie rien en temps réel à une application externe : le combat est déduit du journal de combat officiel",
                     "du jeu (dossier Logs de WoW). Activez-le une fois en jeu avec :  /ha combatlog on",
                     "Tant que ce journal grossit, vous êtes en combat ; après quelques secondes de silence, tout revient.",
                     "",
                     "Raccourci manuel (Overlay > Mode Focus) : automatique -> forcé actif -> forcé inactif.",
                     "Le comportement de chaque widget (Garder / Réduire / Masquer) se règle dans la page Widgets."):
            self.text(line, "small", "light_gray" if line else "gray", (x, y))
            y += 24

    @staticmethod
    def _open_url(url):
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"Impossible d'ouvrir {url} : {e}")
