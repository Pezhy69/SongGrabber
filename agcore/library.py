"""Bibliothek: alle Audiodateien im Zielordner, Tags (schnell über mutagen, mit Zwischenspeicher)
und der Playlist-Generator."""
import json
import os
import random
import re
import threading
import time
from collections import defaultdict

from . import paths

AUDIO_EXT = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".wma"}


def _cache_path():
    return os.path.join(paths.data_dir(), "library.json")


def _first(tags, *keys):
    for k in keys:
        v = tags.get(k)
        if v:
            v = v[0] if isinstance(v, list) else v
            return str(v).strip()
    return ""


def read_tags(path):
    info = {"title": "", "artist": "", "album": "", "genre": "", "year": "", "track": 0, "duration": 0.0}
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None:
            t = f.tags or {}
            info.update({"title": _first(t, "title"), "artist": _first(t, "artist", "albumartist"),
                         "album": _first(t, "album"), "genre": _first(t, "genre"),
                         "year": _first(t, "date", "year")[:4]})
            tr = _first(t, "tracknumber")
            info["track"] = int(re.match(r"\d*", tr).group() or 0) if tr else 0
            info["duration"] = round(float(getattr(f.info, "length", 0) or 0), 1)
    except Exception:
        pass
    if not info["title"]:
        name = os.path.splitext(os.path.basename(path))[0]
        name = re.sub(r"^\d{1,3}[\s.\-_]+", "", name)
        if " - " in name and not info["artist"]:
            info["artist"], info["title"] = [x.strip() for x in name.split(" - ", 1)]
        else:
            info["title"] = name
    return info


