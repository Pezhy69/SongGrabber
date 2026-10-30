"""Lautstärke beim Abspielen angleichen: Lautheit je Titel messen (EBU R128) und merken.

Vorhandene ReplayGain-Angaben in den Tags werden genutzt; sonst misst ffmpeg einmal im Hintergrund.
Ergebnis je Datei: Verstärkung in dB, sodass alle Titel etwa gleich laut klingen (Ziel −16 LUFS),
ohne zu übersteuern (Spitze bleibt unter −1 dBTP).
"""
import json
import os
import queue
import re
import threading

from . import paths

TARGET = -16.0
_lock = threading.Lock()
_cache = None
_q = queue.Queue()
_pending = set()
_worker = None
_dirty = 0


def _file():
    return os.path.join(paths.data_dir(), "lautheit.json")


def _load():
    global _cache
    if _cache is None:
        try:
            with open(_file(), encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _save():
    global _dirty
    try:
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump(_cache, f)
        _dirty = 0
    except Exception:
        pass


def _key(p):
    st = os.stat(p)
    return f"{os.path.normcase(os.path.abspath(p))}|{int(st.st_mtime)}|{st.st_size}"


def _num(s):
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(s))
    return float(m.group().replace(",", ".")) if m else None


def from_tags(p):
    """ReplayGain aus den Tags (Bezug −18 LUFS) → Verstärkung für unser Ziel."""
    try:
        import mutagen
        f = mutagen.File(p)
        if f is None or not f.tags:
            return None
        tags = f.tags
        gain = peak = None
        for k in list(tags.keys()):
            kl = str(k).lower()
            if "replaygain_track_gain" in kl:
                v = tags[k]
                v = getattr(v, "text", v)
                gain = _num(v[0] if isinstance(v, (list, tuple)) else v)
            elif "replaygain_track_peak" in kl:
                v = tags[k]
                v = getattr(v, "text", v)
                peak = _num(v[0] if isinstance(v, (list, tuple)) else v)
        if gain is None:
            return None
        g = gain + (TARGET + 18.0)
        if peak and peak > 0:
            import math
            g = min(g, -1.0 - 20 * math.log10(peak))
        return max(-15.0, min(10.0, g))
    except Exception:
        return None


def measure(p):
    ff = paths.ffmpeg()
    if not ff:
        return None
    r = paths.run([ff, "-hide_banner", "-nostdin", "-i", p, "-vn", "-sn", "-dn",
                   "-af", "ebur128=peak=true", "-f", "null", "-"], timeout=300)
    txt = r.stderr.decode("utf-8", "replace")
    tail = txt[txt.rfind("Summary:"):] if "Summary:" in txt else txt
    mi = re.search(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", tail)
    if not mi:
        return None
    lufs = float(mi.group(1))
    if lufs <= -70:                                   # Stille
        return 0.0
    g = TARGET - lufs
    mp = re.search(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", tail)
    if mp:
        g = min(g, -1.0 - float(mp.group(1)))
    return round(max(-15.0, min(10.0, g)), 2)


def _run():
    global _dirty
    while True:
        p = _q.get()
        try:
            g = from_tags(p)
            if g is None:
                g = measure(p)
            with _lock:
                if g is not None:
                    _load()[_key(p)] = g
                    _dirty += 1
                _pending.discard(p)
                if _dirty and (_q.empty() or _dirty >= 20):
                    _save()
        except Exception as e:
            paths.log.warning("Lautheit nicht messbar (%s): %s", os.path.basename(p), e)
            with _lock:
                _pending.discard(p)


def get(items):
    """→ {pfad: verstärkung_dB oder None (wird gerade gemessen)}"""
    global _worker
    out = {}
    with _lock:
        cache = _load()
        for p in items or []:
            if not p or not os.path.isfile(p):
                continue
            try:
                k = _key(p)
            except OSError:
                continue
            if k in cache:
                out[p] = cache[k]
                continue
            out[p] = None
            if p not in _pending:
                _pending.add(p)
                _q.put(p)
        if _pending and (_worker is None or not _worker.is_alive()):
            _worker = threading.Thread(target=_run, daemon=True)
            _worker.start()
    return out
