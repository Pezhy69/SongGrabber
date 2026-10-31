"""Pfade, Einstellungen und Prozess-Hilfen – alles portabel, ohne Installation."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading

APP_NAME = "SongGrabber"
VERSION = "1.11.0"
# Wo neue Versionen veröffentlicht werden. GitHub: "https://api.github.com/repos/<Name>/SongGrabber/releases/latest"
# oder eine eigene JSON-Datei {"version": "1.9.0", "url": "https://…", "notes": "…"}. Leer = Prüfung aus.
UPDATE_URL = "https://api.github.com/repos/Pezhy69/SongGrabber/releases/latest"
IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0


def app_dir():
    """Ordner der .exe (bzw. des Projekts im Entwicklungsmodus)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def res_dir():
    """Ordner mit mitgelieferten Ressourcen (ui/, bin/)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_dir())
    return app_dir()


OLD_NAME = "AudioGrabber"          # früherer Programmname – Daten werden einmalig übernommen
_migrated = False


def data_dir():
    """Einstellungen: portabel neben der .exe, falls 'portable.txt' existiert, sonst %APPDATA%."""
    global _migrated
    if os.path.exists(os.path.join(app_dir(), "portable.txt")):
        d, old = os.path.join(app_dir(), "data"), None
    elif IS_WIN and os.environ.get("APPDATA"):
        d, old = os.path.join(os.environ["APPDATA"], APP_NAME), os.path.join(os.environ["APPDATA"], OLD_NAME)
    else:                                   # Linux: ~/.config/SongGrabber (XDG)
        d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), APP_NAME)
        old = os.path.join(os.path.expanduser("~"), ".songgrabber")
    if not _migrated:
        _migrated = True
        if old and os.path.isdir(old) and not os.path.exists(d):
            try:            # Einstellungen, Bibliothek, Abos, aktualisierte Werkzeuge übernehmen
                shutil.copytree(old, d, ignore=shutil.ignore_patterns("temp", "webview", "ipc.json"))
            except OSError:
                pass
    os.makedirs(d, exist_ok=True)
    return d


def temp_dir():
    d = os.path.join(data_dir(), "temp")
    os.makedirs(d, exist_ok=True)
    return d


def default_music_dir():
    if not IS_WIN:
        try:
            from . import osint
            return os.path.join(osint.music_dir(), APP_NAME)
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Music", APP_NAME)


DEFAULTS = {
    "output_dir": default_music_dir(),
    "preset": "mp3_v0",
    "normalize": "off",            # off | peak | loud
    "trim_silence": False,
    "name_single": "{albumartist}/{album}/{track:02} - {title}",
    "name_album": "{albumartist}/{album}/{track:02} - {title}",
    "embed_cover": True,
    "square_cover": True,
    "playlist_m3u": True,
    "cd_verify": True,
    "cd_eject": False,
    "musicbrainz": True,
    "rec_samplerate": 48000,
    "rec_bitdepth": 24,
    "keep_raw": False,
    "tools_dir": "",               # leer = eigener bin-Ordner; sonst z. B. bin-Ordner des Video Downloaders
    "watch_enabled": False,
    "watch_dir": os.path.join(default_music_dir(), "_Übergabe"),
    "watch_delete_source": False,
    "metadata_online": True,       # Album/Genre/Jahr/Cover über iTunes + MusicBrainz ergänzen
    "prefer_album_cover": True,    # Albumcover statt Video-Vorschaubild
    "skip_existing": True,         # schon vorhandene Titel nicht doppelt speichern
    "auto_playlist_links": True,   # Link-Playlists automatisch als .m3u8 anlegen
    "clipboard_watch": True,       # Links in der Zwischenablage erkennen
    "volume": 0.8,
    "layout_v": 2,
    "live_check": True,            # bei Live-Auftritten nach dem Original fragen
    "welcome_done": False,
    "seen_version": "",
    "viz_fx": True,
    "pp_info_min": True,
    "viz_custom": None,
    "setup_stamp": "",
    "update_check": True,          # beim Start (einmal am Tag) nach neuer Version sehen
    "update_last": 0,
    "update_skip": "",
    "xfade": 4,                    # Player: Überblenden in Sekunden (0 = aus)
    "pp_side_off": False,          # Player: rechte Leiste (Warteschlange/Songtext) weggeschoben
    "pp_side_auto": True,          # Player: rechte Leiste nach 1 Minute ohne Bedienung wegschieben
    "screen_hint_ok": False,       # Bildschirmaufnahme: Einverständnis-Hinweis gelesen
    "screen_opts": {},             # Bildschirmaufnahme: zuletzt gewählte Einstellungen
    "norm_play": True,             # Player: Lautstärke der Titel angleichen             # zuletzt vom Setup übernommener Musik-Ordner            # Player: eigene Farben {c0, c1, c2, sun0, sun1, sky}           # Player: Cover & Titel klein oben links (wie ein Senderlogo)                # Player: Lichtshow & Effekte an/aus
    "viz_mode": "synth",           # Player: synth | bars | ring | wave | off
    "viz_theme": "synth",          # Player-Farbwelt
    "eq_gains": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "eq_preset": "flat",
    "eq_on": True,            # zuletzt gestartete Version – für „Neu in dieser Version“
    "lyrics_auto": True,           # Songtexte automatisch einbetten (LRCLIB)
    "lyrics_lrc": False,           # zusätzlich .lrc-Datei neben dem Titel
    "acoustid_key": "",            # kostenloser Schlüssel von acoustid.org
    "acoustid_auto": True,         # Aufnahmen automatisch erkennen
    "abo_hours": 6,                # Abos alle x Stunden prüfen
}
OLD_SINGLE = "{artist} - {title}"

_settings_lock = threading.Lock()
_settings = None


def settings():
    global _settings
    with _settings_lock:
        if _settings is None:
            s = dict(DEFAULTS)
            p = os.path.join(data_dir(), "settings.json")
            try:
                with open(p, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                s.update({k: v for k, v in saved.items() if k in DEFAULTS})
                if saved.get("layout_v", 1) < 2:            # Umstellung auf Interpret/Album/Titel
                    if s["name_single"] == OLD_SINGLE:
                        s["name_single"] = DEFAULTS["name_single"]
                    s["layout_v"] = 2
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(s, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            _setup_folder(s)
            _settings = s
        return dict(_settings)


REG_KEY = r"Software\SongGrabber"


def _portable():
    return os.path.exists(os.path.join(app_dir(), "portable.txt"))


def _setup_folder(s):
    """Vom Setup gewählten Musik-Ordner übernehmen (nur wenn er dort neu gewählt wurde) und den
    aktuellen Ordner für das nächste Setup hinterlegen."""
    if not IS_WIN or _portable():
        return
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            try:
                stamp = winreg.QueryValueEx(k, "OutputDirStamp")[0]
                chosen = winreg.QueryValueEx(k, "SetupOutputDir")[0]
            except OSError:
                stamp, chosen = "", ""
            if stamp and chosen and stamp != s.get("setup_stamp"):
                s["output_dir"], s["setup_stamp"] = chosen, stamp
                try:
                    os.makedirs(chosen, exist_ok=True)
                    with open(os.path.join(data_dir(), "settings.json"), "w", encoding="utf-8") as f:
                        json.dump(s, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            winreg.SetValueEx(k, "OutputDir", 0, winreg.REG_SZ, s.get("output_dir") or "")
    except Exception:
        pass


def _remember_folder(path):
    if not IS_WIN or _portable():
        return
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            winreg.SetValueEx(k, "OutputDir", 0, winreg.REG_SZ, path or "")
    except Exception:
        pass


def save_settings(new):
    global _settings
    s = settings()
    s.update({k: v for k, v in (new or {}).items() if k in DEFAULTS})
    with _settings_lock:
        _settings = s
        with open(os.path.join(data_dir(), "settings.json"), "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    if "output_dir" in (new or {}):
        _remember_folder(s.get("output_dir"))
    return dict(s)


# ---------------------------------------------------------------- Werkzeuge

def bin_dirs():
    dirs = []
    custom = settings().get("tools_dir")
    if custom:
        dirs.append(custom)
    dirs.append(os.path.join(data_dir(), "bin"))   # aktualisierte Werkzeuge (installierte Version)
    dirs.append(os.path.join(app_dir(), "bin"))
    dirs.append(os.path.join(res_dir(), "bin"))
    return dirs


def find_bin(name):
    exe = name + (".exe" if IS_WIN else "")
    for d in bin_dirs():
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        test = os.path.join(folder, ".schreibtest")
        with open(test, "w") as f:
            f.write("x")
        os.remove(test)
        return True
    except OSError:
        return False


def ffmpeg():
    return find_bin("ffmpeg")


def ffprobe():
    return find_bin("ffprobe")


def ytdlp():
    return find_bin("yt-dlp")


def popen(args, **kw):
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    kw.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(args, **kw)


def run(args, timeout=None, **kw):
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    kw.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(args, capture_output=True, timeout=timeout, **kw)


def tool_version(path, arg="-version"):
    if not path:
        return None
    try:
        r = run([path, arg], timeout=15)
        line = (r.stdout or r.stderr).decode("utf-8", "replace").strip().splitlines()[0]
        return line[:80]
    except Exception:
        return None


# ---------------------------------------------------------------- Dateinamen

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean(value):
    v = _BAD.sub("_", str(value)).strip().rstrip(". ")
    return v[:150] or "Unbekannt"


FALLBACK = {"album": "Singles", "artist": "Unbekannter Interpret", "albumartist": "Unbekannter Interpret",
            "genre": "Ohne Genre", "date": "Ohne Jahr", "title": "Unbenannt"}


class _Safe(dict):
    def __missing__(self, key):
        return FALLBACK.get(key, "Unbekannt")


LAYOUTS = {
    "artist_album": ("{albumartist}/{album}/{track:02} - {title}", "{albumartist}/{album}/{track:02} - {title}"),
    "artist": ("{artist}/{artist} - {title}", "{albumartist}/{album}/{track:02} - {title}"),
    "flat": ("{artist} - {title}", "{albumartist} - {album}/{track:02} - {title}"),
    "genre": ("{genre}/{albumartist}/{album}/{track:02} - {title}", "{genre}/{albumartist}/{album}/{track:02} - {title}"),
}


def ensure_output(base):
    """Zielordner anlegen – mit verständlicher Meldung, wenn Netzlaufwerk/NAS/USB-Platte fehlt."""
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except OSError:
        raise RuntimeError(f"Zielordner nicht erreichbar: {base} – ist das Netzlaufwerk, NAS oder die "
                           f"externe Festplatte eingeschaltet und verbunden? (Zielordner unten rechts ändern)")


def build_path(base, template, tags, ext, make_unique=True):
    """Zielpfad aus Vorlage. Ohne Album → Ordner „Singles“, ohne Titelnummer → kein „00 - “."""
    vals = _Safe()
    for k, v in tags.items():
        if v not in (None, ""):
            vals[k] = v if isinstance(v, int) else clean(v)
    if "albumartist" not in vals and "album_artist" in vals:
        vals["albumartist"] = vals["album_artist"]
    if "albumartist" not in vals and "artist" in vals:
        vals["albumartist"] = vals["artist"]
    if "date" in vals:
        vals["date"] = str(vals["date"])[:4]
    try:
        vals["track"] = int(str(tags.get("track", 0)).split("/")[0] or 0)
    except ValueError:
        vals["track"] = 0
    try:
        rel = template.format_map(vals)
    except Exception:
        rel = "{artist} - {title}".format_map(vals)
    parts = [clean(p) for p in re.split(r"[\\/]+", rel) if p.strip()]
    if parts and not vals["track"]:
        parts[-1] = re.sub(r"^0+\s*[-.–]\s*", "", parts[-1]) or parts[-1]
    path = os.path.join(base, *parts) + "." + ext
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return unique(path) if make_unique else path


def playlist_dir():
    d = os.path.join(settings()["output_dir"], "Playlists")
    os.makedirs(d, exist_ok=True)
    return d


def unique(path):
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{root} ({i}){ext}"):
        i += 1
    return f"{root} ({i}){ext}"


# ---------------------------------------------------------------- Fehlerprotokoll

import logging  # noqa: E402
import logging.handlers  # noqa: E402

log = logging.getLogger("songgrabber")


def log_file():
    return os.path.join(data_dir(), "songgrabber.log")


def setup_logging():
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    try:
        h = logging.handlers.RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())
    import platform
    log.info("Start %s %s · Windows %s · Python %s · %s", APP_NAME, VERSION, platform.version(),
             platform.python_version(), "portabel" if os.path.exists(os.path.join(app_dir(), "portable.txt")) else "installiert")
    return log


def log_tail(lines=60):
    try:
        with open(log_file(), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""
