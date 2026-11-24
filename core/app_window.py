"""Fenêtres d'application d'AetherTwin : une page du Hub ouverte dans Edge (ou Chrome) en mode application, avec
l'icône d'AetherTwin dans la barre de titre et dans la barre des tâches.

Une fenêtre « --app » de Chromium porte d'habitude l'icône du navigateur dans la barre des tâches et s'y range avec
lui. `brand_window` lui donne son identité Windows (AppUserModelID propre, icône `core/web/logo.ico`, nom affiché) :
elle a alors son propre bouton dans la barre des tâches, avec le logo, et peut y être épinglée.

Hors Windows, ou si quelque chose échoue, la fenêtre s'ouvre simplement sans ces réglages.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ICON = REPO_ROOT / "core" / "web" / "logo.ico"
CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)


def find_browser(candidates: tuple[str, ...] = CANDIDATES) -> str | None:
    """Premier navigateur Chromium installé (Edge, puis Chrome), ou `None`."""
    for raw in candidates:
        path = Path(os.path.expandvars(raw))
        if "%" not in str(path) and path.is_file():
            return str(path)
    return None


def app_args(browser: str, url: str, profile: Path, size: tuple[int, int]) -> list[str]:
    """Ligne de commande (liste, jamais de shell) d'une fenêtre d'application isolée."""
    width, height = size
    return [browser, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={width},{height}",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]


def open_app(url: str, profile: Path, size: tuple[int, int], app_id: str, name: str,
             command: str) -> subprocess.Popen | None:
    """Ouvre `url` dans sa propre fenêtre d'application (avec l'icône d'AetherTwin) ; `None` sans Edge ni Chrome."""
    browser = find_browser()
    if browser is None:
        return None
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(app_args(browser, url, profile, size), stdin=subprocess.DEVNULL,  # noqa: S603
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    brand_in_background(proc.pid, app_id, name, command)
    return proc


def _windows_of(pid: int) -> list[int]:
    """Fenêtres principales visibles de Chromium appartenant au processus `pid`."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value.startswith("Chrome_WidgetWin"):
            found.append(hwnd)
        return True

    user32.EnumWindows(proto(visit), 0)
    return found


def _set_icon(hwnd: int, icon: Path) -> bool:
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_uint]
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
    ok = False
    for which, metric_x, metric_y in ((1, 11, 12), (0, 49, 50)):  # ICON_BIG (SM_CXICON), ICON_SMALL (SM_CXSMICON)
        size_x, size_y = user32.GetSystemMetrics(metric_x), user32.GetSystemMetrics(metric_y)
        handle = user32.LoadImageW(None, str(icon), 1, size_x, size_y, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if handle:
            user32.SendMessageW(hwnd, 0x80, which, handle)  # WM_SETICON
            ok = True
    return ok


def _set_identity(hwnd: int, app_id: str, name: str, icon: Path, command: str) -> bool:
    """Propriétés « AppUserModel » de la fenêtre (IPropertyStore) : identité, icône, nom, commande de relance."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    def guid(text: str) -> GUID:
        import uuid

        b = uuid.UUID(text).bytes_le
        g = GUID()
        ctypes.memmove(ctypes.byref(g), b, 16)
        return g

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                    ("value", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED (déjà initialisé : sans effet)
    store = ctypes.c_void_p()
    iid = guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")  # IID_IPropertyStore
    if shell32.SHGetPropertyStoreForWindow(ctypes.c_void_p(hwnd), ctypes.byref(iid), ctypes.byref(store)) != 0:
        return False
    vtable = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                   ctypes.POINTER(PROPVARIANT))(vtable[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    fmtid = "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"  # PKEY_AppUserModel_*
    keep = []
    ok = True
    # l'identité d'abord : les propriétés de relance n'ont de sens qu'avec elle
    for pid, text in ((5, app_id), (2, command), (3, str(icon)), (4, name)):
        buffer = ctypes.create_unicode_buffer(text)
        keep.append(buffer)
        value = PROPVARIANT(vt=31, value=ctypes.cast(buffer, ctypes.c_void_p))  # VT_LPWSTR
        key = PROPERTYKEY(guid(fmtid), pid)
        ok = set_value(store, ctypes.byref(key), ctypes.byref(value)) == 0 and ok
    ok = commit(store) == 0 and ok
    release(store)
    return ok


def brand_window(pid: int, app_id: str, name: str, command: str, icon: Path = ICON,
                 timeout_s: float = 20.0) -> int:
    """Attend les fenêtres du processus `pid` (jusqu'à `timeout_s`) et leur applique l'identité d'AetherTwin.
    Rend le nombre de fenêtres réglées (0 hors Windows)."""
    if sys.platform != "win32" or not icon.is_file():
        return 0
    done: set[int] = set()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            for hwnd in _windows_of(pid):
                if hwnd in done:
                    continue
                _set_identity(hwnd, app_id, name, icon, command)
                _set_icon(hwnd, icon)
                done.add(hwnd)
        except OSError:
            return len(done)
        if done:
            # Chromium remet parfois son icône quand la page charge son favicon : on repasse une fois
            time.sleep(1.5)
            for hwnd in done:
                _set_icon(hwnd, icon)
            return len(done)
        time.sleep(0.25)
    return len(done)


def brand_in_background(pid: int, app_id: str, name: str, command: str) -> threading.Thread:
    thread = threading.Thread(target=brand_window, args=(pid, app_id, name, command), name="app-window-icon",
                              daemon=True)
    thread.start()
    return thread
