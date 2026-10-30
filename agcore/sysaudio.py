"""„Lichtshow für alles“: hört den Systemsound mit (WASAPI-Loopback) und liefert Spektrum + Welle,
dazu Titel/Cover/Steuerung der gerade spielenden App (Spotify, Browser, …) über die Windows-Mediensteuerung."""
import asyncio
import ctypes
import json
import threading
import time

from . import paths, recorder

try:
    import numpy as np
except ImportError:      # pragma: no cover
    np = None

BANDS = 72


class SystemAudio:
    RATE = 48000
    N = 2048

    def __init__(self, server):
        self.frame = b'{"bands":[],"wave":[],"on":false}'
        self.running = False
        self.last = 0.0
        self.error = ""
        self.device = ""
        self.lock = threading.Lock()
        server.handlers["viz"] = self._serve
        self.url = server.route("viz", "frame")

    def _serve(self, h, _rid):
        self.last = time.time()
        if not self.running:
            self.start()
        body = self.frame
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("Access-Control-Allow-Origin", "*")
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(body)

    def start(self):
        if np is None:
            self.error = "numpy fehlt"
            return
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        done = threading.Event()
        try:
            sc = recorder._audio()
            spk = sc.default_speaker()
            self.device = spk.name
            mic = sc.get_microphone(spk.id, include_loopback=True)
            threading.Thread(target=recorder.Recorder._silence_player, args=(sc, spk.id, self.RATE, done), daemon=True).start()
            ring = np.zeros(self.N, dtype="float32")
            win = np.hanning(self.N).astype("float32")
            freqs = np.fft.rfftfreq(self.N, 1 / self.RATE)
            edges = 35 * (16000 / 35) ** (np.arange(BANDS + 1) / BANDS)
            idx = [np.where((freqs >= edges[i]) & (freqs < max(edges[i + 1], edges[i] + 24)))[0] for i in range(BANDS)]
            with mic.recorder(samplerate=self.RATE, channels=2, blocksize=1024) as rec:
                self.error = ""
                while self.running and time.time() - self.last < 3:
                    d = rec.record(numframes=1024)
                    if not len(d):
                        continue
                    mono = np.ascontiguousarray(d, dtype="float32").mean(axis=1) if d.ndim > 1 else d
                    ring = np.concatenate([ring[len(mono):], mono])[-self.N:]
                    spec = np.abs(np.fft.rfft(ring * win)) / (self.N / 4)
                    db = 20 * np.log10(spec + 1e-9)
                    byte = np.clip((db + 100) / 70, 0, 1)        # wie der Browser-Analyser (-100…-30 dB)
                    bands = [float(byte[i].mean()) if len(i) else 0.0 for i in idx]
                    wave = np.clip(ring[-512::2] * 128 + 128, 0, 255).astype(int).tolist()
                    self.frame = json.dumps({"bands": [round(b, 3) for b in bands], "wave": wave, "on": True,
                                             "peak": round(float(np.abs(mono).max()), 3)}).encode()
        except Exception as e:
            self.error = str(e)[:160]
            self.frame = json.dumps({"bands": [], "wave": [], "on": False, "error": self.error}).encode()
        finally:
            done.set()
            self.running = False


# ---------------------------------------------------------------- Windows-Mediensteuerung (GSMTC)

def _gsmtc():
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
        return M
    except Exception:
        try:
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            return M
        except Exception:
            return None


APP_NAMES = {"spotify": "Spotify", "chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox",
             "vlc": "VLC", "zunemusic": "Windows Media Player", "music.ui": "Windows Media Player", "applemusic": "Apple Music",
             "deezer": "Deezer", "tidal": "TIDAL", "amazonmusic": "Amazon Music", "opera": "Opera", "brave": "Brave"}


def _app(aumid):
    a = (aumid or "").lower()
    for k, v in APP_NAMES.items():
        if k in a:
            return v
    return (aumid or "Unbekannte App").split("!")[0].split("\\")[-1].replace(".exe", "")


