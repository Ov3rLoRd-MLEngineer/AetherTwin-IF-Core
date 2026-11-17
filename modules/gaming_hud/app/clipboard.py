"""
Presse-papier texte (Ctrl+C / Ctrl+V / Ctrl+X des champs de saisie).
Windows : API Win32 via ctypes (aucune dépendance). Ailleurs, ou en cas d'erreur : tampon interne à l'appli,
pour que copier/coller fonctionne au moins entre les champs de WoW Assistant.
"""
import sys
import time

IS_WINDOWS = sys.platform.startswith("win")
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_local = ""            # repli : dernier texte copié dans l'appli


def _api():
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    # types explicites : sans eux, les poignées 64 bits seraient tronquées
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    return ctypes, user32, kernel32


def _open(user32):
    """Le presse-papier peut être tenu un instant par une autre application : on réessaie brièvement."""
    for _ in range(8):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_text():
    """Texte du presse-papier ("" s'il est vide ou ne contient pas de texte)."""
    if not IS_WINDOWS:
        return _local
    try:
        ctypes, user32, kernel32 = _api()
        if not _open(user32):
            return _local
        try:
            handle = user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                return ""
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return ""
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return _local


def set_text(text):
    """Copie le texte dans le presse-papier. Retourne True si le presse-papier du système a été mis à jour."""
    global _local
    _local = text = str(text)
    if not IS_WINDOWS:
        return False
    try:
        ctypes, user32, kernel32 = _api()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not _open(user32):
            kernel32.GlobalFree(handle)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(_CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                return False
            return True                 # le système possède désormais le bloc mémoire
        finally:
            user32.CloseClipboard()
    except Exception:
        return False
