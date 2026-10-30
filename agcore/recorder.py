"""Aufnahme: Systemsound (WASAPI-Loopback), Line-In (Plattenspieler, Kassette), Mikrofon."""
import collections
import os
import sys
import threading
import time
import warnings
import wave

from . import encoder, paths, pipeline

try:
    import numpy as np
except ImportError:          # pragma: no cover
    np = None


def _com_init():
    if paths.IS_WIN:
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0)       # COINIT_MULTITHREADED
        except Exception:
            pass


def _sc():
    import soundcard as sc
    warnings.filterwarnings("ignore", category=getattr(sc, "SoundcardRuntimeWarning", RuntimeWarning))
    return sc


_sc_lock = threading.Lock()


def _audio():
    """Pro Audio-Thread aufrufen. Beim allerersten Laden initialisiert soundcard COM selbst –
    vorher darf COM nicht schon aktiv sein, sonst meldet soundcard „Error 0x100000001“ (S_FALSE)."""
    with _sc_lock:
        if "soundcard" in sys.modules:
            _com_init()
        return _sc()


def _in_audio_thread(fn):
    box = {}

    def t():
        try:
            box["v"] = fn(_audio())
        except Exception as e:
            box["e"] = e
    th = threading.Thread(target=t, daemon=True)
    th.start()
    th.join(15)
    if "e" in box:
        raise box["e"]
    return box.get("v")


def devices():
    def f(sc):
        out = []
        default, default_mic = None, None
        try:
            default = sc.default_speaker().name
        except Exception:
            pass
        try:
            default_mic = sc.default_microphone().id
        except Exception:
            pass
        for m in sc.all_microphones(include_loopback=True):
            lb = bool(m.isloopback)
            out.append({"id": m.id, "name": m.name, "loopback": lb,
                        "default": (lb and m.name == default) or (not lb and m.id == default_mic),
                        "channels": getattr(m, "channels", 2)})
        out.sort(key=lambda d: (not d["loopback"], not d["default"], d["name"]))
        return out
    return _in_audio_thread(f)


def _db(x):
    return -90.0 if x <= 1e-5 else max(-90.0, 20 * np.log10(x))


def _hit_fields(hit, meta):
    f = {"artist": hit["artist"], "title": hit["title"]}
    for k in ("album", "album_artist", "genre", "date", "track"):
        if hit.get(k):
            f[k] = hit[k]
    if meta.get("genre") and not hit.get("genre"):
        f["genre"] = meta["genre"]
    return f


def _cover(hit):
    if not hit.get("cover_url"):
        return None
    from . import musicbrainz
    p = musicbrainz.download_cover(hit["cover_url"], os.path.join(paths.temp_dir(), "erkannt.jpg"))
    if not p:
        return None
    with open(p, "rb") as f:
        return f.read()


# ---------------------------------------------------------------- Windows-Datenschutz

def mic_privacy():
    """'deny', wenn Windows Desktop-Programmen den Mikrofonzugriff verbietet (Aufnahme wäre stumm)."""
    if not paths.IS_WIN:
        return "ok"
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, base), (winreg.HKEY_CURRENT_USER, base),
                      (winreg.HKEY_CURRENT_USER, base + r"\NonPackaged")):
        try:
            with winreg.OpenKey(root, key) as k:
                if str(winreg.QueryValueEx(k, "Value")[0]).lower() == "deny":
                    return "deny"
        except OSError:
            pass
    return "ok"


def open_privacy_settings():
    if paths.IS_WIN:
        os.startfile("ms-settings:privacy-microphone")
    return True


# ---------------------------------------------------------------- Eingänge live beobachten

