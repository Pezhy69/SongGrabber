"""Internetradio über das freie Senderverzeichnis radio-browser.info (über 30.000 Sender)."""
import json
import os
import random
import socket
import threading
import time
import urllib.parse
import urllib.request

from . import musicbrainz, paths

FALLBACK = ["de1.api.radio-browser.info", "de2.api.radio-browser.info", "fi1.api.radio-browser.info"]
_servers = []


def _hosts():
    global _servers
    if not _servers:
        try:
            ips = {a[4][0] for a in socket.getaddrinfo("all.api.radio-browser.info", 443, proto=socket.IPPROTO_TCP)}
            _servers = [socket.gethostbyaddr(ip)[0] for ip in ips]
        except Exception:
            _servers = []
        random.shuffle(_servers)
        _servers += [h for h in FALLBACK if h not in _servers]
    return _servers


def _get(path, params=None):
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    last = None
    for host in _hosts()[:4]:
        try:
            req = urllib.request.Request(f"https://{host}/json/{path}{q}", headers={"User-Agent": musicbrainz.UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
    raise RuntimeError("Senderverzeichnis nicht erreichbar – Internetverbindung prüfen.") from last


def _station(s):
    tags = [t.strip() for t in (s.get("tags") or "").split(",") if t.strip()][:4]
    return {"uuid": s.get("stationuuid"), "name": (s.get("name") or "").strip() or "Unbenannter Sender",
            "url": s.get("url_resolved") or s.get("url"), "favicon": s.get("favicon") or "", "tags": tags,
            "country": s.get("countrycode") or "", "codec": s.get("codec") or "", "bitrate": s.get("bitrate") or 0,
            "homepage": s.get("homepage") or "", "votes": s.get("votes") or 0}


def search(query="", tag="", country="", limit=80, offset=0):
    params = {"order": "clickcount", "reverse": "true", "hidebroken": "true", "limit": limit, "offset": offset}
    if query:
        params["name"] = query
    if tag:
        params["tag"] = tag
    if country:
        params["countrycode"] = country
    return [_station(s) for s in _get("stations/search", params) if s.get("url_resolved") or s.get("url")]


def tags(limit=40):
    return [t["name"] for t in _get("tags", {"order": "stationcount", "reverse": "true", "limit": 200, "hidebroken": "true"})
            if len(t.get("name", "")) > 1][:limit]


def click(uuid):
    """Zählt den Aufruf (gehört zur Fairness gegenüber dem Verzeichnis)."""
    if uuid:
        threading.Thread(target=lambda: _safe(lambda: _get(f"url/{uuid}")), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


# ---------------------------------------------------------------- Favoriten & Verlauf

def _file(name):
    return os.path.join(paths.data_dir(), name)


def _load(name):
    try:
        with open(_file(name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(name, data):
    with open(_file(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def favorites():
    return _load("radio_favoriten.json")


def toggle_favorite(st):
    favs = favorites()
    if any(f["uuid"] == st["uuid"] for f in favs):
        favs = [f for f in favs if f["uuid"] != st["uuid"]]
        on = False
    else:
        favs.insert(0, {k: st.get(k) for k in ("uuid", "name", "url", "favicon", "tags", "country", "codec", "bitrate", "homepage")})
        on = True
    _save("radio_favoriten.json", favs)
    return on


def recent():
    return _load("radio_verlauf.json")


def add_recent(st):
    r = [x for x in recent() if x["uuid"] != st["uuid"]]
    r.insert(0, dict({k: st.get(k) for k in ("uuid", "name", "url", "favicon", "tags", "country", "codec", "bitrate", "homepage")}, t=time.time()))
    _save("radio_verlauf.json", r[:20])
