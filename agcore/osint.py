"""Linux-Gegenstücke zu den Windows-Funktionen: Öffnen, Zwischenablage, Papierkorb, Wechseldatenträger,
Autostart, „nur ein Fenster“ und Musik-Ordner. Windows nutzt weiter die bisherigen Wege."""
import os
import shutil
import subprocess
import sys

from . import paths

LINUX = sys.platform.startswith("linux")


def _run(args, inp=None, timeout=4):
    try:
        return subprocess.run(args, input=inp, capture_output=True, timeout=timeout)
    except Exception:
        return None


# ---------------------------------------------------------------- Öffnen
def open_path(p, reveal=False):
    """Datei/Ordner im Dateimanager öffnen. reveal=True: Ordner öffnen und Datei markieren (wenn möglich)."""
    if reveal and os.path.isfile(p):
        uri = "file://" + os.path.abspath(p)
        r = _run(["dbus-send", "--session", "--dest=org.freedesktop.FileManager1", "--type=method_call",
                  "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                  f"array:string:{uri}", "string:"])
        if r is not None and r.returncode == 0:
            return True
        p = os.path.dirname(p)
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if not opener:
        return False
    args = [opener, "open", p] if opener.endswith("gio") else [opener, p]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True


# ---------------------------------------------------------------- Zwischenablage
def clipboard_get():
    for args in (["wl-paste", "--no-newline"], ["xclip", "-o", "-selection", "clipboard"], ["xsel", "-ob"]):
        if shutil.which(args[0]):
            r = _run(args)
            if r is not None and r.returncode == 0:
                return r.stdout.decode("utf-8", "replace").strip()
    return ""


def clipboard_set(text):
    for args in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]):
        if shutil.which(args[0]):
            r = _run(args, inp=text.encode("utf-8"))
            if r is not None and r.returncode == 0:
                return True
    return False


# ---------------------------------------------------------------- Papierkorb
def trash(files):
    """In den Papierkorb (freedesktop). → Liste der verschobenen Dateien"""
    done = []
    try:
        from send2trash import send2trash
    except Exception:
        send2trash = None
    for f in files:
        try:
            if send2trash:
                send2trash(f)
            else:
                _trash_home(f)
            done.append(f)
        except Exception:
            pass
    return done


def _trash_home(f):
    import datetime
    import urllib.parse
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "Trash")
    os.makedirs(os.path.join(base, "files"), exist_ok=True)
    os.makedirs(os.path.join(base, "info"), exist_ok=True)
    name, i = os.path.basename(f), 1
    stem, ext = os.path.splitext(name)
    while os.path.exists(os.path.join(base, "files", name)) or os.path.exists(os.path.join(base, "info", name + ".trashinfo")):
        i += 1
        name = f"{stem}.{i}{ext}"
    with open(os.path.join(base, "info", name + ".trashinfo"), "w", encoding="utf-8") as fh:
        fh.write(f"[Trash Info]\nPath={urllib.parse.quote(os.path.abspath(f))}\n"
                 f"DeletionDate={datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    shutil.move(f, os.path.join(base, "files", name))


# ---------------------------------------------------------------- Wechseldatenträger
def drives():
    """USB-Sticks/SD-Karten/Handys, die unter /media/<user> bzw. /run/media/<user> eingehängt sind."""
    user = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    out, seen = [], set()
    for base in (f"/media/{user}", f"/run/media/{user}", "/media"):
        if not os.path.isdir(base):
            continue
        for n in sorted(os.listdir(base)):
            root = os.path.join(base, n)
            if root in seen or not os.path.ismount(root):
                continue
            seen.add(root)
            try:
                du = shutil.disk_usage(root)
            except OSError:
                continue
            out.append({"root": root, "label": n, "fs": "", "free": du.free, "total": du.total})
    return out


# ---------------------------------------------------------------- Autostart
def _autostart_file():
    d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart")
    return os.path.join(d, "songgrabber.desktop")


def launch_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    start = os.path.join(paths.app_dir(), "songgrabber")             # Startskript aus install.sh
    if os.path.isfile(start):
        return f'"{start}"'
    return f'"{sys.executable}" "{os.path.join(paths.app_dir(), "main.py")}"'


def autostart(enable=None):
    f = _autostart_file()
    if enable is None:
        return os.path.isfile(f)
    if enable:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=SongGrabber\n"
                     f"Exec={launch_cmd()} --minimized\nIcon=songgrabber\nX-GNOME-Autostart-enabled=true\n")
    elif os.path.isfile(f):
        os.remove(f)
    return bool(enable)


# ---------------------------------------------------------------- nur ein Fenster
_lock = None


def single_instance():
    """True, wenn diese Instanz die erste ist (Sperrdatei bleibt offen, solange SongGrabber läuft)."""
    global _lock
    import fcntl
    try:
        _lock = open(os.path.join(paths.data_dir(), "songgrabber.lock"), "w")
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Musik-Ordner
def music_dir():
    r = _run(["xdg-user-dir", "MUSIC"]) if shutil.which("xdg-user-dir") else None
    if r is not None and r.returncode == 0:
        d = r.stdout.decode("utf-8", "replace").strip()
        if d and d != os.path.expanduser("~"):
            return d
    for n in ("Musik", "Music"):
        d = os.path.join(os.path.expanduser("~"), n)
        if os.path.isdir(d):
            return d
    return os.path.join(os.path.expanduser("~"), "Musik")
