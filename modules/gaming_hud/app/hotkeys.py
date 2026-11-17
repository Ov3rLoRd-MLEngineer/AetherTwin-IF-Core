"""
Raccourcis clavier GLOBAUX (Windows) : fonctionnent même quand WoW a le focus.
Les actions sont placées dans une file que la boucle principale lit (poll()).
Hors Windows, la classe ne fait rien : les raccourcis restent utilisables dans la fenêtre de l'appli.
"""
import queue
import sys
import threading

IS_WINDOWS = sys.platform.startswith("win")

_MODS = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
_NAMED = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "insert": 0x2D, "delete": 0x2E, "home": 0x24,
          "end": 0x23, "pageup": 0x21, "pagedown": 0x22}
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012


def parse_hotkey(text):
    """'Ctrl+Alt+H' -> (modificateurs, code de touche virtuelle) ; None si invalide."""
    if not text:
        return None
    mods, key = 0, None
    for part in [p.strip().lower() for p in str(text).split("+") if p.strip()]:
        if part in _MODS:
            mods |= _MODS[part]
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            key = 0x70 + int(part[1:]) - 1
        elif part in _NAMED:
            key = _NAMED[part]
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        else:
            return None
    return (mods, key) if key is not None else None


class Hotkeys:
    def __init__(self):
        self.events = queue.Queue()
        self._thread = None
        self._thread_id = None
        self.error = ""
        self.registered = []

    def start(self, bindings):
        """bindings : {action: 'F9', ...}. Relance proprement si déjà démarré."""
        self.stop()
        if not IS_WINDOWS:
            self.error = "Raccourcis globaux disponibles sous Windows uniquement"
            return False
        parsed = {action: parse_hotkey(text) for action, text in bindings.items()}
        self._thread = threading.Thread(target=self._run, args=(parsed,), daemon=True)
        self._thread.start()
        return True

    def _run(self, parsed):
        try:
            import ctypes
            from ctypes import wintypes
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()
            ids, self.registered, failed = {}, [], []
            for index, (action, spec) in enumerate(parsed.items(), start=1):
                if spec and user32.RegisterHotKey(None, index, spec[0] | _MOD_NOREPEAT, spec[1]):
                    ids[index] = action
                    self.registered.append(action)
                else:
                    failed.append(action)
            self.error = ("Raccourci(s) indisponible(s) : " + ", ".join(failed)) if failed else ""
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == _WM_HOTKEY and msg.wParam in ids:
                    self.events.put(ids[msg.wParam])
            for index in ids:
                user32.UnregisterHotKey(None, index)
        except Exception as e:
            self.error = f"Raccourcis globaux : {e}"

    def stop(self):
        if IS_WINDOWS and self._thread and self._thread_id:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
            except Exception:
                pass
        self._thread, self._thread_id = None, None

    def poll(self):
        """Actions reçues depuis le dernier appel."""
        actions = []
        while True:
            try:
                actions.append(self.events.get_nowait())
            except queue.Empty:
                return actions
