"""
Fenêtre overlay (Windows) : sans bordure, au premier plan, transparente.
Le fond est une couleur-clé : les pixels de cette couleur sont transparents ET laissent passer les clics vers WoW.
Tout est protégé : hors Windows (ou en cas d'erreur) les fonctions ne font rien et l'appli reste utilisable en fenêtre.
"""
import sys

IS_WINDOWS = sys.platform.startswith("win")
COLOR_KEY = (255, 0, 255)          # magenta : couleur transparente

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_LWA_COLORKEY = 0x1
_LWA_ALPHA = 0x2
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOACTIVATE, _SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40
_SW_HIDE, _SW_SHOWNOACTIVATE, _SW_SHOW = 0, 4, 5


def _user32():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    # types explicites : sans eux, les identifiants de fenêtre 64 bits seraient tronqués
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    return user32


def window_handle():
    """Identifiant de la fenêtre pygame (ou None)."""
    try:
        import pygame
        return pygame.display.get_wm_info().get("window")
    except Exception:
        return None


def find_window(title):
    """Identifiant (HWND) d'une fenêtre d'après son titre, ou None."""
    if not IS_WINDOWS:
        return None
    try:
        hwnd = _user32().FindWindowW(None, title)
        return hwnd or None
    except Exception:
        return None


def list_monitors():
    """Écrans : [(x, y, largeur, hauteur)] (le premier est l'écran principal). Repli : écrans vus par pygame."""
    monitors = []
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

            def callback(_hmon, _hdc, rect, _data):
                r = rect.contents
                monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
                return 1
            user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
            monitors.sort(key=lambda m: (m[0] != 0 or m[1] != 0, m[0], m[1]))     # écran principal (0,0) en premier
        except Exception:
            monitors = []
    if not monitors:
        try:
            import pygame
            x = 0
            for width, height in pygame.display.get_desktop_sizes():
                monitors.append((x, 0, width, height))
                x += width
        except Exception:
            monitors = [(0, 0, 1920, 1080)]
    return monitors


def apply_overlay_style(hwnd, opacity_percent=100, topmost=True):
    """Couleur-clé transparente + opacité globale + premier plan. Retourne True si appliqué."""
    if not (IS_WINDOWS and hwnd):
        return False
    try:
        from ctypes import wintypes
        user32 = _user32()
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED)
        r, g, b = COLOR_KEY
        alpha = max(40, min(100, int(opacity_percent))) * 255 // 100
        user32.SetLayeredWindowAttributes(hwnd, r | (g << 8) | (b << 16), alpha, _LWA_COLORKEY | _LWA_ALPHA)
        set_topmost(hwnd, topmost)
        return True
    except Exception as e:
        print(f"Overlay : style non appliqué ({e})")
        return False


def clear_overlay_style(hwnd):
    if not (IS_WINDOWS and hwnd):
        return
    try:
        user32 = _user32()
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style & ~_WS_EX_LAYERED)
        set_topmost(hwnd, False)
    except Exception:
        pass


def set_topmost(hwnd, topmost):
    if not (IS_WINDOWS and hwnd):
        return
    try:
        from ctypes import wintypes
        user32 = _user32()
        user32.SetWindowPos(hwnd, wintypes.HWND(-1 if topmost else -2), 0, 0, 0, 0,
                            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
    except Exception:
        pass


def show_window(hwnd, visible):
    if not (IS_WINDOWS and hwnd):
        return
    try:
        _user32().ShowWindow(hwnd, _SW_SHOWNOACTIVATE if visible else _SW_HIDE)
    except Exception:
        pass


def find_game_rect():
    """(x, y, largeur, hauteur) de la zone client de la fenêtre de WoW, ou None."""
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _user32()
        for window_class in ("GxWindowClass", "GxWindowClassD3d"):
            hwnd = user32.FindWindowW(window_class, None)
            if hwnd:
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                point = wintypes.POINT(0, 0)
                user32.ClientToScreen(hwnd, ctypes.byref(point))
                if rect.right > 200 and rect.bottom > 200:
                    return point.x, point.y, rect.right, rect.bottom
    except Exception:
        pass
    return None
