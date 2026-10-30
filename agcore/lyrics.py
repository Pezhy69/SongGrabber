"""Songtexte von LRCLIB (lrclib.net – frei, ohne Konto). Bevorzugt synchronisierte Texte (LRC)."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import metadata, musicbrainz, paths, tags

API = "https://lrclib.net/api"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": musicbrainz.UA})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch(artist, title, album="", duration=0):
    """→ {"synced": str, "plain": str, "instrumental": bool} oder None."""
    if not artist or not title:
        return None
    q = {"artist_name": artist, "track_name": title}
    if album:
        q["album_name"] = album
    if duration:
        q["duration"] = int(round(duration))
    try:
        d = _get(f"{API}/get?" + urllib.parse.urlencode(q))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return None
        d = None
    except Exception:
        return None
    if not d:      # unscharfe Suche, Dauer ±5 s
        try:
            res = _get(f"{API}/search?" + urllib.parse.urlencode({"artist_name": artist, "track_name": title}))
        except Exception:
            return None
        best = None
        for r in res or []:
            if metadata._similar(artist, r.get("artistName")) < 0.6 or metadata._similar(title, r.get("trackName")) < 0.7:
                continue
            if duration and r.get("duration") and abs(r["duration"] - duration) > 5:
                continue
            if best is None or (r.get("syncedLyrics") and not best.get("syncedLyrics")):
                best = r
        d = best
    if not d:
        return None
    return {"synced": d.get("syncedLyrics") or "", "plain": d.get("plainLyrics") or "",
            "instrumental": bool(d.get("instrumental"))}


_SUFFIX = re.compile(r"\s*[-–—]\s*(\d{4}\s*)?(remaster(ed)?|remix|radio edit|single version|mono|stereo|bonus track)\b.*$", re.I)
_PAREN = re.compile(r"\s*[\(\[][^\)\]]*(official|video|audio|lyric|visuali[sz]er|hd|hq|4k|remaster|explicit|clean|m/v|mv|feat\.?|ft\.|edit|version)[^\)\]]*[\)\]]", re.I)
_FEAT = re.compile(r"\s*[\(\[]?\s*(feat\.?|ft\.?|featuring|with)\s+[^\)\]]*[\)\]]?\s*$", re.I)


def _clean_artist(a):
    a = re.sub(r"\s*(VEVO|- Topic|Official|Offiziell)\s*$", "", a or "", flags=re.I).strip()
    return a


def candidates(artist, title):
    """Aus YouTube-/Spotify-/Radio-Titeln brauchbare (Interpret, Titel)-Paare machen."""
    artist, title = _clean_artist(artist), (title or "").strip()
    out = []
    if not artist:
        return split_text(title)[:4]

    def add(a, t):
        t = _FEAT.sub("", _SUFFIX.sub("", _PAREN.sub("", t or ""))).strip(" -–—\"'")
        a = _clean_artist(a)
        if a and t and (a.lower(), t.lower()) not in [(x.lower(), y.lower()) for x, y in out]:
            out.append((a, t))
    for sep in (" - ", " – ", " — ", " | "):
        if sep in title:
            left, right = title.split(sep, 1)
            if not artist or metadata._similar(artist, left) >= 0.5 or artist.lower() in left.lower():
                add(left, right)
            break
    add(artist, title)
    for a, t in list(out):
        first = re.split(r"\s*(,|&| x | und | and | feat\.?| ft\.?)\s*", a, flags=re.I)[0]
        add(first, t)
        add(a, re.sub(r"\s*[\(\[].*?[\)\]]", "", t))
    return out[:4]


_Q = "\"'„“”‚‘’«»`´"
_PREFIX = re.compile(r"^\s*(jetzt|gerade|aktuell|now|on air|you are listening to|sie hören|ihr hört|du hörst)\b[^:–\-]*[:–\-]\s*", re.I)
_NOT_MUSIC = re.compile(r"\b(nachrichten|news|werbung|verkehr|wetter|traffic|weather|commercial|jingle|moderation|interview|podcast|sendung|live ?stream)\b", re.I)


def _unq(s):
    return re.sub(r"\s+", " ", (s or "").strip().strip(_Q).replace("\u00a0", " ")).strip(" -–—:|/").strip().strip(_Q).strip()


def split_text(text, station=""):
    """Radio-/Stream-Titel in mögliche (Interpret, Titel)-Paare zerlegen – beste Vermutung zuerst.
    Versteht z. B. „Interpret - Titel“, „Titel - Interpret“, „"Titel" von Interpret“, „Titel by Interpret“,
    „Interpret mit "Titel"“, „Interpret: Titel“, „Interpret / Titel“."""
    t = (text or "").strip()
    if station:
        t = re.sub(re.escape(station), " ", t, flags=re.I)
    t = _PREFIX.sub("", t).strip(" -–—:|")
    if not t or _NOT_MUSIC.search(t) and not re.search(r"\s[-–—]\s", t):
        return []
    pairs = []

    def add(a, ti):
        a, ti = _unq(a), _unq(ti)
        if a and ti and len(a) < 80 and len(ti) < 120 and (a, ti) not in pairs:
            pairs.append((a, ti))
    m = re.match(rf"^[{_Q}]?(.+?)[{_Q}]?\s+(?:von|by|vom|from|performed by|interpretiert von)\s+(.+)$", t, re.I)
    if m:
        add(m.group(2), m.group(1))
    m = re.match(rf"^(.+?)\s+(?:mit|with)\s+[{_Q}](.+?)[{_Q}]?$", t, re.I)
    if m:
        add(m.group(1), m.group(2))
    m = re.match(rf"^(.+?)\s*[{_Q}](.+?)[{_Q}]\s*$", t)             # Interpret "Titel"
    if m:
        add(m.group(1), m.group(2))
    for sep in (" - ", " – ", " — ", " | ", " / ", " ~ ", ": ", " * "):
        if sep in t:
            a, b = t.split(sep, 1)
            add(a, b)
            add(b, a)
            break
    return pairs


def _words(s):
    s = re.sub(r"[’'´`]", "", _PAREN.sub("", s or ""))
    return set(re.findall(r"\w{2,}", metadata.norm(s)))


def search_free(text, duration=0):
    """Freitext-Suche bei lrclib.net – wenn Interpret/Titel nicht sicher getrennt sind."""
    q = re.sub(rf"[{_Q}]|\b(von|by|mit|with|feat\.?|ft\.?)\b", " ", text or "", flags=re.I)
    q = re.sub(r"\s+", " ", _PAREN.sub("", q)).strip(" -–—:|/")
    if len(q) < 4:
        return None
    try:
        res = _get(f"{API}/search?" + urllib.parse.urlencode({"q": q}))
    except Exception:
        return None
    qw, best, best_s = _words(q), None, 0.0
    for r in res or []:
        tw, aw = _words(r.get("trackName")), _words(r.get("artistName"))
        if not tw or not aw:
            continue
        ft, fa = len(tw & qw) / len(tw), len(aw & qw) / len(aw)
        cover = len((tw | aw) & qw) / len(qw)     # wie viel vom Sendertext ist erklärt?
        if ft < 0.75 or fa < (1.0 if len(aw) <= 3 else 0.6) or cover < 0.7:   # Titel UND Interpret müssen passen
            continue
        if duration and r.get("duration") and abs(r["duration"] - duration) > 8:
            continue
        s = ft + fa + (0.3 if r.get("syncedLyrics") else 0)
        if s > best_s:
            best, best_s = r, s
    if not best:
        return None
    return {"synced": best.get("syncedLyrics") or "", "plain": best.get("plainLyrics") or "",
            "instrumental": bool(best.get("instrumental")), "artist": best.get("artistName", ""), "title": best.get("trackName", "")}


def smart(artist, title, album="", duration=0, raw=""):
    """Songtext für Titel aus Browser, Spotify oder Radio – probiert mehrere Schreibweisen."""
    dur = duration if duration and duration < 1200 else 0
    tried = []
    pairs = candidates(artist, title) + [p for p in split_text(raw or title) if p not in candidates(artist, title)]
    for a, t in pairs[:6]:
        if (a.lower(), t.lower()) in tried:
            continue
        tried.append((a.lower(), t.lower()))
        r = fetch(a, t, "", dur)
        if r and (r["synced"] or r["plain"] or r["instrumental"]):
            r.update(artist=a, title=t)
            return r
    return search_free(raw or f"{artist} {title}", dur)


def apply(path, info=None):
    """Songtext suchen und einbetten (+ .lrc daneben, wenn eingestellt). True bei Erfolg."""
    s = paths.settings()
    t = info or tags.read(path)
    res = fetch(t.get("artist"), t.get("title"), t.get("album"), t.get("duration"))
    if not res or res["instrumental"] or not (res["synced"] or res["plain"]):
        return False
    text = res["synced"] or res["plain"]
    tags.write(path, lyrics=text)
    if s.get("lyrics_lrc") and res["synced"]:
        with open(os.path.splitext(path)[0] + ".lrc", "w", encoding="utf-8") as f:
            f.write(res["synced"])
    return True
