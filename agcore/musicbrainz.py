"""Trackinformationen und Cover für Audio-CDs (MusicBrainz + Cover Art Archive)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import paths

UA = f"{paths.APP_NAME}/{paths.VERSION} ( redline-it.net )"
_last = [0.0]


def _get(url, timeout=20):
    wait = 1.1 - (time.time() - _last[0])        # MusicBrainz: max. 1 Anfrage/Sekunde
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _credit(ac):
    return "".join(a.get("name", "") + a.get("joinphrase", "") for a in ac or []).strip()


def lookup(discid, toc, n_tracks):
    q = urllib.parse.urlencode({"toc": toc, "inc": "artist-credits recordings labels release-groups",
                                "cdstubs": "no", "fmt": "json"})
    try:
        data = json.loads(_get(f"https://musicbrainz.org/ws/2/discid/{discid}?{q}"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise RuntimeError(f"MusicBrainz antwortet nicht ({e.code}).")
    except urllib.error.URLError:
        raise RuntimeError("Keine Internetverbindung – Titel bitte manuell eintragen.")
    out = []
    for rel in data.get("releases", []):
        media = rel.get("media", [])
        medium = next((m for m in media if any(d.get("id") == discid for d in m.get("discs", []))), None)
        if medium is None:
            medium = next((m for m in media if len(m.get("tracks", [])) == n_tracks), None)
        if medium is None:
            continue
        album_artist = _credit(rel.get("artist-credit"))
        tracks = [{"n": t.get("position"), "title": t.get("title") or t.get("recording", {}).get("title", ""),
                   "artist": _credit(t.get("artist-credit")) or album_artist} for t in medium.get("tracks", [])]
        labels = [li.get("label", {}).get("name") for li in rel.get("label-info", []) if li.get("label")]
        rg = rel.get("release-group", {}) or {}
        art = rel.get("cover-art-archive", {}) or {}
        cover = f"https://coverartarchive.org/release/{rel['id']}/front-500" if art.get("front", True) else ""
        out.append({"mbid": rel["id"], "album": rel.get("title", ""), "artist": album_artist,
                    "date": rel.get("date", ""), "country": rel.get("country", ""),
                    "label": ", ".join(x for x in labels if x), "tracks": tracks,
                    "disc": f"{medium.get('position', 1)}/{len(media)}" if len(media) > 1 else "",
                    "cover_url": cover, "rg_cover": f"https://coverartarchive.org/release-group/{rg['id']}/front-500"
                    if rg.get("id") else ""})
    return out


def download_cover(url, dst):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
            f.write(r.read())
        return dst
    except Exception:
        return None
