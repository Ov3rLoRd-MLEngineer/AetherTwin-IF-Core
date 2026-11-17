"""
Gestionnaire de captures d'écran pour la vision de l'assistant IA.

Deux façons d'obtenir une image :
  1. Bouton / raccourci de capture : l'overlay se masque brièvement, la fenêtre de WoW est capturée, puis il réapparaît.
  2. Presse-papier : dès qu'une nouvelle image y est déposée (Win + Maj + S), une notification propose de la joindre.
Les images jointes sont réduites et encodées en JPEG avant d'être envoyées avec la question.
Dépendance : Pillow (pip install pillow), chargée seulement à l'usage.
"""
import base64
import hashlib
import io
import threading
import time


class Attachment:
    def __init__(self, image, source):
        self.image = image            # image Pillow (RGB)
        self.source = source          # "capture" ou "presse-papier"
        self.created = time.time()
        self._thumb = None

    @property
    def size(self):
        return self.image.size

    def thumb_surface(self, size=(160, 90)):
        """Miniature pygame (mise en cache)."""
        if self._thumb is None:
            import pygame
            img = self.image.copy()
            img.thumbnail(size)
            self._thumb = pygame.image.fromstring(img.tobytes(), img.size, "RGB")
        return self._thumb

    def encode(self, max_edge=1600, quality=80):
        """(type MIME, base64) d'une version JPEG réduite."""
        img = self.image.convert("RGB")
        if max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge))
        buffer = io.BytesIO()
        img.save(buffer, "JPEG", quality=quality)
        return "image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii")


class VisionManager:
    def __init__(self, settings, grab=None, clipboard=None, hide=None, show=None, game_rect=None):
        self.settings = settings
        self._grab = grab or self._default_grab
        self._clipboard = clipboard or self._default_clipboard
        self._hide = hide or (lambda: None)
        self._show = show or (lambda: None)
        self._game_rect = game_rect or (lambda: None)
        self.attachments = []
        self.toast = None             # capture du presse-papier en attente de décision
        self.toast_until = 0.0
        self.error = ""
        self._last_sig = None
        self._primed = False
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ sources par défaut (Pillow)
    @staticmethod
    def _default_grab(bbox):
        from PIL import ImageGrab
        try:
            return ImageGrab.grab(bbox=bbox, all_screens=True)
        except TypeError:             # anciennes versions de Pillow
            return ImageGrab.grab(bbox=bbox)

    @staticmethod
    def _default_clipboard():
        from PIL import Image, ImageGrab
        data = ImageGrab.grabclipboard()
        return data if isinstance(data, Image.Image) else None

    # ------------------------------------------------------------------ pièces jointes
    def add(self, image, source):
        att = Attachment(image.convert("RGB"), source)
        with self._lock:
            self.attachments.append(att)
            del self.attachments[:-4]                 # 4 images maximum
        return att

    def remove(self, index):
        with self._lock:
            if 0 <= index < len(self.attachments):
                del self.attachments[index]

    def clear(self):
        with self._lock:
            self.attachments = []

    def payload(self):
        """[(mime, base64)] des images jointes, prêtes pour l'envoi."""
        max_edge = int(self.settings.get("vision.max_edge", 1600))
        return [a.encode(max_edge) for a in list(self.attachments)]

    # ------------------------------------------------------------------ capture de la fenêtre du jeu
    def capture_game(self):
        """Masque l'overlay un court instant, capture la fenêtre de WoW (ou tout l'écran), le réaffiche."""
        self.error = ""
        rect = self._game_rect()
        bbox = (rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]) if rect else None
        delay = max(0, int(self.settings.get("vision.hide_ms", 80))) / 1000.0
        try:
            self._hide()
            time.sleep(delay)
            image = self._grab(bbox)
        except ImportError:
            self.error = "Pillow est requis pour les captures : pip install pillow"
            return None
        except Exception as e:
            self.error = f"Capture impossible : {e}"
            return None
        finally:
            try:
                self._show()
            except Exception:
                pass
        return self.add(image, "capture")

    # ------------------------------------------------------------------ presse-papier (Win + Maj + S)
    @staticmethod
    def _signature(image):
        small = image.convert("RGB").resize((24, 24))
        return f"{image.size}-{hashlib.md5(small.tobytes()).hexdigest()}"

    def start_watch(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop_watch(self):
        self._stop.set()

    def check_clipboard(self):
        """Une lecture du presse-papier ; retourne True si une nouvelle image a été détectée."""
        try:
            image = self._clipboard()
        except ImportError:
            self.error = "Pillow est requis pour surveiller le presse-papier : pip install pillow"
            self._stop.set()
            return False
        except Exception:
            return False
        if image is None:
            return False
        signature = self._signature(image)
        if signature == self._last_sig:
            return False
        self._last_sig = signature
        if not self._primed:          # première lecture : l'image déjà présente au démarrage est ignorée
            self._primed = True
            return False
        self.toast = Attachment(image.convert("RGB"), "presse-papier")
        self.toast_until = time.time() + 20
        return True

    def _watch(self):
        # on mémorise d'abord ce qui est déjà dans le presse-papier pour ne pas le proposer au lancement
        self.check_clipboard()
        self._primed = True
        while not self._stop.wait(0.6):
            if self.settings.get("vision.watch_clipboard", True):
                self.check_clipboard()

    def accept_toast(self):
        if self.toast is not None:
            with self._lock:
                self.attachments.append(self.toast)
                del self.attachments[:-4]
            self.toast = None

    def dismiss_toast(self):
        self.toast = None

    def active_toast(self):
        if self.toast is not None and time.time() > self.toast_until:
            self.toast = None
        return self.toast
