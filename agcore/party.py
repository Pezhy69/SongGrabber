"""Karaoke-Party: Gäste wünschen sich Songs vom Handy.

Ein kleiner Webserver im eigenen WLAN liefert die Handy-Seite (ui/party.html) und eine JSON-Schnittstelle.
Zugang nur mit dem Zufallsschlüssel aus dem QR-Code; nach „Party beenden“ ist der Server aus.
Die Warteschlange selbst verwaltet das Hauptfenster: Wünsche landen in einem Eingang (inbox),
das Hauptfenster holt sie ab und schickt den aktuellen Stand (snapshot) zurück.
"""
import json
import os
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import paths, tlscert

MAX_BODY = 8 * 1024
MAX_SINGERS = 60
MAX_WISHES = 6            # offene Wünsche pro Handy


def lan_ip():
    """IP-Adresse dieses Rechners im WLAN/LAN (ohne Daten zu senden)."""
    for probe in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


class Party:
    def __init__(self, search, thumb_file=None, favorites=None, likes=None):
        self.search, self.thumb_file, self.favorites, self.likes = search, thumb_file, favorites, likes
        self.srv = None
        self.tls = None                 # zweiter Server mit https – nur für die Handy-Mikro-Seite
        self.lock = threading.Lock()
        self.search_sem = threading.Semaphore(2)
        self._reset()

    def _reset(self):
        self.token = ""
        self.singers = {}           # sid → {"name", "joined"}
        self.inbox = []             # Wünsche/Löschungen für das Hauptfenster
        self.snap = {"queue": [], "now": None, "next": None, "ts": 0}
        self.seq = 0
        self.rtc = {}                   # sid → Antwort des Rechners (SDP) für das Handy-Mikro

    # ------------------------------------------------------------ Steuerung (Hauptfenster)
    def start(self):
        if self.srv:
            return self.info()
        self._reset()
        self.token = secrets.token_urlsafe(9)
        port_pref = int(paths.settings().get("party_port") or 8930)
        last = None
        for port in [port_pref] + list(range(8931, 8950)) + [0]:
            try:
                self.srv = ThreadingHTTPServer(("0.0.0.0", port), self._handler())
                break
            except OSError as e:
                last = e
        if not self.srv:
            raise RuntimeError(f"Party-Server startet nicht: {last}")
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True, name="party").start()
        paths.log.info("Party gestartet auf Port %s", self.srv.server_address[1])
        self._start_tls()
        return self.info()

    def _start_tls(self):
        """https-Server fürs Handy-Mikro (Browser geben das Mikrofon nur über https frei)."""
        try:
            pair = tlscert.ensure(lan_ip())
            if not pair:
                return
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*pair)
            for port in list(range(8960, 8980)) + [0]:
                try:
                    srv = ThreadingHTTPServer(("0.0.0.0", port), self._handler())
                    break
                except OSError:
                    srv = None
            if not srv:
                return
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
            srv.daemon_threads = True
            self.tls = srv
            threading.Thread(target=srv.serve_forever, daemon=True, name="party-tls").start()
        except Exception as e:  # noqa: BLE001 – ohne https geht alles außer dem Handy-Mikro
            paths.log.warning("Handy-Mikro (https) nicht verfügbar: %s", e)
            self.tls = None

    def stop(self):
        for attr in ("srv", "tls"):
            srv = getattr(self, attr)
            setattr(self, attr, None)
            if srv:
                threading.Thread(target=lambda s=srv: (s.shutdown(), s.server_close()), daemon=True).start()
        self._reset()
        return True

    def info(self):
        if not self.srv:
            return {"on": False}
        ip, port = lan_ip(), self.srv.server_address[1]
        mic = f"https://{ip}:{self.tls.server_address[1]}/p/{self.token}/mic" if self.tls else ""
        return {"on": True, "url": f"http://{ip}:{port}/p/{self.token}/", "ip": ip, "port": port, "mic_url": mic,
                "singers": self._singers()}

    def rtc_answer(self, sid, sdp):
        """Antwort des Rechners fürs Handy-Mikro hinterlegen; das Handy holt sie ab."""
        with self.lock:
            self.rtc[str(sid)] = str(sdp or "")
        return True

    def poll(self):
        """Neue Wünsche abholen (vom Hauptfenster etwa jede Sekunde)."""
        with self.lock:
            box, self.inbox = self.inbox, []
            return {"actions": box, "singers": self._singers()}

    def sync(self, snap):
        """Aktuellen Stand vom Hauptfenster übernehmen: Warteschlange (mit sid), jetzt, als Nächstes."""
        queue = []
        for e in (snap.get("queue") or [])[:200]:
            e = dict(e)
            th = str(e.get("thumb") or "")
            if self.thumb_file and e.get("id") and self.thumb_file(e["id"]):
                e["thumb"] = f"/p/{self.token}/thumb/{e['id']}"
            elif not th.startswith("https://"):
                e["thumb"] = ""                       # lokale Adressen (127.0.0.1) erreicht das Handy nicht
            queue.append(e)
        snap = dict(snap, queue=queue)
        with self.lock:
            self.snap = {"queue": snap.get("queue") or [], "now": snap.get("now"), "next": snap.get("next"),
                         "ts": time.time()}
        return True

    def add_singer(self, name):
        """Sänger am Rechner anlegen (ohne Handy)."""
        name = (name or "").strip()[:40]
        if not name:
            return None
        with self.lock:
            for sid, s in self.singers.items():
                if s["name"].lower() == name.lower():
                    return sid
            sid = "pc-" + secrets.token_hex(4)
            self.singers[sid] = {"name": name, "joined": time.time(), "pc": True}
            return sid

    @staticmethod
    def offline():
        """Offline-Schalter im Karaoke: nur gespeicherte Songs anbieten."""
        return bool(paths.settings().get("kara_offline"))

    def _offline_songs(self, text=""):
        words = text.lower().split()
        out = []
        for f in (self.favorites() if self.favorites else []):
            if not f.get("file"):
                continue
            hay = f"{f.get('title', '')} {f.get('channel', '')}".lower()
            if all(w in hay for w in words):
                out.append(dict(self._song(f), offline=True))
        return out

    def _singers(self):
        return [{"sid": k, "name": v["name"], "pc": bool(v.get("pc"))}
                for k, v in sorted(self.singers.items(), key=lambda x: x[1]["joined"])]

    # ------------------------------------------------------------ Handy-Schnittstelle
    def _api(self, h, path, q, body):
        sid = (q.get("sid") or [""])[0] or body.get("sid", "")
        me = self.singers.get(sid)
        if path == "join":
            name = " ".join(str(body.get("name") or "").split())[:40]
            if not name:
                return 400, {"error": "Bitte einen Namen eingeben."}
            with self.lock:
                if sid in self.singers:
                    self.singers[sid]["name"] = name
                else:
                    if len(self.singers) >= MAX_SINGERS:
                        return 400, {"error": "Die Party ist voll."}
                    taken = {s["name"].lower() for s in self.singers.values()}
                    base, n = name, 2
                    while name.lower() in taken:
                        name = f"{base} {n}"
                        n += 1
                    sid = secrets.token_urlsafe(10)
                    self.singers[sid] = {"name": name, "joined": time.time()}
                self.inbox.append({"type": "join", "sid": sid, "name": name})
            return 200, {"sid": sid, "name": name}
        if path == "state":
            with self.lock:
                snap = dict(self.snap)
            queue = snap["queue"]
            mine = [dict(e, pos=i + 1) for i, e in enumerate(queue) if e.get("sid") == sid]
            nxt = snap.get("next") or {}
            return 200, {"me": me and me["name"], "now": snap.get("now"), "next": nxt or None,
                         "youNext": bool(sid and nxt.get("sid") == sid), "mine": mine,
                         "queue": [{"title": e.get("title"), "singer": e.get("singer"), "mine": e.get("sid") == sid}
                                   for e in queue[:30]],
                         "singers": len(self.singers), "offline": self.offline()}
        if not me:
            return 403, {"error": "Bitte zuerst den Namen eintragen.", "rejoin": True}
        if path == "search":
            text = (q.get("q") or [""])[0].strip()[:80]
            if self.offline():
                return 200, {"results": self._offline_songs(text)[:40], "offline": True}
            if not text:
                return 200, {"results": self._favs()}
            if not self.search_sem.acquire(timeout=20):
                return 503, {"error": "Gerade viel los – gleich nochmal versuchen."}
            try:
                res = self.search(text, (q.get("long") or ["0"])[0] == "1")
            except Exception as e:  # noqa: BLE001 – Suche darf die Party nicht stören
                return 502, {"error": str(e) or "Suche fehlgeschlagen."}
            finally:
                self.search_sem.release()
            return 200, {"results": [self._song(s) for s in res[:25]]}
        if path == "wish":
            song = body.get("song") or {}
            if not song.get("id"):
                return 400, {"error": "Kein Song."}
            if self.offline() and not any(f["id"] == song["id"] for f in self._offline_songs()):
                return 400, {"error": "Gerade gibt es nur gespeicherte Songs – such dir einen aus der Liste aus."}
            with self.lock:
                open_n = sum(1 for e in self.snap["queue"] if e.get("sid") == sid) + \
                    sum(1 for a in self.inbox if a.get("type") == "wish" and a.get("sid") == sid)
                if open_n >= MAX_WISHES:
                    return 400, {"error": f"Du hast schon {MAX_WISHES} Songs in der Warteschlange – erst mal singen! 🎤"}
                self.seq += 1
                self.inbox.append({"type": "wish", "sid": sid, "name": me["name"], "song": self._song(song), "n": self.seq})
            return 200, {"ok": True}
        if path == "remove":
            with self.lock:
                self.inbox.append({"type": "remove", "sid": sid, "qid": body.get("qid")})
            return 200, {"ok": True}
        if path == "unwish":                      # versehentlich gewünscht: über die Song-ID wieder raus
            vid = str(body.get("id") or "")
            with self.lock:
                for i in range(len(self.inbox) - 1, -1, -1):
                    a = self.inbox[i]
                    if a.get("type") == "wish" and a.get("sid") == sid and (a.get("song") or {}).get("id") == vid:
                        del self.inbox[i]
                        return 200, {"ok": True}
                self.inbox.append({"type": "remove", "sid": sid, "id": vid})
            return 200, {"ok": True}
        if path == "move":                        # eigenen Song in der eigenen Reihenfolge hoch/runter
            d = -1 if str(body.get("dir")) in ("-1", "up") else 1
            with self.lock:
                self.inbox.append({"type": "move", "sid": sid, "qid": body.get("qid"), "dir": d})
            return 200, {"ok": True}
        if path == "rtc_offer":                   # Handy-Mikro: Verbindungsangebot des Handys an den Rechner
            sdp = str(body.get("sdp") or "")
            if not sdp.startswith("v=0") or len(sdp) > 6000:
                return 400, {"error": "Ungültig."}
            with self.lock:
                self.rtc.pop(sid, None)
                self.inbox.append({"type": "rtc_offer", "sid": sid, "name": me["name"], "sdp": sdp})
            return 200, {"ok": True}
        if path == "rtc_answer":
            with self.lock:
                return 200, {"sdp": self.rtc.get(sid) or None}
        if path == "rtc_bye":
            with self.lock:
                self.rtc.pop(sid, None)
                self.inbox.append({"type": "rtc_bye", "sid": sid})
            return 200, {"ok": True}
        if path == "likes":
            ids = [i for i in (q.get("ids") or [""])[0].split(",") if i][:12]
            try:
                return 200, {"likes": self.likes(ids) if self.likes else {}}
            except Exception:  # noqa: BLE001 – Likes sind nur Zusatz
                return 200, {"likes": {}}
        return 404, {"error": "Unbekannt."}

    def _song(self, s):
        keep = {k: s.get(k) for k in ("id", "title", "channel", "duration", "thumb", "views")}
        keep["title"] = str(keep.get("title") or "")[:160]
        keep["channel"] = str(keep.get("channel") or "")[:80]
        if self.thumb_file and keep.get("id") and self.thumb_file(keep["id"]):
            keep["thumb"] = f"/p/{self.token}/thumb/{keep['id']}"
        return keep

    def _favs(self):
        try:
            return [dict(self._song(f), offline=bool(f.get("file"))) for f in (self.favorites() if self.favorites else [])][:40]
        except Exception:  # noqa: BLE001
            return []

    def _handler(self):
        party = self
        ui = os.path.join(paths.res_dir(), "ui")
        files = {"": ("party.html", "text/html; charset=utf-8"), "mic": ("mic.html", "text/html; charset=utf-8"),
                 "i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
                 "logo.png": ("logo.png", "image/png")}

        class H(BaseHTTPRequestHandler):
            server_version = "SongGrabberParty"

            def log_message(self, *a):
                pass

            def _send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
                body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _route(self):
                u = urlparse(self.path)
                parts = u.path.split("/")
                # /p/<token>/<rest>
                if len(parts) < 3 or parts[1] != "p" or not party.token or not secrets.compare_digest(parts[2], party.token):
                    return None, None, None
                rest = "/".join(parts[3:])
                return rest, parse_qs(u.query), u

            def do_GET(self):
                rest, q, _ = self._route()
                if rest is None:
                    return self._send(404, {"error": "Diese Party gibt es nicht (mehr)."})
                if rest in files:
                    name, ctype = files[rest]
                    try:
                        with open(os.path.join(ui, name), "rb") as f:
                            return self._send(200, f.read(), ctype,
                                              {"Content-Security-Policy": "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"} if name.endswith(".html") else None)
                    except OSError:
                        return self._send(404, {"error": "fehlt"})
                if rest.startswith("thumb/"):
                    p = party.thumb_file(rest[6:]) if party.thumb_file else None
                    if p and os.path.isfile(p):
                        with open(p, "rb") as f:
                            return self._send(200, f.read(), "image/jpeg", {"Cache-Control": "max-age=3600"})
                    return self._send(404, {"error": "kein Bild"})
                if rest.startswith("api/"):
                    code, data = party._api(self, rest[4:], q, {})
                    return self._send(code, data)
                return self._send(404, {"error": "nicht gefunden"})

            def do_POST(self):
                rest, q, _ = self._route()
                if rest is None or not rest.startswith("api/"):
                    return self._send(404, {"error": "nicht gefunden"})
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._send(413, {"error": "zu groß"})
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError
                except ValueError:
                    return self._send(400, {"error": "ungültig"})
                code, data = party._api(self, rest[4:], q, body)
                return self._send(code, data)

        return H
