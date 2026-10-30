"""Linux: „Alles am PC“ über MPRIS (D-Bus) – Titel, Interpret, Cover, Position und Steuerung von
Spotify, Firefox, Chrome, VLC, Rhythmbox & Co. Nutzt jeepney (reines Python)."""
import threading
import time
import urllib.parse
import urllib.request

PREFIX = "org.mpris.MediaPlayer2."
PLAYER = "org.mpris.MediaPlayer2.Player"


def _v(x):
    """jeepney liefert Varianten als (Signatur, Wert)."""
    return x[1] if isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], str) else x


class Mpris:
    def __init__(self):
        from jeepney import DBusAddress  # noqa: F401  (früh prüfen, ob vorhanden)
        self.lock = threading.Lock()
        self.conn = None
        self.art = {}                      # artUrl → bytes

    def _c(self):
        if self.conn is None:
            from jeepney.io.blocking import open_dbus_connection
            self.conn = open_dbus_connection(bus="SESSION")
        return self.conn

    def _call(self, addr, method, sig=None, body=()):
        from jeepney import new_method_call
        msg = new_method_call(addr, method, sig, body) if sig else new_method_call(addr, method)
        try:
            return self._c().send_and_get_reply(msg, timeout=2).body
        except Exception:
            self.conn = None
            raise

    def _get(self, name, iface, prop):
        from jeepney import DBusAddress, Properties
        a = DBusAddress("/org/mpris/MediaPlayer2", bus_name=name, interface=iface)
        msg = Properties(a).get(prop)
        try:
            return _v(self._c().send_and_get_reply(msg, timeout=2).body[0])
        except Exception:
            return None

    def players(self):
        from jeepney import DBusAddress
        bus = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus", interface="org.freedesktop.DBus")
        return [n for n in self._call(bus, "ListNames")[0] if n.startswith(PREFIX)]

    def _pick(self):
        best, rank = None, -1
        for n in self.players():
            st = self._get(n, PLAYER, "PlaybackStatus") or ""
            r = {"Playing": 2, "Paused": 1}.get(st, 0)
            if r > rank:
                best, rank = (n, st), r
        return best

    def info(self):
        with self.lock:
            p = self._pick()
            if not p:
                return {"active": False}
            name, status = p
            md = self._get(name, PLAYER, "Metadata") or {}
            md = {k: _v(v) for k, v in md.items()}
            ident = self._get(name, "org.mpris.MediaPlayer2", "Identity") or name[len(PREFIX):].split(".")[0].title()
            artist = md.get("xesam:artist") or ""
            if isinstance(artist, (list, tuple)):
                artist = ", ".join(str(a) for a in artist)
            out = {"active": True, "app": str(ident), "title": str(md.get("xesam:title") or ""), "artist": str(artist),
                   "album": str(md.get("xesam:album") or ""), "playing": status == "Playing",
                   "art_src": str(md.get("mpris:artUrl") or "")}
            length = md.get("mpris:length")
            pos = self._get(name, PLAYER, "Position")
            if length:
                out["duration"] = float(length) / 1e6
                if pos is not None:
                    out["position"] = out["pos_now"] = max(0.0, float(pos) / 1e6)
                    out["pos_live"] = True              # MPRIS liefert die Position zum Abfragezeitpunkt
            return out

    def art_bytes(self, url):
        if not url:
            return b""
        if url in self.art:
            return self.art[url]
        data = b""
        try:
            if url.startswith("file://"):
                with open(urllib.parse.unquote(urllib.parse.urlparse(url).path), "rb") as f:
                    data = f.read()
            elif url.startswith(("http://", "https://")):
                req = urllib.request.Request(url, headers={"User-Agent": "SongGrabber"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = r.read(8_000_000)
        except Exception:
            data = b""
        if len(self.art) > 50:
            self.art.clear()
        self.art[url] = data
        return data

    def control(self, cmd):
        from jeepney import DBusAddress
        with self.lock:
            p = self._pick()
            if not p:
                return False
            a = DBusAddress("/org/mpris/MediaPlayer2", bus_name=p[0], interface=PLAYER)
            try:
                self._call(a, {"toggle": "PlayPause", "next": "Next", "prev": "Previous"}[cmd])
                return True
            except Exception:
                return False


def create():
    try:
        m = Mpris()
        m.players()
        return m
    except Exception:
        return None
