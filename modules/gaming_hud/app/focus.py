"""
Mode Focus : masque ou réduit des widgets pendant les combats.

WoW n'envoie aucune information en temps réel à une application externe (les SavedVariables ne sont écrites
qu'au rechargement). Le combat est donc détecté avec le journal de combat officiel du jeu
(Logs/WoWCombatLog*.txt, activé avec /ha combatlog on) : tant que le fichier grossit, vous êtes en combat.
Un raccourci permet aussi de forcer le mode Focus à la main.
"""
import glob
import os
import time

GROWTH_BYTES = 120        # croissance minimale du fichier pour compter comme de l'activité de combat


class CombatMonitor:
    def __init__(self, logs_dir, quiet_seconds=5):
        self.logs_dir = logs_dir
        self.quiet_seconds = quiet_seconds
        self.in_combat = False
        self.status = "inconnu"     # "combat", "calme", "pas de journal"
        self._path = None
        self._size = None
        self._last_activity = 0.0
        self._last_scan = 0.0
        self._last_poll = 0.0

    def _newest_log(self, now):
        if now - self._last_scan > 5 or not self._path:
            self._last_scan = now
            files = glob.glob(os.path.join(self.logs_dir, "WoWCombatLog*.txt"))
            self._path = max(files, key=os.path.getmtime) if files else None
        return self._path

    def update(self, now=None):
        """À appeler souvent (limité à 4 fois par seconde). Retourne True si en combat."""
        now = time.time() if now is None else now
        if now - self._last_poll < 0.25:
            return self.in_combat
        self._last_poll = now
        path = self._newest_log(now)
        if not path:
            self.in_combat, self.status = False, "pas de journal"
            self._size = None
            return False
        try:
            size = os.path.getsize(path)
        except OSError:
            self._path = None
            return self.in_combat
        if self._size is not None and size - self._size >= GROWTH_BYTES:
            self._last_activity = now
        if self._size is None or size < self._size:
            self._size = size          # première lecture, ou nouveau fichier
        else:
            self._size = size
        self.in_combat = (now - self._last_activity) < self.quiet_seconds
        self.status = "combat" if self.in_combat else "calme"
        return self.in_combat


class FocusManager:
    """Combine détection automatique et forçage manuel (None = automatique)."""

    def __init__(self, settings):
        self.settings = settings
        self.manual = None          # None : auto / True : forcé actif / False : forcé inactif
        self.combat = False

    @property
    def auto_enabled(self):
        return bool(self.settings.get("focus.auto", True))

    @property
    def active(self):
        if self.manual is not None:
            return self.manual
        return self.auto_enabled and self.combat

    def cycle_manual(self):
        """Auto -> forcé actif -> forcé inactif -> auto."""
        self.manual = {None: True, True: False, False: None}[self.manual]
        return self.label

    @property
    def label(self):
        return {None: "auto", True: "forcé (actif)", False: "forcé (inactif)"}[self.manual]
