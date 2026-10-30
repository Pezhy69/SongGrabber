"""Online-Quellen im Player: YouTube & Co. (über yt-dlp), Internetradio, Podcasts, Bilder.

Alles läuft über den lokalen Medienserver (127.0.0.1). Dadurch dürfen Lichtshow und Equalizer
den Ton analysieren (CORS), und Quellen, die der Browser nicht kann (Radio mit ICY-Protokoll, HLS),
werden von ffmpeg live in MP3 umgewandelt.
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict

from . import links, paths

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
STREAM_FMT = "bestaudio[protocol^=http][acodec!=none]/bestaudio[acodec!=none]/best[protocol^=http]/best"


def _id(*parts):
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


class Remote:
    """Registriert Routen am Medienserver: r = Ton, img = Bild."""

    def __init__(self, server):
        self.srv = server
        self.items = {}              # id → {kind, url, headers}
        self.resolved = {}           # Seiten-URL → {url, headers, protocol, t, meta}
        self.now = {}                # id → aktueller Titel (Radio)
        self.meta = {}               # id → Titel + Zeitpunkt des Wechsels
        self.imgs = OrderedDict()    # id → (ctype, bytes)
        self.lock = threading.Lock()
        server.handlers["r"] = self._audio
        server.handlers["img"] = self._img

    # ---------------------------------------------------------------- URLs erzeugen
    def audio_url(self, kind, url, headers=None):
        """kind: page (yt-dlp löst auf) | direct (Datei im Netz) | live (Radio/HLS → ffmpeg)"""
        rid = _id(kind, url)
        with self.lock:
            self.items[rid] = {"kind": kind, "url": url, "headers": headers or {}}
        return self.srv.route("r", rid), rid

    def img_url(self, url):
        if not url or not url.startswith(("http://", "https://")):
            return url or ""
        rid = _id("img", url)
        with self.lock:
            self.items[rid] = {"kind": "img", "url": url, "headers": {}}
        return self.srv.route("img", rid)

    def now_playing(self, rid):
        return self.now.get(rid, "")

    def now_meta(self, rid):
        """→ {"text", "t": Zeitpunkt des Titelwechsels, "n": wievielter Titel seit Senderstart}"""
        return dict(self.meta.get(rid) or {})

    # ---------------------------------------------------------------- yt-dlp
    def resolve(self, page_url, force=False):
        c = self.resolved.get(page_url)
        if c and not force and time.time() - c["t"] < 3 * 3600:
            return c
        r = paths.run([links._ytdlp(), "-J", "--no-playlist", "--no-warnings", "-f", STREAM_FMT, page_url], timeout=90)
        if r.returncode != 0 or not r.stdout:
            msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError((msg[-1] if msg else "Link nicht abspielbar").replace("ERROR: ", ""))
        info = json.loads(r.stdout.decode("utf-8", "replace"))
        fmt = info if info.get("url") else (info.get("requested_formats") or [{}])[0]
        if not fmt.get("url"):
            raise RuntimeError("Keine abspielbare Tonspur gefunden.")
        c = {"url": fmt["url"], "headers": fmt.get("http_headers") or info.get("http_headers") or {},
             "protocol": fmt.get("protocol") or "", "t": time.time(), "live": bool(info.get("is_live")),
             "meta": {"title": info.get("title"), "uploader": info.get("uploader"), "duration": info.get("duration"),
                      "thumb": info.get("thumbnail")}}
        self.resolved[page_url] = c
        return c

    # ---------------------------------------------------------------- Ton ausliefern
    def _audio(self, h, rid):
        it = self.items.get(rid)
        if not it:
            h.send_error(404)
            return
        if it["kind"] == "page":
            try:
                c = self.resolve(it["url"])
            except Exception as e:
                paths.log.warning("Stream nicht abspielbar (%s): %s", it["url"], e)
                h.send_error(502, str(e)[:100])
                return
            if c["live"] or "m3u8" in c["protocol"] or "dash" in c["protocol"]:
                return self._transcode(h, rid, c["url"], c["headers"])
            ok = self._pass(h, c["url"], c["headers"])
            if ok is False:                                  # Adresse abgelaufen → neu auflösen
                c = self.resolve(it["url"], force=True)
                self._pass(h, c["url"], c["headers"], final=True)
            return
        if it["kind"] == "live":
            return self._transcode(h, rid, it["url"], it["headers"])
        self._pass(h, it["url"], it["headers"], final=True)

    def _pass(self, h, url, headers, final=False):
        """Reicht eine Datei aus dem Netz durch – mit Spulen (Range)."""
        hdr = {"User-Agent": UA}
        hdr.update(headers or {})
        if h.headers.get("Range"):
            hdr["Range"] = h.headers["Range"]
        try:
            resp = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=20)
        except urllib.error.HTTPError as e:
            if e.code in (403, 410) and not final:
                return False
            h.send_error(e.code)
            return True
        except Exception:
            h.send_error(502)
            return True
        with resp:
            h.send_response(resp.status)
            ctype = resp.headers.get("Content-Type", "audio/mpeg")
            if not ctype.startswith(("audio/", "video/")):
                ctype = "audio/mp4" if ".m4a" in url or "mp4" in ctype else "audio/mpeg"
            h.send_header("Content-Type", ctype)
            for k in ("Content-Length", "Content-Range"):
                if resp.headers.get(k):
                    h.send_header(k, resp.headers[k])
            h.send_header("Accept-Ranges", "bytes")
            h.send_header("Access-Control-Allow-Origin", "*")
            h.end_headers()
            if h.command == "HEAD":
                return True
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                h.wfile.write(chunk)
        return True

    def _set_title(self, rid, txt):
        txt = (txt or "").strip().strip("'\"").strip()
        if not txt:
            return
        old = self.meta.get(rid)
        if not old or old["text"] != txt:
            self.meta[rid] = {"text": txt, "t": time.time(), "n": (old["n"] + 1) if old else 1}
        self.now[rid] = txt

    def _transcode(self, h, rid, url, headers):
        """Radio/HLS: ffmpeg wandelt live in MP3 um. Bei Radio (ICY) liest SongGrabber den Datenstrom selbst
        und holt bei jedem Liedwechsel den neuen Titel heraus – ffmpeg meldet nur den allerersten."""
        h.send_response(200)
        h.send_header("Content-Type", "audio/mpeg")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Access-Control-Allow-Origin", "*")
        h.end_headers()
        if h.command == "HEAD":
            return
        conn = None
        if url.startswith(("http://", "https://")) and not re.search(r"\.(m3u8?|pls)(\?|$)", url, re.I):
            try:
                conn = _icy_open(url, headers)
            except Exception as e:
                paths.log.info("Radio direkt nicht lesbar (%s) – ffmpeg übernimmt", e)
            if conn and not _is_audio(conn[2].get("content-type", "")):
                conn[1].close(); conn[0].close(); conn = None
        if conn:
            return self._transcode_icy(h, rid, url, headers, conn)
        args = [paths.ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "info", "-user_agent", UA]
        extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items() if k.lower() != "user-agent")
        if extra:
            args += ["-headers", extra]
        if url.startswith("http"):
            args += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
        args += ["-i", url, "-vn", "-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "2", "-f", "mp3", "pipe:1"]
        proc = paths.popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def meta():
            for raw in proc.stderr:
                m = re.search(r"StreamTitle\s*:\s*(.*)$", raw.decode("utf-8", "replace"))
                if m:
                    self._set_title(rid, m.group(1))
        threading.Thread(target=meta, daemon=True).start()
        try:
            while True:
                chunk = proc.stdout.read(16 * 1024)
                if not chunk:
                    break
                h.wfile.write(chunk)
        finally:
            proc.kill()

    def _transcode_icy(self, h, rid, url, headers, conn):
        sock, f, hdr = conn
        fmt = AUDIO_FMT.get(hdr.get("content-type", "").split(";")[0].strip().lower())
        args = [paths.ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error"]
        if fmt:
            args += ["-f", fmt]
        args += ["-i", "pipe:0", "-vn", "-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "2", "-f", "mp3", "pipe:1"]
        proc = paths.popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        stop = threading.Event()
        state = {"sock": sock, "f": f, "hdr": hdr}

        def feed():
            tries = 0
            while not stop.is_set():
                f_, metaint = state["f"], int(state["hdr"].get("icy-metaint") or 0)
                try:
                    while not stop.is_set():
                        data = _read_exact(f_, metaint) if metaint else f_.read(16 * 1024)
                        if not data:
                            break
                        proc.stdin.write(data)
                        tries = 0
                        if metaint:
                            n = f_.read(1)
                            if not n:
                                break
                            if n[0]:
                                title = _icy_title(_read_exact(f_, n[0] * 16))
                                if title is not None:
                                    self._set_title(rid, title)
                except (OSError, ValueError):
                    pass
                for o in (state["f"], state["sock"]):
                    try:
                        o.close()
                    except Exception:
                        pass
                if stop.is_set() or tries >= 5 or state["hdr"].get("content-length"):   # Datei zu Ende / Verbindung weg → bis zu 5× neu verbinden
                    break
                tries += 1
                time.sleep(min(5, tries))
                try:
                    c = _icy_open(url, headers)
                    if c:
                        state.update(sock=c[0], f=c[1], hdr=c[2])
                except Exception:
                    pass
            try:
                proc.stdin.close()
            except Exception:
                pass
        threading.Thread(target=feed, daemon=True).start()
        try:
            while True:
                chunk = proc.stdout.read(16 * 1024)
                if not chunk:
                    break
                h.wfile.write(chunk)
        finally:
            stop.set()
            proc.kill()
            for o in (state["f"], state["sock"]):
                try:
                    o.close()
                except Exception:
                    pass

    # ---------------------------------------------------------------- Bilder
    def _img(self, h, rid):
        it = self.items.get(rid)
        if not it:
            h.send_error(404)
            return
        c = self.imgs.get(rid)
        if not c:
            try:
                req = urllib.request.Request(it["url"], headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=12) as r:
                    data = r.read(4 * 1024 * 1024)
                    ctype = r.headers.get("Content-Type", "image/jpeg")
            except Exception:
                h.send_error(404)
                return
            c = (ctype, data)
            self.imgs[rid] = c
            while len(self.imgs) > 300:
                self.imgs.popitem(last=False)
        h.send_response(200)
        h.send_header("Content-Type", c[0])
        h.send_header("Content-Length", str(len(c[1])))
        h.send_header("Cache-Control", "max-age=86400")
        h.send_header("Access-Control-Allow-Origin", "*")
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(c[1])


# ---------------------------------------------------------------- Online-Suche (YouTube)

def search(query, limit=20):
    r = paths.run([links._ytdlp(), "-J", "--flat-playlist", "--no-warnings", f"ytsearch{int(limit)}:{query}"], timeout=60)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("Suche fehlgeschlagen – Internetverbindung und yt-dlp prüfen.")
    out = []
    for e in json.loads(r.stdout.decode("utf-8", "replace")).get("entries") or []:
        if not e or not e.get("id"):
            continue
        artist, title = links.guess_artist_title({"title": e.get("title"), "uploader": e.get("channel") or e.get("uploader")})
        out.append({"url": f"https://www.youtube.com/watch?v={e['id']}", "title": e.get("title") or "",
                    "artist": artist, "track": title, "uploader": e.get("channel") or e.get("uploader") or "",
                    "duration": e.get("duration") or 0, "thumb": f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
                    "live": bool(links.live_reason({}, e.get("title") or "", title))})
    return out


# ---------------------------------------------------------------- Radio (ICY) direkt lesen
AUDIO_FMT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mpeg3": "mp3", "audio/aac": "aac", "audio/aacp": "aac",
             "audio/x-aac": "aac", "audio/aac-adts": "aac", "application/ogg": "ogg", "audio/ogg": "ogg",
             "audio/flac": "flac", "audio/x-flac": "flac", "audio/opus": "ogg"}


def _is_audio(ct):
    ct = (ct or "").split(";")[0].strip().lower()
    return ct.startswith("audio/") and "mpegurl" not in ct and "scpls" not in ct or ct in ("application/ogg", "application/octet-stream")


def _icy_open(url, headers=None, redirects=6):
    """Rohe HTTP-Verbindung mit „Icy-MetaData: 1“. Versteht auch alte Shoutcast-Server („ICY 200 OK“).
    → (socket, datei, kopfzeilen) oder None"""
    import socket
    import ssl
    import urllib.parse
    for _ in range(redirects):
        u = urllib.parse.urlsplit(url)
        host = u.hostname
        port = u.port or (443 if u.scheme == "https" else 80)
        s = socket.create_connection((host, port), timeout=15)
        if u.scheme == "https":
            s = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        hdr = {"Host": u.netloc.split("@")[-1], "User-Agent": UA, "Accept": "*/*", "Icy-MetaData": "1", "Connection": "close"}
        hdr.update({k: v for k, v in (headers or {}).items() if k.lower() not in ("host", "connection")})
        s.sendall((f"GET {path} HTTP/1.0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hdr.items()) + "\r\n").encode("latin-1", "replace"))
        f = s.makefile("rb")
        status = f.readline(4096).decode("latin-1", "replace").split()
        head = {}
        while True:
            line = f.readline(8192)
            if not line or line in (b"\r\n", b"\n"):
                break
            k, _, v = line.decode("latin-1", "replace").partition(":")
            head[k.strip().lower()] = v.strip()
        code = int(status[1]) if len(status) > 1 and status[1].isdigit() else 0
        if code in (301, 302, 303, 307, 308) and head.get("location"):
            f.close()
            s.close()
            url = urllib.parse.urljoin(url, head["location"])
            continue
        if code != 200 or "chunked" in head.get("transfer-encoding", "").lower():
            f.close()
            s.close()
            return None
        s.settimeout(30)
        return s, f, head
    return None


def _read_exact(f, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return bytes(buf) if buf else b""
        buf += chunk
    return bytes(buf)


def _icy_title(block):
    raw = block.rstrip(b"\0")
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("cp1252", "replace")
    m = re.search(r"StreamTitle='(.*?)';", txt, re.S) or re.search(r"StreamTitle='(.*)'", txt, re.S)
    return m.group(1) if m else None
