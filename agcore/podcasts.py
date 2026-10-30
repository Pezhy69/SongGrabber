"""Podcasts: suchen (iTunes-Verzeichnis), abonnieren (RSS), Folgen abspielen, fortsetzen, herunterladen."""
import email.utils
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import metadata, musicbrainz, paths

NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd", "content": "http://purl.org/rss/1.0/modules/content/"}


def _file(name):
    return os.path.join(paths.data_dir(), name)


def _load(name, default):
    try:
        with open(_file(name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(name, data):
    with open(_file(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def search(query):
    q = urllib.parse.urlencode({"term": query, "media": "podcast", "entity": "podcast", "limit": 30, "country": "DE"})
    res = metadata._get_json(f"https://itunes.apple.com/search?{q}", timeout=12).get("results", [])
    return [{"feed": r.get("feedUrl"), "title": r.get("collectionName", ""), "author": r.get("artistName", ""),
             "image": r.get("artworkUrl600") or r.get("artworkUrl100", ""), "genre": r.get("primaryGenreName", ""),
             "count": r.get("trackCount", 0)} for r in res if r.get("feedUrl")]


def _dur(v):
    v = (v or "").strip()
    if not v:
        return 0
    if v.isdigit():
        return int(v)
    parts = [int(p) for p in v.split(":") if p.isdigit()]
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def _text(s, n=400):
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def fetch(feed_url):
    req = urllib.request.Request(feed_url, headers={"User-Agent": musicbrainz.UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(20 * 1024 * 1024)
    root = ET.fromstring(raw)
    ch = root.find("channel")
    if ch is None:
        raise RuntimeError("Das ist kein Podcast-Feed.")
    img = ch.find("itunes:image", NS)
    image = img.get("href") if img is not None else (ch.findtext("image/url") or "")
    show = {"feed": feed_url, "title": _text(ch.findtext("title"), 200), "author": _text(ch.findtext("itunes:author", namespaces=NS) or ch.findtext("managingEditor") or "", 200),
            "image": image, "description": _text(ch.findtext("description") or ch.findtext("itunes:summary", namespaces=NS), 600)}
    eps = []
    for it in ch.findall("item"):
        enc = it.find("enclosure")
        if enc is None or not enc.get("url"):
            continue
        try:
            ts = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except Exception:
            ts = 0
        ei = it.find("itunes:image", NS)
        guid = it.findtext("guid") or enc.get("url")
        eps.append({"guid": hashlib.sha1(guid.encode("utf-8")).hexdigest()[:16], "title": _text(it.findtext("title"), 300),
                    "url": enc.get("url"), "type": enc.get("type") or "", "date": ts,
                    "duration": _dur(it.findtext("itunes:duration", namespaces=NS)),
                    "image": ei.get("href") if ei is not None else "", "description": _text(it.findtext("description") or it.findtext("itunes:summary", namespaces=NS))})
    eps.sort(key=lambda e: -e["date"])
    show["episodes"] = eps[:300]
    show["checked"] = time.time()
    _save(f"podcast_{hashlib.sha1(feed_url.encode()).hexdigest()[:12]}.json", show)
    return show


def cached(feed_url):
    return _load(f"podcast_{hashlib.sha1(feed_url.encode()).hexdigest()[:12]}.json", None)


def subscriptions():
    return _load("podcasts.json", [])


def subscribe(show):
    subs = [s for s in subscriptions() if s["feed"] != show["feed"]]
    subs.insert(0, {k: show.get(k) for k in ("feed", "title", "author", "image")})
    _save("podcasts.json", subs)
    return True


def unsubscribe(feed):
    _save("podcasts.json", [s for s in subscriptions() if s["feed"] != feed])
    return True


def progress():
    return _load("podcast_fortschritt.json", {})


def set_progress(guid, pos, dur):
    p = progress()
    p[guid] = {"pos": round(float(pos), 1), "dur": round(float(dur or 0), 1), "done": bool(dur and pos >= dur - 30), "t": time.time()}
    _save("podcast_fortschritt.json", p)
    return True


def download_job(show, ep):
    """Lädt eine Folge in <Zielordner>/Podcasts/<Sendung>/ und taggt sie."""
    def run(job):
        from . import tags
        folder = os.path.join(paths.settings()["output_dir"], "Podcasts", paths.clean(show.get("title") or "Podcast"))
        os.makedirs(folder, exist_ok=True)
        ext = os.path.splitext(urllib.parse.urlparse(ep["url"]).path)[1].lower()
        if ext not in (".mp3", ".m4a", ".aac", ".ogg", ".opus"):
            ext = ".m4a" if "mp4" in ep.get("type", "") or "m4a" in ep.get("type", "") else ".mp3"
        day = time.strftime("%Y-%m-%d", time.localtime(ep["date"])) if ep.get("date") else ""
        dst = paths.unique(os.path.join(folder, paths.clean(f"{day} - {ep['title']}" if day else ep["title"])[:150] + ext))
        req = urllib.request.Request(ep["url"], headers={"User-Agent": musicbrainz.UA})
        with urllib.request.urlopen(req, timeout=30) as r, open(dst + ".part", "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if job.cancel.is_set():
                    raise RuntimeError("Abgebrochen")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                job.set(done / total if total else None, f"Lädt … {done / 1048576:.1f} MB")
        os.replace(dst + ".part", dst)
        try:
            cover = None
            img = ep.get("image") or show.get("image")
            if img:
                p = musicbrainz.download_cover(img, os.path.join(paths.temp_dir(), "podcast.jpg"))
                if p:
                    with open(p, "rb") as f:
                        cover = f.read()
            tags.write(dst, {"title": ep["title"], "artist": show.get("author") or show.get("title"), "album": show.get("title"),
                             "album_artist": show.get("author") or show.get("title"), "date": day[:4], "genre": "Podcast"},
                       cover_data=cover)
        except Exception:
            pass
        job.outputs.append(dst)
        job.set(1.0, "Fertig")
    return run
