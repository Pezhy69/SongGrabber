"""Musikerkennung per Audio-Fingerabdruck (Chromaprint + AcoustID).

Fingerabdruck: fpcalc.exe (bin-Ordner) oder – falls vorhanden – ffmpeg mit Chromaprint.
Für die Abfrage braucht AcoustID einen kostenlosen Anwendungsschlüssel (acoustid.org/new-application).
"""
import json
import os
import re
import urllib.parse
import urllib.request

from . import metadata, musicbrainz, paths

API = "https://api.acoustid.org/v2/lookup"


def available():
    return bool(paths.find_bin("fpcalc") or _ffmpeg_chromaprint())


_ffcp = None


def _ffmpeg_chromaprint():
    global _ffcp
    if _ffcp is None:
        try:
            r = paths.run([paths.ffmpeg(), "-hide_banner", "-muxers"], timeout=20)
            _ffcp = b"chromaprint" in r.stdout
        except Exception:
            _ffcp = False
    return _ffcp


def fingerprint(path, start=None, length=120):
    """→ (dauer_sekunden, fingerprint_base64)"""
    fp = paths.find_bin("fpcalc")
    if fp and start is None:
        r = paths.run([fp, "-json", "-length", str(length), path], timeout=120)
        if r.returncode == 0:
            d = json.loads(r.stdout.decode("utf-8", "replace"))
            return int(d["duration"]), d["fingerprint"]
    if not _ffmpeg_chromaprint():
        raise RuntimeError("Für die Erkennung fehlt fpcalc.exe im bin-Ordner (build.bat lädt es automatisch).")
    from . import encoder
    dur = encoder.probe(path)["duration"]
    args = [paths.ffmpeg(), "-hide_banner", "-nostdin", "-v", "error"]
    if start:
        args += ["-ss", f"{start:.2f}"]
    args += ["-i", path, "-t", str(length), "-vn", "-ac", "2", "-f", "chromaprint", "-fp_format", "base64", "-"]
    r = paths.run(args, timeout=120)
    out = r.stdout.decode("ascii", "replace").strip()
    if r.returncode != 0 or not out:
        raise RuntimeError("Fingerabdruck konnte nicht berechnet werden.")
    return int(round(dur)), out


def lookup(duration, fp, key):
    data = urllib.parse.urlencode({"client": key, "meta": "recordings releasegroups compress",
                                   "duration": duration, "fingerprint": fp, "format": "json"}).encode()
    req = urllib.request.Request(API, data=data, headers={"User-Agent": musicbrainz.UA,
                                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if d.get("status") != "ok":
        msg = (d.get("error") or {}).get("message", "unbekannter Fehler")
        if "invalid API key" in msg or "client" in msg.lower():
            raise RuntimeError("AcoustID-Schlüssel ungültig – bitte in den Einstellungen prüfen.")
        raise RuntimeError("AcoustID: " + msg)
    return pick(d.get("results") or [])


def pick(results):
    """Bestes Ergebnis: höchste Übereinstimmung, bevorzugt Original-Album statt Sampler/Live."""
    best, best_score = None, 0.0
    for res in results:
        sc = float(res.get("score") or 0)
        if sc < 0.5:
            continue
        for rec in res.get("recordings") or []:
            if not rec.get("title") or not rec.get("artists"):
                continue
            artist = "".join(a.get("name", "") + a.get("joinphrase", "") for a in rec["artists"]).strip()
            for rg in rec.get("releasegroups") or [{}]:
                s = sc * 3
                if rg.get("type") == "Album":
                    s += 0.6
                if rg.get("secondarytypes"):
                    s -= 1.0
                if s > best_score:
                    best_score = s
                    best = {"artist": artist, "title": rec["title"], "album": rg.get("title", ""),
                            "score": round(sc, 2), "mbid": rec.get("id", "")}
    return best


def identify(path, start=None):
    """Erkennt einen Titel. → dict mit artist/title/album/genre/date/track/cover_url/score oder None."""
    key = (paths.settings().get("acoustid_key") or "").strip()
    if not key:
        raise RuntimeError("Für die Erkennung wird ein kostenloser AcoustID-Schlüssel benötigt (Einstellungen).")
    dur, fp = fingerprint(path, start)
    hit = lookup(dur, fp, key)
    if not hit:
        return None
    meta = metadata.lookup(hit["artist"], hit["title"]) or {}
    out = dict(hit)
    for k in ("album", "genre", "date", "track", "cover_url", "album_artist"):
        if meta.get(k) and (k != "album" or not out.get("album") or re.search(r"live|hits|best of", out["album"], re.I)):
            out[k] = meta[k]
    return out
