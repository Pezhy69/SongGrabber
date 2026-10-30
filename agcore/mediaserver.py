"""Kleiner lokaler Medienserver für den eingebauten Player (nur 127.0.0.1, mit Token, Spulen per Range)."""
import hashlib
import http.server
import mimetypes
import os
import secrets
import socketserver
import threading
import urllib.parse

MIME = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".aac": "audio/aac", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".webm": "audio/webm",
        ".mka": "audio/x-matroska", ".jpg": "image/jpeg", ".png": "image/png"}


class MediaServer:
    def __init__(self):
        self.token = secrets.token_urlsafe(12)
        self.files = {}
        self.handlers = {}             # weitere Routen: kind → handler(request, id)
        self.lock = threading.Lock()
        server = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                server._serve(self)

            do_HEAD = do_GET

        class TS(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.httpd = TS(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path, kind="m"):
        """Gibt eine abspielbare URL für eine lokale Datei zurück."""
        if not path or not os.path.isfile(path):
            return ""
        fid = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]
        with self.lock:
            self.files[fid] = os.path.abspath(path)
        return f"http://127.0.0.1:{self.port}/{self.token}/{kind}/{fid}"

    def route(self, kind, rid):
        return f"http://127.0.0.1:{self.port}/{self.token}/{kind}/{rid}"

    def _serve(self, h):
        parts = urllib.parse.urlparse(h.path).path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != self.token:
            h.send_error(403)
            return
        _, kind, fid = parts
        if kind in self.handlers:                      # Online-Quellen, Bilder, Lichtshow-Daten
            try:
                self.handlers[kind](h, fid)
            except (ConnectionError, BrokenPipeError, OSError):
                pass
            return
        path = self.files.get(fid)
        if not path or not os.path.isfile(path):
            h.send_error(404)
            return
        if kind == "art":
            data = cover_bytes(path)
            if not data:
                h.send_error(404)
                return
            h.send_response(200)
            h.send_header("Content-Type", "image/png" if data[:4] == b"\x89PNG" else "image/jpeg")
            h.send_header("Content-Length", str(len(data)))
            h.send_header("Cache-Control", "max-age=3600")
            h.send_header("Access-Control-Allow-Origin", "*")
            h.end_headers()
            if h.command != "HEAD":
                h.wfile.write(data)
            return
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = h.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            if a:
                start = int(a)
                end = int(b) if b else end
            elif b:
                start = max(0, size - int(b))
            end = min(end, size - 1)
            h.send_response(206)
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            h.send_response(200)
        ext = os.path.splitext(path)[1].lower()
        h.send_header("Content-Type", MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream")
        h.send_header("Accept-Ranges", "bytes")
        h.send_header("Content-Length", str(end - start + 1))
        h.send_header("Access-Control-Allow-Origin", "*")
        h.end_headers()
        if h.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    h.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass


def cover_bytes(path):
    """Eingebettetes Cover aus MP3/FLAC/M4A lesen."""
    try:
        import mutagen
        from mutagen.flac import FLAC
        from mutagen.mp4 import MP4
        f = mutagen.File(path)
        if f is None:
            return None
        if isinstance(f, FLAC) and f.pictures:
            return f.pictures[0].data
        if isinstance(f, MP4):
            c = (f.tags or {}).get("covr")
            return bytes(c[0]) if c else None
        tags = getattr(f, "tags", None)
        if tags is not None and hasattr(tags, "getall"):
            apic = tags.getall("APIC")
            return apic[0].data if apic else None
        pics = getattr(f, "pictures", None)
        return pics[0].data if pics else None
    except Exception:
        return None