class Monitor:
    """Öffnet alle Eingänge gleichzeitig und misst den Pegel – so sieht man beim Sprechen,
    welches Mikrofon das richtige ist. Stoppt sich selbst, wenn niemand mehr nachfragt."""
    BLOCK = 1024
    RATE = 48000

    def __init__(self):
        self.levels = {}
        self.lock = threading.Lock()
        self.running = False
        self.last_poll = 0.0
        self.paused = threading.Event()

    def poll(self):
        self.last_poll = time.time()
        if not self.running:
            self.start()
        with self.lock:
            return {k: dict(v) for k, v in self.levels.items()}

    def start(self):
        self.running = True
        self.paused.clear()
        self.done = threading.Event()
        threading.Thread(target=self._spawn, daemon=True).start()

    def stop(self):
        self.running = False
        if getattr(self, "done", None):
            self.done.set()

    def _spawn(self):
        try:
            mics = [m for m in _audio().all_microphones(include_loopback=True)]
        except Exception as e:
            with self.lock:
                self.levels = {"_error": {"error": str(e)}}
            self.running = False
            return
        with self.lock:
            self.levels = {m.id: {"peak": -90.0, "rms": -90.0, "zero": 0.0, "state": "start", "error": "",
                                  "loop": bool(m.isloopback)} for m in mics}
        for m in mics:
            threading.Thread(target=self._watch, args=(m.id, bool(m.isloopback)), daemon=True).start()
        while self.running and time.time() - self.last_poll < 4:
            time.sleep(0.5)
        self.running = False
        self.done.set()

    def _watch(self, dev_id, loop=False):
        lv = self.levels[dev_id]
        hold, hold_t = -90.0, 0.0
        try:
            sc = _audio()
            mic = sc.get_microphone(dev_id, include_loopback=True)
            ch = 2 if getattr(mic, "channels", 1) >= 2 else 1
            if loop:     # Loopback liefert bei Stille keine Daten – stummer Player hält ihn am Laufen
                threading.Thread(target=Recorder._silence_player, args=(sc, dev_id, self.RATE, self.done),
                                 daemon=True).start()
            with mic.recorder(samplerate=self.RATE, channels=ch, blocksize=self.BLOCK) as r:
                lv["state"] = "ok"
                while self.running:
                    data = r.record(numframes=self.BLOCK)
                    if not len(data):
                        continue
                    pk = float(np.abs(data).max())
                    rm = float(np.sqrt((data.astype("float64") ** 2).mean()))
                    now = time.time()
                    p = _db(pk)
                    if p > hold or now - hold_t > 1.2:
                        hold, hold_t = p, now
                    with self.lock:
                        lv["peak"], lv["rms"], lv["hold"] = p, _db(rm), hold
                        lv["zero"] = lv["zero"] + self.BLOCK / self.RATE if pk == 0.0 else 0.0
        except Exception as e:
            lv["state"], lv["error"] = "error", str(e)[:120]


