"""Musikdaten online ergänzen: Album, Genre, Jahr, Titelnummer und Albumcover.

1. iTunes-Suche (schnell, ohne Schlüssel, liefert Genre + großes Cover)
2. MusicBrainz als Ersatz (Album, Jahr, Genre-Tags)
"""
import json
import re
import unicodedata
import urllib.parse
import urllib.request

from . import musicbrainz, paths

COMPILATION = re.compile(r"\b(greatest hits|best of|the best|hits|collection|essential|anthology|"
                         r"bravo|now that|now!|kuschelrock|top \d+|charts|ultimate|mix|karaoke|"
                         r"compilation|sampler|20 jahre|gold)\b", re.IGNORECASE)
LIVE = re.compile(r"\b(live|remix|acoustic|instrumental|karaoke|cover)\b", re.IGNORECASE)
_cache = {}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((feat|ft|with|prod)[^)]*\)|\[(feat|ft)[^\]]*\]|\b(feat|ft)\.? .*$", "", s)
    s = re.sub(r"[\(\[]([^)\]]*(remaster|version|edit|mono|stereo|deluxe)[^)\]]*)[\)\]]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    wa, wb = set(a.split()), set(b.split())
    return len(wa & wb) / max(len(wa | wb), 1)


def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": musicbrainz.UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def pick_itunes(results, artist, title):
    """Wählt aus iTunes-Treffern bevorzugt das Original-Studioalbum."""
    best, best_score = None, 0.0
    want_live = bool(LIVE.search(title))
    for r in results:
        if r.get("wrapperType") != "track" or r.get("kind") not in (None, "song"):
            continue
        sa = _similar(artist, r.get("artistName"))
        st = _similar(title, r.get("trackName"))
        if sa < 0.5 or st < 0.6:
            continue
        score = sa * 2 + st * 2
        coll = r.get("collectionName", "")
        if COMPILATION.search(coll) or (r.get("collectionArtistName") or "").lower() in ("various artists",
                                                                                         "verschiedene interpreten"):
            score -= 1.5
        if not want_live and (LIVE.search(r.get("trackName", "")) or LIVE.search(coll)):
            score -= 1.0
        if coll.endswith(" - Single"):
            score -= 0.4
        elif coll.endswith(" - EP"):
            score -= 0.2
        if (r.get("trackCount") or 0) >= 6:
            score += 0.3
        year = (r.get("releaseDate") or "9999")[:4]
        score -= (int(year) - 1950) / 2000 if year.isdigit() else 0     # bei Gleichstand: frühere Ausgabe
        if score > best_score:
            best, best_score = r, score
    if not best:
        return None
    art = best.get("artworkUrl100") or best.get("artworkUrl60") or ""
    return {"album": re.sub(r" - (Single|EP)$", "", best.get("collectionName", "")),
            "album_artist": best.get("collectionArtistName") or best.get("artistName", ""),
            "artist": best.get("artistName", ""), "title": best.get("trackName", ""),
            "genre": best.get("primaryGenreName", ""), "date": (best.get("releaseDate") or "")[:4],
            "track": f"{best['trackNumber']}/{best['trackCount']}" if best.get("trackNumber") and best.get("trackCount") else "",
            "disc": f"{best['discNumber']}/{best['discCount']}" if (best.get("discCount") or 1) > 1 else "",
            "cover_url": re.sub(r"\d+x\d+bb", "1000x1000bb", art) if art else "", "source": "iTunes",
            "duration": round((best.get("trackTimeMillis") or 0) / 1000)}


def itunes(artist, title, country="DE"):
    q = urllib.parse.urlencode({"term": f"{artist} {title}", "entity": "song", "limit": 25,
                                "country": country, "media": "music"})
    data = _get_json(f"https://itunes.apple.com/search?{q}")
    return pick_itunes(data.get("results", []), artist, title)


def pick_musicbrainz(recordings, artist, title):
    best, best_score = None, 0.0
    for rec in recordings:
        ra = "".join(a.get("name", "") + a.get("joinphrase", "") for a in rec.get("artist-credit", []))
        sa, st = _similar(artist, ra), _similar(title, rec.get("title"))
        if sa < 0.5 or st < 0.6:
            continue
        for rel in rec.get("releases", []):
            rg = rel.get("release-group", {}) or {}
            score = sa * 2 + st * 2 + rec.get("score", 0) / 100
            if rg.get("primary-type") == "Album":
                score += 0.6
            elif rg.get("primary-type") == "Single":
                score += 0.1
            if rg.get("secondary-types"):
                score -= 1.2            # Compilation, Live, Soundtrack, Remix …
            if rel.get("status") not in (None, "Official"):
                score -= 0.8
            date = rel.get("date") or "9999"
            score -= (int(date[:4]) - 1950) / 2000 if date[:4].isdigit() else 0.2
            if score > best_score:
                tags = sorted(rec.get("tags", []), key=lambda t: -t.get("count", 0))
                media = (rel.get("media") or [{}])[0]
                tr = (media.get("track") or [{}])[0]
                best_score = score
                best = {"album": rel.get("title", ""), "artist": ra, "title": rec.get("title", ""),
                        "album_artist": ra, "genre": tags[0]["name"].title() if tags else "",
                        "date": (rel.get("date") or "")[:4],
                        "track": f"{tr.get('number')}/{media.get('track-count')}" if tr.get("number") and media.get("track-count") else "",
                        "disc": "", "source": "MusicBrainz",
                        "cover_url": f"https://coverartarchive.org/release-group/{rg['id']}/front-500" if rg.get("id") else ""}
    return best


def mb(artist, title):
    q = f'recording:"{title}" AND artist:"{artist}"'
    data = json.loads(musicbrainz._get("https://musicbrainz.org/ws/2/recording?" +
                                       urllib.parse.urlencode({"query": q, "limit": 15, "fmt": "json"})))
    return pick_musicbrainz(data.get("recordings", []), artist, title)


def lookup(artist, title):
    """Liefert dict mit album, genre, date, track, cover_url … oder None. Fehler werden geschluckt."""
    if not artist or not title or not paths.settings().get("metadata_online", True):
        return None
    key = (norm(artist), norm(title))
    if key in _cache:
        return _cache[key]
    res = None
    for fn in (itunes, mb):
        try:
            res = fn(artist, title)
        except Exception:
            res = None
        if res and res.get("album"):
            break
    if res and not res.get("genre"):
        try:
            g = mb(artist, title) if res.get("source") != "MusicBrainz" else None
            if g and g.get("genre"):
                res["genre"] = g["genre"]
        except Exception:
            pass
    _cache[key] = res
    return res


def album_lookup(artist, album):
    """Album (nicht Titel) suchen – für Full-Album-Videos. → album, album_artist, genre, date, cover_url, tracks"""
    if not artist or not album or not paths.settings().get("metadata_online", True):
        return None
    try:
        q = urllib.parse.urlencode({"term": f"{artist} {album}", "entity": "album", "limit": 15, "country": "DE"})
        res = _get_json(f"https://itunes.apple.com/search?{q}").get("results", [])
    except Exception:
        return None
    best, best_score = None, 0.0
    for r in res:
        sa, sb = _similar(artist, r.get("artistName")), _similar(album, re.sub(r" - (Single|EP)$", "", r.get("collectionName", "")))
        if sa < 0.5 or sb < 0.6:
            continue
        sc = sa + sb * 2 - (0.5 if re.search(r"deluxe|remaster|edition|live", r.get("collectionName", ""), re.I) else 0)
        if sc > best_score:
            best, best_score = r, sc
    if not best:
        return None
    art = best.get("artworkUrl100") or ""
    return {"album": re.sub(r" - (Single|EP)$", "", best.get("collectionName", "")), "album_artist": best.get("artistName", ""),
            "genre": best.get("primaryGenreName", ""), "date": (best.get("releaseDate") or "")[:4],
            "tracks": best.get("trackCount") or 0,
            "cover_url": re.sub(r"\d+x\d+bb", "1000x1000bb", art) if art else "", "source": "iTunes"}
