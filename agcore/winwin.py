"""Fenster direkt über Windows steuern (Mini-Player).

pywebview-Befehle wie resize/move/on_top laufen über den Fenster-Thread und können das Fenster
einfrieren, wenn sie aus einem API-Aufruf kommen. SetWindowPos/SetWindowPlacement sind dagegen
sicher aus jedem Thread und rechnen hier mit der echten Bildschirmskalierung (DPI) und dem
Arbeitsbereich ohne Taskleiste.
"""
import ctypes
import os

_saved = None          # Fensterzustand vor dem Mini-Modus


def _api():
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.MonitorFromWindow.restype = ctypes.c_void_p
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.GetWindow.restype = wintypes.HWND
    u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    for f in ("GetWindowRect", "GetWindowPlacement", "SetWindowPlacement"):
        getattr(u, f).argtypes = [wintypes.HWND, ctypes.c_void_p]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    try:
        u.GetDpiForWindow.argtypes = [wintypes.HWND]
    except AttributeError:
        pass
    return u, wintypes


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _PLACEMENT(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint), ("showCmd", ctypes.c_uint),
                ("ptMinPosition", _POINT), ("ptMaxPosition", _POINT), ("rcNormalPosition", _RECT)]


class _MONINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


def main_window():
    """Größtes sichtbares Fenster dieses Programms (das SongGrabber-Hauptfenster)."""
    u, wt = _api()
    pid, found = os.getpid(), []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h) and not u.GetWindow(h, 4):        # 4 = GW_OWNER
            r = _RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            found.append(((r.right - r.left) * (r.bottom - r.top), h))
        return True
    u.EnumWindows(cb, 0)
    return max(found)[1] if found else None


def _dpi(h):
    try:
        return ctypes.windll.user32.GetDpiForWindow(h) or 96
    except Exception:
        return 96


def mini(on, width=460, height=150, margin=16):
    """Hauptfenster als kleine Leiste unten rechts (immer im Vordergrund) bzw. zurück."""
    global _saved
    u, _ = _api()
    h = main_window()
    if not h:
        return False
    TOPMOST, NOTOPMOST = -1, -2
    SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x1, 0x2, 0x40
    if on:
        if _saved is None:
            pl = _PLACEMENT()
            pl.length = ctypes.sizeof(_PLACEMENT)
            u.GetWindowPlacement(h, ctypes.byref(pl))
            _saved = pl
        u.ShowWindow(h, 9)                                   # SW_RESTORE (aus maximiert/minimiert holen)
        k = _dpi(h) / 96
        w, ht = int(width * k), int(height * k)
        mon = u.MonitorFromWindow(h, 2)                      # MONITOR_DEFAULTTONEAREST
        mi = _MONINFO()
        mi.cbSize = ctypes.sizeof(_MONINFO)
        u.GetMonitorInfoW(mon, ctypes.byref(mi))
        wa = mi.rcWork
        x = wa.right - w - int(margin * k)
        y = wa.bottom - ht - int(margin * k)
        u.SetWindowPos(h, TOPMOST, x, y, w, ht, SWP_SHOWWINDOW)
    else:
        u.SetWindowPos(h, NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW)
        if _saved is not None:
            u.SetWindowPlacement(h, ctypes.byref(_saved))
            _saved = None
        u.SetForegroundWindow(h)
    return True


def forget():
    """Mini-Modus wurde durch Vergrößern von Hand verlassen: nur „immer im Vordergrund“ aufheben."""
    global _saved
    _saved = None
    try:
        u, _ = _api()
        h = main_window()
        if h:
            u.SetWindowPos(h, -2, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)       # NOTOPMOST, ohne Größe/Position/Aktivieren
    except Exception:
        pass
    return True