class NowPlaying:
    def __init__(self, server):
        self.M = _gsmtc() if paths.IS_WIN else None
        self.art = (None, b"", "")
        server.handlers["sysart"] = self._serve_art
        self.art_url = server.route("sysart", "cover")

    def available(self):
        return self.M is not None

    def _serve_art(self, h, _rid):
        data = self.art[1]
        if not data:
            h.send_error(404)
            return
        h.send_response(200)
        h.send_header("Content-Type", "image/png" if data[:4] == b"\x89PNG" else "image/jpeg")
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("Access-Control-Allow-Origin", "*")
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(data)

    async def _info(self):
        mgr = await self.M.request_async()
        s = mgr.get_current_session()
        if s is None:
            return {"active": False}
        props = await s.try_get_media_properties_async()
        pb = s.get_playback_info()
        out = {"active": True, "app": _app(s.source_app_user_model_id), "title": props.title or "",
               "artist": props.artist or "", "album": props.album_title or "",
               "playing": int(pb.playback_status) == 4}
        try:
            tl = s.get_timeline_properties()
            pos, dur = tl.position.total_seconds(), tl.end_time.total_seconds()
            out["position"], out["duration"], out["pos_live"] = pos, dur, False
            try:        # Apps melden die Position oft nur beim Start/Spulen → bis jetzt hochrechnen
                upd = tl.last_updated_time
                upd = upd.timestamp() if hasattr(upd, "timestamp") else float(upd)
                age = time.time() - upd
                if 0 <= age < 6 * 3600:
                    out["pos_live"] = True
                    if out["playing"]:
                        pos += age
            except Exception:
                pass
            out["pos_now"] = max(0.0, min(pos, dur)) if dur > 0 else pos
        except Exception:
            pass
        key = (out["title"], out["artist"])
        if self.art[0] != key:
            self.art_since = time.time()
        fresh = time.time() - getattr(self, "art_since", 0) < 8      # Browser liefert das neue Bild oft erst später
        if props.thumbnail is not None and (self.art[0] != key or fresh):
            try:
                data = await self._read(props.thumbnail)
                if self.art[0] != key or data != self.art[1]:
                    self.art = (key, data, str(time.time()))
            except Exception:
                if self.art[0] != key:
                    self.art = (key, b"", "")
        elif props.thumbnail is None and self.art[0] != key:
            self.art = (key, b"", "")
        out["art"] = f"{self.art_url}?v={self.art[2]}" if self.art[1] else ""
        return out

    async def _read(self, ref):
        try:
            from winrt.windows.storage.streams import Buffer, InputStreamOptions, DataReader
        except Exception:
            from winsdk.windows.storage.streams import Buffer, InputStreamOptions, DataReader
        stream = await ref.open_read_async()
        size = int(stream.size)
        buf = Buffer(size)
        await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
        try:
            return bytes(memoryview(buf))[: buf.length]
        except Exception:
            reader = DataReader.from_buffer(buf)
            arr = bytearray(buf.length)
            reader.read_bytes(arr)
            return bytes(arr)

    def info(self):
        if not self.M:
            return {"active": False, "unavailable": True}
        try:
            return asyncio.run(asyncio.wait_for(self._info(), 4))
        except Exception as e:
            paths.log.warning("Mediensteuerung: %s", e)
            return {"active": False, "error": str(e)[:120]}

    async def _cmd(self, cmd):
        mgr = await self.M.request_async()
        s = mgr.get_current_session()
        if s is None:
            return False
        f = {"toggle": s.try_toggle_play_pause_async, "next": s.try_skip_next_async, "prev": s.try_skip_previous_async}[cmd]
        return bool(await f())

    def control(self, cmd):
        if self.M:
            try:
                if asyncio.run(asyncio.wait_for(self._cmd(cmd), 4)):
                    return True
            except Exception:
                pass
        if paths.IS_WIN:                         # Ersatz: Medientaste drücken (wirkt auf Spotify & Co.)
            vk = {"toggle": 0xB3, "next": 0xB0, "prev": 0xB1}[cmd]
            u = ctypes.windll.user32
            u.keybd_event(vk, 0, 0, 0)
            u.keybd_event(vk, 0, 2, 0)
            return True
        return False