class Recorder:
    BLOCK_S = 0.04

    def __init__(self, jobs):
        self.jobs = jobs
        self.state = "idle"          # idle | armed | recording | paused | finishing
        self.lock = threading.Lock()
        self.reset_meters()
        self.thread = None
        self.opts = {}
        self.file = None
        self.error = ""

    def reset_meters(self):
        self.peak = [-90.0, -90.0]
        self.rms = [-90.0, -90.0]
        self.wave = collections.deque(maxlen=600)
        self.frames = 0
        self.clips = 0
        self.silence_s = 0.0
        self.zero_s = 0.0            # „digitale Stille“ = exakt 0 → Windows blockiert oder Gerät liefert nichts

    # ---------------------------------------------------------------- Steuerung
    def start(self, opts):
        if np is None:
            raise RuntimeError("numpy fehlt.")
        if self.state not in ("idle",):
            raise RuntimeError("Es läuft bereits eine Aufnahme.")
        self.opts = dict(opts)
        self.reset_meters()
        self.error = ""
        self.state = "armed" if opts.get("wait_signal") else "recording"
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self.status()

    def pause(self):
        if self.state == "recording":
            self.state = "paused"
        elif self.state == "paused":
            self.state = "recording"
        return self.status()

    def stop(self, meta=None):
        if self.state in ("idle", "finishing"):
            return self.status()
        self.opts["meta"] = meta or self.opts.get("meta") or {}
        self._stop.set()
        return self.status()

    def discard(self):
        self.opts["discard"] = True
        return self.stop()

    def set_gain(self, db):
        self.opts["gain_db"] = float(db)
        return True

    # ---------------------------------------------------------------- Aufnahmeschleife
    def _run(self):
        o = self.opts
        sr = int(o.get("samplerate", 48000))
        bits = int(o.get("bitdepth", 24))
        thr = float(o.get("threshold_db", -42))
        stop_after = float(o.get("stop_silence", 0) or 0)
        block = int(sr * self.BLOCK_S)
        self.file = os.path.join(paths.temp_dir(), f"aufnahme_{time.strftime('%Y%m%d_%H%M%S')}.wav")
        keepalive = threading.Event()
        try:
            sc = _audio()
            mic = sc.get_microphone(o["device"], include_loopback=True)
            ch = 2 if getattr(mic, "channels", 2) >= 2 else 1
            if mic.isloopback:
                threading.Thread(target=self._silence_player, args=(sc, o["device"], sr, keepalive),
                                 daemon=True).start()
            preroll = collections.deque(maxlen=int(0.5 / self.BLOCK_S))
            with mic.recorder(samplerate=sr, channels=ch, blocksize=block) as rec, \
                    wave.open(self.file, "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(bits // 8)
                w.setframerate(sr)
                while not self._stop.is_set():
                    data = np.ascontiguousarray(rec.record(numframes=block), dtype="float32")
                    if data.ndim == 1:
                        data = data[:, None]
                    if data.shape[1] == 1:
                        data = np.repeat(data, 2, axis=1)
                    data = data[:, :2] * (10 ** (float(o.get("gain_db", 0)) / 20))
                    pk = np.abs(data).max(axis=0) if len(data) else np.zeros(2)
                    rm = np.sqrt((data ** 2).mean(axis=0)) if len(data) else np.zeros(2)
                    loud = _db(float(pk.max()))
                    if mic.isloopback:
                        self.zero_s = 0.0
                    else:
                        self.zero_s = self.zero_s + self.BLOCK_S if not np.any(data) else 0.0
                    with self.lock:
                        self.peak = [_db(float(pk[0])), _db(float(pk[1]))]
                        self.rms = [_db(float(rm[0])), _db(float(rm[1]))]
                        self.clips += int((np.abs(data) >= 0.999).sum())
                    pcm = self._pcm(np.clip(data, -1, 1), bits)
                    if self.state == "armed":
                        preroll.append(pcm)
                        if loud > thr:
                            self.state = "recording"
                            for p in preroll:
                                w.writeframes(p)
                                self.frames += len(p) // (2 * bits // 8)
                        continue
                    if self.state != "recording":
                        continue
                    w.writeframes(pcm)
                    self.frames += len(data)
                    self.wave.append(round(float(pk.max()), 3))
                    self.silence_s = self.silence_s + self.BLOCK_S if loud < thr else 0.0
                    if stop_after and self.silence_s >= stop_after and self.frames / sr > stop_after + 5:
                        break
        except Exception as e:
            self.error = str(e)
        finally:
            keepalive.set()
        self.state = "finishing"
        self._handoff(sr)
        self.state = "idle"

    @staticmethod
    def _pcm(data, bits):
        if bits == 16:
            return (data * 32767).astype("<i2").tobytes()
        i = np.ascontiguousarray((data * 8388607).astype("<i4"))
        return i.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()

    @staticmethod
    def _silence_player(sc, speaker_id, sr, done):
        """WASAPI-Loopback liefert bei Stille keine Daten – ein stummer Player hält ihn wach."""
        _com_init()
        try:
            spk = sc.get_speaker(speaker_id)
            zeros = np.zeros((int(sr * 0.1), 2), dtype="float32")
            with spk.player(samplerate=sr, channels=2) as p:
                while not done.is_set():
                    p.play(zeros)
        except Exception:
            pass

    def _handoff(self, sr):
        o, f = self.opts, self.file
        if o.get("discard") or not f or not os.path.exists(f) or self.frames < sr:
            try:
                os.remove(f)
            except (OSError, TypeError):
                pass
            return
        meta = o.get("meta") or {}
        split = bool(o.get("auto_split"))
        vinyl = bool(o.get("vinyl_clean"))
        duration = self.frames / sr

        def run(job):
            s = paths.settings()
            try:
                segs = [(0.0, duration)]
                if split:
                    job.set(0.02, "Suche Pausen zwischen den Titeln …")
                    segs = encoder.split_points(f, duration, float(o.get("split_db", -45)),
                                                float(o.get("split_pause", 1.5)))
                n = len(segs)
                base_title = meta.get("title") or ("Aufnahme " + time.strftime("%Y-%m-%d %H-%M"))
                titles = meta.get("titles") or []
                files = []
                for i, (a, b) in enumerate(segs, 1):
                    if job.cancel.is_set():
                        raise encoder.Cancelled()
                    title = titles[i - 1] if i - 1 < len(titles) and titles[i - 1] else \
                        (f"{base_title} – Titel {i:02d}" if n > 1 and not meta.get("album") else
                         (f"Titel {i:02d}" if n > 1 else base_title))
                    tags = {"title": title, "artist": meta.get("artist") or "Aufnahme",
                            "album": meta.get("album") or "", "album_artist": meta.get("artist") or "",
                            "date": meta.get("year") or time.strftime("%Y"), "genre": meta.get("genre") or "",
                            "track": f"{i}/{n}" if n > 1 else ""}
                    pipeline.output(job, f, tags, album=bool(meta.get("album")) and n > 1,
                                    start=a if n > 1 else None, end=b if n > 1 else None, vinyl=vinyl,
                                    src_info={"audio": [{"rate": sr}], "duration": duration},
                                    p0=0.05 + 0.95 * (i - 1) / n, p1=0.05 + 0.95 * i / n,
                                    stage=f"Titel {i}/{n}" if n > 1 else "Umwandeln")
                    files.append(job.outputs[-1])
                    if not meta.get("titles") and s.get("acoustid_auto") and s.get("acoustid_key"):
                        job.set(None, f"Erkenne Titel {i}/{n} …")
                        try:
                            from . import identify, library
                            hit = identify.identify(job.outputs[-1])
                            if hit:
                                new = library.apply_tags(job.outputs[-1], _hit_fields(hit, meta), _cover(hit))
                                job.outputs[-1] = files[-1] = new
                                job.recognized = getattr(job, "recognized", 0) + 1
                        except Exception:
                            pass
                if n > 1:
                    pipeline.write_m3u(files, meta.get("album") or base_title)
                rec = getattr(job, "recognized", 0)
                job.set(1.0, (f"Fertig · {n} Titel" if n > 1 else "Fertig") + (f" · {rec} erkannt" if rec else ""))
            finally:
                if s["keep_raw"]:
                    dst = paths.unique(os.path.join(s["output_dir"], os.path.basename(f)))
                    try:
                        os.makedirs(s["output_dir"], exist_ok=True)
                        os.replace(f, dst)
                        job.outputs.append(dst)
                    except OSError:
                        pass
                else:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
        label = meta.get("album") or meta.get("title") or "Aufnahme"
        self.jobs.add("rec", label, run, f"{int(duration // 60)}:{int(duration % 60):02d} min aufgenommen")

    def status(self):
        sr = int(self.opts.get("samplerate", 48000) or 48000)
        with self.lock:
            return {"state": self.state, "peak": self.peak, "rms": self.rms,
                    "elapsed": self.frames / sr, "clips": self.clips, "wave": list(self.wave)[-300:],
                    "silence": round(self.silence_s, 1), "zero": round(self.zero_s, 1), "error": self.error}