class Library:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()
        self.scanning = False
        self.progress = (0, 0)
        try:
            with open(_cache_path(), encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def scan(self, force=False):
        if self.scanning:
            return False
        threading.Thread(target=self._scan, args=(force,), daemon=True).start()
        return True

    def _scan(self, force):
        self.scanning = True
        try:
            root = paths.settings()["output_dir"]
            found = []
            for d, _, names in os.walk(root):
                if os.path.basename(d).startswith("_"):          # z. B. _Übergabe
                    continue
                found += [os.path.join(d, n) for n in names if os.path.splitext(n)[1].lower() in AUDIO_EXT]
            items = {}
            self.progress = (0, len(found))
            for i, p in enumerate(found, 1):
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                c = self.cache.get(p)
                if force or not c or c.get("mtime") != st.st_mtime or c.get("size") != st.st_size:
                    c = read_tags(p)
                    c.update({"mtime": st.st_mtime, "size": st.st_size})
                    self.cache[p] = c
                items[p] = dict(c, path=p, format=os.path.splitext(p)[1][1:].upper())
                self.progress = (i, len(found))
            self.cache = {k: v for k, v in self.cache.items() if k in items}
            with self.lock:
                self.items = items
            try:
                with open(_cache_path(), "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, ensure_ascii=False)
            except OSError:
                pass
        finally:
            self.scanning = False

    def add(self, path):
        if os.path.splitext(path)[1].lower() not in AUDIO_EXT or not os.path.isfile(path):
            return
        st = os.stat(path)
        c = read_tags(path)
        c.update({"mtime": st.st_mtime, "size": st.st_size})
        self.cache[path] = c
        with self.lock:
            self.items[path] = dict(c, path=path, format=os.path.splitext(path)[1][1:].upper())

    def remove(self, path):
        with self.lock:
            self.items.pop(path, None)
        self.cache.pop(path, None)

    def list(self):
        with self.lock:
            return sorted(self.items.values(), key=lambda x: -x.get("mtime", 0))

    def status(self):
        return {"scanning": self.scanning, "done": self.progress[0], "total": self.progress[1],
                "count": len(self.items)}


# ---------------------------------------------------------------- Playlists

def _write(name, items, folder):
    from .pipeline import write_m3u
    return write_m3u([i["path"] for i in items], name, folder=folder)


def _sorted(items):
    return sorted(items, key=lambda i: (i.get("artist", "").lower(), i.get("album", "").lower(),
                                        i.get("track") or 0, i.get("title", "").lower()))


def generate(items, mode, opts):
    """mode: selection | artist | album | genre | decade | recent | random. Gibt erstellte Dateien zurück."""
    folder = paths.playlist_dir()
    min_n = max(1, int(opts.get("min", 3) or 1))
    prefix = (opts.get("prefix") or "").lstrip()
    out = []
    if not items:
        raise RuntimeError("Keine Titel in der Bibliothek.")

    if mode == "selection":
        sel = [i for i in items if i["path"] in set(opts.get("paths") or [])]
        if not sel:
            raise RuntimeError("Keine Titel ausgewählt.")
        out.append(_write(opts.get("name") or "Meine Playlist", sel if opts.get("keep_order") else _sorted(sel), folder))
    elif mode in ("artist", "album", "genre", "decade"):
        groups = defaultdict(list)
        for i in items:
            if mode == "decade":
                y = i.get("year", "")
                key = f"{y[:3]}0er" if len(y) >= 4 and y[:4].isdigit() else ""
            else:
                key = i.get(mode, "")
            if key:
                groups[key].append(i)
        for key, grp in sorted(groups.items()):
            if len(grp) >= min_n:
                name = key if mode != "album" else f"{grp[0].get('artist', '')} – {key}".strip(" –")
                out.append(_write(f"{prefix}{name}", _sorted(grp), folder))
    elif mode == "recent":
        days = float(opts.get("days", 30) or 30)
        cut = time.time() - days * 86400
        grp = sorted([i for i in items if i.get("mtime", 0) >= cut], key=lambda i: -i.get("mtime", 0))
        if grp:
            out.append(_write(opts.get("name") or f"Neu – letzte {int(days)} Tage", grp, folder))
    elif mode == "random":
        pool = items
        if opts.get("genre"):
            pool = [i for i in items if i.get("genre", "").lower() == opts["genre"].lower()]
        if opts.get("artist"):
            pool = [i for i in pool if opts["artist"].lower() in i.get("artist", "").lower()]
        n = min(int(opts.get("count", 50) or 50), len(pool))
        if n:
            grp = random.sample(pool, n)
            out.append(_write(opts.get("name") or f"Zufallsmix {time.strftime('%Y-%m-%d')}", grp, folder))
    else:
        raise RuntimeError("Unbekannte Playlist-Art.")
    out = [o for o in out if o]
    if not out:
        raise RuntimeError("Keine passenden Titel gefunden (Mindestanzahl pro Playlist beachten).")
    return out


def list_playlists():
    folder = paths.playlist_dir()
    res = []
    for root in {folder, paths.settings()["output_dir"]}:
        for d, _, names in os.walk(root):
            for n in names:
                if n.lower().endswith((".m3u8", ".m3u")):
                    p = os.path.join(d, n)
                    res.append({"path": p, "name": os.path.splitext(n)[0], "count": len(read_playlist(p)),
                                "mtime": os.path.getmtime(p), "auto": d == folder})
    uniq = {r["path"]: r for r in res}
    return sorted(uniq.values(), key=lambda r: -r["mtime"])


def read_playlist(path):
    base = os.path.dirname(path)
    out = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                p = line if os.path.isabs(line) else os.path.normpath(os.path.join(base, line))
                if os.path.isfile(p):
                    out.append(p)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- Ordnerstruktur nachträglich anwenden

def _full_tags(path):
    t = {}
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        tags = (f.tags if f is not None else None) or {}
        t = {"artist": _first(tags, "artist"), "album_artist": _first(tags, "albumartist"),
             "album": _first(tags, "album"), "title": _first(tags, "title"), "genre": _first(tags, "genre"),
             "date": _first(tags, "date", "year")[:4], "track": _first(tags, "tracknumber")}
    except Exception:
        pass
    if not t.get("title"):
        base = read_tags(path)
        t.update({k: t.get(k) or base.get(k, "") for k in ("title", "artist")})
    return t


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def reorganize_plan():
    s = paths.settings()
    root = s["output_dir"]
    moves = []
    for d, dirs, names in os.walk(root):
        rel = os.path.relpath(d, root)
        if rel.split(os.sep)[0] in ("Playlists",) or os.path.basename(d).startswith("_"):
            continue
        for n in names:
            if os.path.splitext(n)[1].lower() not in AUDIO_EXT:
                continue
            src = os.path.join(d, n)
            tags = _full_tags(src)
            tmpl = s["name_album"] if tags.get("album") and tags.get("track") else s["name_single"]
            dst = paths.build_path(root, tmpl, tags, os.path.splitext(n)[1][1:].lower(), make_unique=False)
            if not _same(src, dst):
                moves.append((src, dst))
    return moves


def reorganize(apply=False):
    moves = reorganize_plan()
    root = paths.settings()["output_dir"]
    preview = [{"from": os.path.relpath(a, root), "to": os.path.relpath(b, root)} for a, b in moves[:6]]
    if not apply:
        return {"count": len(moves), "preview": preview}
    done, errors, mapping = 0, [], {}
    for src, dst in moves:
        try:
            if os.path.exists(dst):
                dst = paths.unique(dst)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
            mapping[os.path.normcase(os.path.abspath(src))] = dst
            done += 1
        except OSError as e:
            errors.append(f"{os.path.basename(src)}: {e.strerror or e}")
    # Playlists auf die neuen Pfade umschreiben
    for d, _, names in os.walk(root):
        for n in names:
            if not n.lower().endswith((".m3u8", ".m3u")):
                continue
            p = os.path.join(d, n)
            try:
                with open(p, encoding="utf-8-sig", errors="replace") as f:
                    lines = f.read().splitlines()
                changed, out = False, []
                for line in lines:
                    s_ = line.strip()
                    if s_ and not s_.startswith("#"):
                        old = s_ if os.path.isabs(s_) else os.path.normpath(os.path.join(d, s_))
                        new = mapping.get(os.path.normcase(os.path.abspath(old)))
                        if new:
                            try:
                                line = os.path.relpath(new, d)
                            except ValueError:
                                line = new
                            changed = True
                    out.append(line)
                if changed:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write("\n".join(out) + "\n")
            except OSError:
                pass
    # leere Ordner aufräumen (nie den Zielordner selbst)
    for d, dirs, files_ in sorted(os.walk(root), key=lambda x: -len(x[0])):
        if d != root and not os.listdir(d) and not os.path.basename(d).startswith("_"):
            try:
                os.rmdir(d)
            except OSError:
                pass
    return {"count": done, "errors": errors[:10], "preview": preview}



# ---------------------------------------------------------------- Tags ändern + passend einsortieren

def apply_tags(path, fields=None, cover_data=None, remove_cover=False, lyrics=None, rename=True):
    """Schreibt Tags und verschiebt die Datei gemäß Ordnerstruktur. → neuer Pfad"""
    from . import tags as T
    T.write(path, fields or {}, cover_data=cover_data, remove_cover=remove_cover, lyrics=lyrics)
    if not rename:
        return path
    s = paths.settings()
    root = s["output_dir"]
    try:
        inside = os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        inside = False
    if not inside:
        return path                                    # Dateien außerhalb des Zielordners nicht verschieben
    t = _full_tags(path)
    tmpl = s["name_album"] if t.get("album") and t.get("track") else s["name_single"]
    dst = paths.build_path(root, tmpl, t, os.path.splitext(path)[1][1:].lower(), make_unique=False)
    if _same(path, dst):
        return path
    dst = paths.unique(dst)
    os.replace(path, dst)
    for side in (".lrc",):
        old = os.path.splitext(path)[0] + side
        if os.path.exists(old):
            os.replace(old, os.path.splitext(dst)[0] + side)
    _cleanup_dirs(os.path.dirname(path), root)
    return dst


def _cleanup_dirs(d, root):
    d, root = os.path.abspath(d), os.path.abspath(root)
    while d.startswith(root) and d != root:
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)


# ---------------------------------------------------------------- Löschen (Papierkorb)

def _recycle(files):
    """Verschiebt Dateien in den Windows-Papierkorb. → True bei Erfolg."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, "\0".join(os.path.abspath(f) for f in files) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


def delete_files(files):
    """Löscht Audiodateien (+ .lrc daneben). Unter Windows in den Papierkorb. → (gelöscht, fehler)"""
    root = os.path.abspath(paths.settings()["output_dir"])
    todo = []
    for f in files:
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in AUDIO_EXT:
            todo.append(f)
            lrc = os.path.splitext(f)[0] + ".lrc"
            if os.path.exists(lrc):
                todo.append(lrc)
    done, errors = [], []
    if paths.IS_WIN and todo:
        try:
            if _recycle(todo):
                done = [f for f in todo if not os.path.exists(f)]
        except Exception:
            pass
    for f in todo:                                   # Rest (oder kein Windows): direkt löschen
        if f in done or not os.path.exists(f):
            if f not in done and not os.path.exists(f):
                done.append(f)
            continue
        try:
            os.remove(f)
            done.append(f)
        except OSError as e:
            errors.append(f"{os.path.basename(f)}: {e.strerror or e}")
    for f in done:
        _cleanup_dirs(os.path.dirname(f), root)
    return [f for f in done if not f.endswith(".lrc")], errors
