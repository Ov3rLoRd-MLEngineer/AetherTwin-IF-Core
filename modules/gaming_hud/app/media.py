"""
Images chargées en arrière-plan (rendu officiel du personnage, montures) : l'interface ne se fige jamais pendant
un téléchargement. Une image demandée est cherchée une seule fois ; une erreur est retenue (et affichée) jusqu'au
prochain « Réessayer ».
"""
import threading

import pygame


class MediaStore:
    def __init__(self, bnet=None):
        self.bnet = bnet
        self._paths, self._errors, self._surfaces = {}, {}, {}
        self._pending = set()
        self._lock = threading.Lock()

    def available(self):
        return self.bnet is not None and self.bnet.configured()

    def request(self, key, loader):
        """Lance `loader()` (qui rend le chemin d'une image) dans un fil, une seule fois par clé."""
        with self._lock:
            if key in self._paths or key in self._errors or key in self._pending:
                return
            self._pending.add(key)

        def work():
            try:
                path, error = loader(), ""
            except Exception as e:   # réseau, API, fichier : affiché à la place de l'image
                path, error = None, str(e) or e.__class__.__name__
            with self._lock:
                self._pending.discard(key)
                if path:
                    self._paths[key] = path
                else:
                    self._errors[key] = error
        threading.Thread(target=work, daemon=True).start()

    def state(self, key):
        """« prête », « en cours », « erreur » ou « absente »."""
        with self._lock:
            if key in self._paths:
                return "prête"
            if key in self._pending:
                return "en cours"
            if key in self._errors:
                return "erreur"
            return "absente"

    def value(self, key):
        """Résultat brut du chargeur (pour une donnée qui n'est pas une image : pièces d'un ensemble…)."""
        return self._paths.get(key)

    def error(self, key):
        return self._errors.get(key, "")

    def retry(self, key):
        with self._lock:
            self._errors.pop(key, None)

    def surface(self, key):
        """Image chargée (pygame), ou None si elle n'est pas (encore) disponible ou illisible."""
        if key in self._surfaces:
            return self._surfaces[key]
        path = self._paths.get(key)
        if not path:
            return None
        try:
            image = pygame.image.load(path)
            image = image.convert_alpha() if pygame.display.get_surface() else image
            image = trim_transparent(image)
        except (pygame.error, OSError) as e:
            with self._lock:
                self._paths.pop(key, None)
                self._errors[key] = f"image illisible : {e}"
            return None
        self._surfaces[key] = image
        return image


def trim_transparent(image, margin=0.04):
    """Retire les grandes marges transparentes (le rendu du personnage occupe ~1/6 de son image 1600×1200),
    en gardant une petite marge. Une image opaque est rendue telle quelle."""
    if not image.get_flags() & pygame.SRCALPHA:
        return image
    box = image.get_bounding_rect(min_alpha=8)
    if box.w == 0 or box.h == 0 or box.w * box.h > 0.8 * image.get_width() * image.get_height():
        return image
    box = box.inflate(int(box.w * margin * 2), int(box.h * margin * 2)).clip(image.get_rect())
    return image.subsurface(box).copy()


def fit_image(image, width, height):
    """Image ajustée (agrandie au plus 3×) pour tenir dans width × height, proportions gardées."""
    scale = min(width / image.get_width(), height / image.get_height(), 3.0)
    size = (max(1, int(image.get_width() * scale)), max(1, int(image.get_height() * scale)))
    return pygame.transform.smoothscale(image, size)
