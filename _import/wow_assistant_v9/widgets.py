"""
Hub de widgets : chaque widget est un panneau que l'on peut déplacer (glisser la barre de titre), redimensionner
(poignée en bas à droite), réduire, fermer ou verrouiller. La disposition est mémorisée dans layout.json.
Mode Focus : pendant un combat, chaque widget est gardé, réduit à sa barre de titre ou masqué (au choix).
"""
import json
import os

import pygame

import mousepos

from overlay import COLOR_KEY
from theme import C

TITLE_H = 28
FOCUS_CHOICES = (("keep", "Garder"), ("shrink", "Réduire"), ("hide", "Masquer"))


class WidgetSpec:
    def __init__(self, wid, title, size, draw, min_size=(180, 120), focus="keep", enabled=True, chrome=True,
                 closable=True, note="", web=False):
        self.web = web           # widget web : le corps est transparent, une fenêtre web (processus isolé) s'y superpose
        self.id, self.title, self.size, self.draw = wid, title, size, draw
        self.min_size, self.focus, self.enabled = min_size, focus, enabled
        self.chrome, self.closable, self.note = chrome, closable, note


class WidgetManager:
    def __init__(self, specs, path):
        self.specs = {s.id: s for s in specs}
        self.order = [s.id for s in specs]
        self.path = path
        self.layout = {}
        self.locked = False
        self.focus_active = False
        self.screen_size = (1920, 1080)
        self._hits = []          # (rect, widget id, type) de la dernière image, du dessous vers le dessus
        self.web_state = {}      # widgets web : {id: {"rect": zone du corps ou None, "enabled": bool}}
        self._drag = None
        self._unplaced = set()   # widgets sans position mémorisée : placés automatiquement sans chevauchement
        self.load()
        self._place_unplaced()

    # ------------------------------------------------------------------ disposition
    def _default_entry(self, index, spec):
        col, row = index % 3, index // 3
        return {"x": 30 + col * 330, "y": 80 + row * 60 + (index % 3) * 30, "w": spec.size[0], "h": spec.size[1],
                "enabled": spec.enabled, "collapsed": False, "focus": spec.focus, "z": index, "auto": True}

    def load(self):
        stored = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stored = data.get("widgets", {}) if isinstance(data, dict) else {}
            self.locked = bool(data.get("locked", False))
        except (OSError, ValueError, AttributeError):
            pass
        self.layout = {}
        self._unplaced = set()
        for index, wid in enumerate(self.order):
            entry = self._default_entry(index, self.specs[wid])
            if isinstance(stored.get(wid), dict) and "x" in stored[wid]:
                entry.update({k: v for k, v in stored[wid].items() if k in entry})
                entry.setdefault("auto", False)
                if "auto" not in stored[wid]:
                    entry["auto"] = False      # anciennes dispositions : on respecte les positions enregistrées
            else:
                self._unplaced.add(wid)
            self.layout[wid] = entry

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"locked": self.locked, "widgets": self.layout}, f, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"Disposition non sauvegardée : {e}")

    def reset(self):
        self.layout = {wid: self._default_entry(i, self.specs[wid]) for i, wid in enumerate(self.order)}
        self._unplaced = set(self.order)
        self._place_unplaced()
        self.save()

    def _free_spot(self, wid):
        """Premier emplacement libre (colonnes de gauche à droite) pour le widget, sans chevaucher les autres."""
        e = self.layout[wid]
        sw, sh = self.screen_size
        w, h = e["w"], e["h"]
        others = [pygame.Rect(o["x"], o["y"], o["w"], TITLE_H if o["collapsed"] else o["h"])
                  for k, o in self.layout.items() if k != wid and o["enabled"] and k not in self._unplaced]
        for x in range(20, max(21, sw - w + 1), 20):
            for y in range(56, max(57, sh - h + 1), 20):
                rect = pygame.Rect(x, y, w, h)
                if not any(rect.colliderect(o.inflate(8, 8)) for o in others):
                    return x, y
        n = len([k for k in self.layout if k not in self._unplaced and self.layout[k]["enabled"]])
        return 40 + 24 * (n % 8), 80 + 24 * (n % 8)     # écran trop petit : en cascade

    def _place_unplaced(self):
        for wid in [w for w in self.order if w in self._unplaced]:
            e = self.layout[wid]
            if not e["enabled"]:
                continue
            self.clamp(wid)
            if wid == "barre":
                e["x"], e["y"] = max(0, (self.screen_size[0] - e["w"]) // 2), 8
            else:
                e["x"], e["y"] = self._free_spot(wid)
            self._unplaced.discard(wid)

    def entry(self, wid):
        return self.layout[wid]

    def set_enabled(self, wid, enabled):
        self.layout[wid]["enabled"] = bool(enabled)
        if enabled:
            self.bring_to_front(wid)
            self._place_unplaced()
        self.save()

    def set_focus_behaviour(self, wid, behaviour):
        self.layout[wid]["focus"] = behaviour
        self.save()

    def set_screen_size(self, size):
        changed = tuple(size) != tuple(self.screen_size)
        self.screen_size = size
        if changed:
            # les widgets jamais déplacés à la main suivent la nouvelle taille d'écran
            self._unplaced |= {wid for wid in self.order if self.layout[wid].get("auto")}
        self.clamp_all()
        self._place_unplaced()

    def clamp(self, wid):
        e, spec = self.layout[wid], self.specs[wid]
        sw, sh = self.screen_size
        e["w"] = max(spec.min_size[0], min(e["w"], sw))
        e["h"] = max(spec.min_size[1], min(e["h"], sh))
        e["x"] = max(0, min(e["x"], sw - 60))
        e["y"] = max(0, min(e["y"], sh - TITLE_H))

    def clamp_all(self):
        for wid in self.order:
            self.clamp(wid)

    def bring_to_front(self, wid):
        top = max(e["z"] for e in self.layout.values())
        self.layout[wid]["z"] = top + 1

    # ------------------------------------------------------------------ état visible
    def visible(self):
        """[(spec, entry, collapsed)] du dessous vers le dessus, en tenant compte du mode Focus."""
        out = []
        for wid in sorted(self.order, key=lambda w: self.layout[w]["z"]):
            e, spec = self.layout[wid], self.specs[wid]
            if not e["enabled"]:
                continue
            collapsed = e["collapsed"]
            if self.focus_active and spec.chrome:
                if e["focus"] == "hide":
                    continue
                if e["focus"] == "shrink":
                    collapsed = True
            out.append((spec, e, collapsed))
        return out

    # ------------------------------------------------------------------ dessin
    def draw(self, ui, ctx):
        self._hits = []
        self.web_state = {wid: {"rect": None, "enabled": self.layout[wid]["enabled"]}
                          for wid, spec in self.specs.items() if spec.web}
        for spec, e, collapsed in self.visible():
            self.clamp(spec.id)
            x, y, w = e["x"], e["y"], e["w"]
            h = TITLE_H if collapsed else e["h"]
            rect = pygame.Rect(x, y, w, h)
            if not spec.chrome:
                self._draw_bare(ui, ctx, spec, rect)
                continue
            ui.frame(rect)
            self._hits.append((rect, spec.id, "body"))
            bar = pygame.Rect(x + 3, y + 3, w - 6, TITLE_H - 6)
            pygame.draw.rect(ui.screen, C["header"], bar, border_radius=5)
            pygame.draw.rect(ui.screen, C["header_border"], bar, 1, border_radius=5)
            shrunk = self.focus_active and e["focus"] == "shrink"
            ui.text(ui.fit(spec.title, "small", w - 90), "small", "gray" if shrunk else "gold",
                    (x + 12, y + TITLE_H // 2), anchor="midleft", shadow=True)
            self._hits.append((bar, spec.id, "title"))
            if not self.locked:
                bx = x + w - 10
                if spec.closable:
                    bx -= 18
                    self._icon_button(ui, pygame.Rect(bx, y + 7, 14, 14), "x")
                    self._hits.append((pygame.Rect(bx - 2, y + 4, 18, 20), spec.id, "close"))
                bx -= 20
                self._icon_button(ui, pygame.Rect(bx, y + 7, 14, 14), "+" if collapsed else "-")
                self._hits.append((pygame.Rect(bx - 2, y + 4, 18, 20), spec.id, "collapse"))
            if collapsed:
                continue
            body = pygame.Rect(x + 6, y + TITLE_H + 2, w - 12, h - TITLE_H - 8)
            if spec.web:       # zone transparente : la fenêtre web du processus isolé est visible (et cliquable) à travers
                pygame.draw.rect(ui.screen, COLOR_KEY, body)
                self.web_state[spec.id]["rect"] = (body.x, body.y, body.w, body.h)
            ui.clip_push(body)
            try:
                spec.draw(ui, ctx, body)
            finally:
                ui.clip_pop()
            if not self.locked:
                grip = pygame.Rect(x + w - 16, y + h - 16, 14, 14)
                for k in (4, 8, 12):
                    pygame.draw.line(ui.screen, C["frame_hi"], (grip.right - k, grip.bottom - 2), (grip.right - 2, grip.bottom - k), 1)
                self._hits.append((grip, spec.id, "resize"))

    def _draw_bare(self, ui, ctx, spec, rect):
        """Widget sans cadre standard (barre d'outils) : une poignée à gauche pour le déplacer."""
        ui.frame(rect)
        self._hits.append((rect, spec.id, "body"))
        grip = pygame.Rect(rect.x + 2, rect.y + 2, 16, rect.h - 4)
        for k in range(3):
            pygame.draw.line(ui.screen, C["frame_hi"], (grip.x + 5 + k * 3, grip.y + 6), (grip.x + 5 + k * 3, grip.bottom - 6), 1)
        self._hits.append((grip, spec.id, "title"))
        inner = pygame.Rect(rect.x + 20, rect.y + 3, rect.w - 24, rect.h - 6)
        ui.clip_push(inner)
        try:
            spec.draw(ui, ctx, inner)
        finally:
            ui.clip_pop()

    @staticmethod
    def _icon_button(ui, rect, kind):
        hover = rect.collidepoint(mousepos.get())
        color = C["gold"] if hover else C["light_gray"]
        pygame.draw.rect(ui.screen, (30, 30, 36), rect, border_radius=3)
        pygame.draw.rect(ui.screen, color, rect, 1, border_radius=3)
        cx, cy = rect.center
        if kind in ("x", "+", "-"):
            pygame.draw.line(ui.screen, color, (cx - 3, cy), (cx + 3, cy), 1) if kind != "x" else None
            if kind == "+":
                pygame.draw.line(ui.screen, color, (cx, cy - 3), (cx, cy + 3), 1)
            if kind == "x":
                pygame.draw.line(ui.screen, color, (cx - 3, cy - 3), (cx + 3, cy + 3), 1)
                pygame.draw.line(ui.screen, color, (cx - 3, cy + 3), (cx + 3, cy - 3), 1)

    # ------------------------------------------------------------------ événements
    def on_event(self, event, ui=None):
        """Retourne True si l'événement a été consommé (déplacement, redimensionnement, réduire, fermer)."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, wid, kind in reversed(self._hits):
                if not rect.collidepoint(event.pos):
                    continue
                self.bring_to_front(wid)
                e = self.layout[wid]
                if kind == "close":
                    self.set_enabled(wid, False)
                    return True
                if kind == "collapse":
                    e["collapsed"] = not e["collapsed"]
                    self.save()
                    return True
                if kind == "title" and not self.locked:
                    self._drag = {"id": wid, "mode": "move", "dx": event.pos[0] - e["x"], "dy": event.pos[1] - e["y"]}
                    return True
                if kind == "resize" and not self.locked:
                    self._drag = {"id": wid, "mode": "resize", "dx": e["w"] - event.pos[0], "dy": e["h"] - event.pos[1]}
                    return True
                return False      # clic dans le corps : les boutons du widget s'en occupent
            return False
        if event.type == pygame.MOUSEMOTION and self._drag:
            d, e = self._drag, self.layout[self._drag["id"]]
            if d["mode"] == "move":
                e["x"], e["y"] = event.pos[0] - d["dx"], event.pos[1] - d["dy"]
                self._snap(d["id"])
            else:
                e["w"], e["h"] = event.pos[0] + d["dx"], event.pos[1] + d["dy"]
            self.clamp(d["id"])
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._drag:
            self.layout[self._drag["id"]]["auto"] = False      # déplacé / redimensionné à la main : on ne le touche plus
            self._drag = None
            self.save()
            return True
        return False

    def _snap(self, wid, margin=12):
        """Aimantation aux bords de l'écran et aux autres widgets."""
        e = self.layout[wid]
        sw, sh = self.screen_size
        w = e["w"]
        h = TITLE_H if e["collapsed"] else e["h"]
        if abs(e["x"]) < margin:
            e["x"] = 0
        if abs(e["x"] + w - sw) < margin:
            e["x"] = sw - w
        if abs(e["y"]) < margin:
            e["y"] = 0
        if abs(e["y"] + h - sh) < margin:
            e["y"] = sh - h
        for other, o in self.layout.items():
            if other == wid or not o["enabled"]:
                continue
            oh = TITLE_H if o["collapsed"] else o["h"]
            if abs(e["x"] - (o["x"] + o["w"])) < margin:
                e["x"] = o["x"] + o["w"] + 4
            if abs((e["x"] + w) - o["x"]) < margin:
                e["x"] = o["x"] - w - 4
            if abs(e["y"] - (o["y"] + oh)) < margin:
                e["y"] = o["y"] + oh + 4
            if abs((e["y"] + h) - o["y"]) < margin:
                e["y"] = o["y"] - h - 4
