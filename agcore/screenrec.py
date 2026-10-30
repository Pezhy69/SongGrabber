"""Bildschirmaufnahme mit Ton: ganzer Bildschirm oder ein Fenster (z. B. Zoom, Teams, Coaching),
dazu der Ton vom PC und auf Wunsch das Mikrofon – als MP4, optional zusätzlich als MP3.

Bild: ffmpeg (Windows gdigrab, Linux x11grab). Ton: SongGrabber selbst (wie bei „Aufnahme“), in getrennten
Spuren, die am Ende passend zum Bild verschoben und gemischt werden. Pause = neuer Abschnitt; beim Stoppen
werden alle Abschnitte zu einer Datei zusammengefügt.
"""
import base64
import ctypes
import os
import re
import shutil
import subprocess
import threading
import time
import wave

import numpy as np

from . import paths, recorder

RATE = 48000
QUALITY = {"high": 20, "normal": 25, "small": 31}          # x264 CRF: kleiner = schärfer
APP_NAMES = {"zoom": "Zoom", "ms-teams": "Microsoft Teams", "teams": "Microsoft Teams", "chrome": "Google Chrome",
             "msedge": "Microsoft Edge", "firefox": "Firefox", "webex": "Webex", "skype": "Skype", "discord": "Discord",
             "obs64": "OBS", "slack": "Slack", "whatsapp": "WhatsApp", "explorer": "Explorer", "vlc": "VLC",
             "powerpnt": "PowerPoint", "winword": "Word", "excel": "Excel", "acrobat": "Acrobat", "signal": "Signal"}


def _nice_app(exe):
    b = os.path.splitext(os.path.basename(exe or ""))[0].lower()
    for k, v in APP_NAMES.items():
        if b == k or b.startswith(k):
            return v
    return os.path.splitext(os.path.basename(exe or ""))[0] or "Programm"


def wayland():
    return not paths.IS_WIN and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" and not os.environ.get("DISPLAY")


# ---------------------------------------------------------------- Quellen: Bildschirme & Fenster
def _win_screens():
    from ctypes import wintypes
    u = ctypes.windll.user32

    class MI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]
    out = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(h, _dc, _r, _l):
        mi = MI()
        mi.cbSize = ctypes.sizeof(MI)
        u.GetMonitorInfoW(ctypes.c_void_p(h), ctypes.byref(mi))
        r = mi.rcMonitor
        out.append({"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top, "primary": bool(mi.dwFlags & 1)})
        return True
    u.EnumDisplayMonitors(None, None, proto(cb), 0)
    return out


def _win_windows():
    from ctypes import wintypes
    u, k, dwm = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.dwmapi
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    k.OpenProcess.restype = wintypes.HANDLE
    me, out = os.getpid(), []

    def cb(h, _):
        if not u.IsWindowVisible(h):
            return True
        n = u.GetWindowTextLengthW(h)
        if n <= 0:
            return True
        if u.GetWindowLongW(h, -20) & 0x80:                        # WS_EX_TOOLWINDOW
            return True
        cloaked = wintypes.DWORD(0)
        dwm.DwmGetWindowAttribute(wintypes.HWND(h), 14, ctypes.byref(cloaked), 4)   # DWMWA_CLOAKED
        if cloaked.value:
            return True
        r = wintypes.RECT()
        if dwm.DwmGetWindowAttribute(wintypes.HWND(h), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:   # sichtbarer Rahmen
            u.GetWindowRect(wintypes.HWND(h), ctypes.byref(r))
        w, hh = r.right - r.left, r.bottom - r.top
        if w < 160 or hh < 120:
            return True
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == me:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        exe = ""
        hp = k.OpenProcess(0x1000, False, pid.value)                 # PROCESS_QUERY_LIMITED_INFORMATION
        if hp:
            pb, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
            if k.QueryFullProcessImageNameW(hp, 0, pb, ctypes.byref(size)):
                exe = pb.value
            k.CloseHandle(hp)
        if os.path.basename(exe).lower() in ("textinputhost.exe", "applicationframehost.exe", "shellexperiencehost.exe"):
            return True
        out.append({"id": f"win:{int(h)}", "title": buf.value, "app": _nice_app(exe), "x": r.left, "y": r.top,
                    "w": w, "h": hh, "minimized": bool(u.IsIconic(h))})
        return True
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u.EnumWindows(proto(cb), 0)
    return out


def _x_screens():
    out = []
    if shutil.which("xrandr"):
        r = paths.run(["xrandr", "--listmonitors"], timeout=5)
        for line in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
            m = re.search(r"(\d+):\s+\+?(\*?)\S*\s+(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)", line)
            if m:
                out.append({"x": int(m.group(5)), "y": int(m.group(6)), "w": int(m.group(3)), "h": int(m.group(4)),
                            "primary": m.group(2) == "*"})
    if not out and shutil.which("xwininfo"):
        r = paths.run(["xwininfo", "-root"], timeout=5).stdout.decode("utf-8", "replace")
        w, h = re.search(r"Width:\s*(\d+)", r), re.search(r"Height:\s*(\d+)", r)
        if w and h:
            out.append({"x": 0, "y": 0, "w": int(w.group(1)), "h": int(h.group(1)), "primary": True})
    return out


def _x_windows():
    out = []
    if not shutil.which("wmctrl"):
        return out
    r = paths.run(["wmctrl", "-lpG"], timeout=5)
    me = os.getpid()
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        p = line.split(None, 8)
        if len(p) < 8:
            continue
        wid, desk, pid, x, y, w, h = p[0], p[1], int(p[2]), int(p[3]), int(p[4]), int(p[5]), int(p[6])
        title = p[8] if len(p) > 8 else ""
        if desk == "-1" or pid == me or w < 160 or h < 120 or not title:
            continue
        exe = ""
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            pass
        out.append({"id": f"win:{int(wid, 16)}", "title": title, "app": _nice_app(exe), "x": x, "y": y, "w": w, "h": h,
                    "minimized": False})
    return out


def sources():
    if wayland():
        return {"supported": False, "screens": [], "windows": [],
                "reason": "Unter Wayland erlaubt Linux Bildschirmaufnahmen nur über eigene Freigabe-Dialoge. "
                          "Bitte beim Anmelden die Sitzung „… auf Xorg“ wählen – dann funktioniert es."}
    try:
        screens = _win_screens() if paths.IS_WIN else _x_screens()
        windows = _win_windows() if paths.IS_WIN else _x_windows()
    except Exception as e:
        paths.log.warning("Bildschirmquellen: %s", e)
        screens, windows = [], []
    if screens and not any(s["primary"] for s in screens):
        min(screens, key=lambda s: (s["x"] != 0 or s["y"] != 0, s["x"], s["y"]))["primary"] = True
    screens.sort(key=lambda s: (not s["primary"], s["x"], s["y"]))
    sc = []
    for i, s in enumerate(screens, 1):
        sc.append(dict(s, id=f"screen:{i - 1}",
                       name=f"Bildschirm {i}" + (" (Hauptbildschirm)" if s["primary"] and len(screens) > 1 else ""),
                       size=f"{s['w']} × {s['h']}"))
    windows.sort(key=lambda w: (w["minimized"], w["app"].lower(), w["title"].lower()))
    return {"supported": True, "screens": sc, "windows": windows, "reason": ""}


def _find(src_id):
    s = sources()
    for x in s["screens"] + s["windows"]:
        if x["id"] == src_id:
            return x
    if src_id.startswith("win:"):
        return {"id": src_id, "title": "Fenster", "app": "Programm", "x": 0, "y": 0, "w": 0, "h": 0}
    raise RuntimeError("Diese Quelle gibt es nicht mehr – bitte neu auswählen.")


def _video_input(src, fps, cursor, by_title=False):
    """ffmpeg-Eingabe für Bildschirm/Fenster."""
    fps, cur = str(int(fps)), "1" if cursor else "0"
    if paths.IS_WIN:
        if src["id"].startswith("win:"):                   # ältere ffmpeg-Versionen kennen nur „title=“
            target = f"title={src.get('title', '')}" if by_title else f"hwnd={src['id'][4:]}"
            return ["-f", "gdigrab", "-framerate", fps, "-draw_mouse", cur, "-i", target]
        return ["-f", "gdigrab", "-framerate", fps, "-draw_mouse", cur, "-offset_x", str(src["x"]), "-offset_y", str(src["y"]),
                "-video_size", f"{src['w']}x{src['h']}", "-i", "desktop"]
    disp = os.environ.get("DISPLAY", ":0")
    if src["id"].startswith("win:"):
        return ["-f", "x11grab", "-framerate", fps, "-draw_mouse", cur, "-window_id", src["id"][4:], "-i", disp]
    return ["-f", "x11grab", "-framerate", fps, "-draw_mouse", cur, "-video_size", f"{src['w']}x{src['h']}",
            "-i", f"{disp}+{src['x']},{src['y']}"]


def preview(src_id, width=480):
    """Ein Standbild der Quelle (JPEG als data-URL) – damit man sieht, was aufgenommen würde."""
    src = _find(src_id)
    for by_title in (False, True):
        args = [paths.ffmpeg(), "-hide_banner", "-loglevel", "error"] + _video_input(src, 5, True, by_title) + \
               ["-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2", "-c:v", "mjpeg", "-q:v", "5", "pipe:1"]
        r = paths.run(args, timeout=15)
        if r.returncode == 0 or not (paths.IS_WIN and src["id"].startswith("win:")):
            break
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError((r.stderr.decode("utf-8", "replace").strip().splitlines() or ["Kein Bild"])[-1])
    return "data:image/jpeg;base64," + base64.b64encode(r.stdout).decode()


# ---------------------------------------------------------------- Ton
class _Audio(threading.Thread):
    """Nimmt eine Tonquelle (PC-Ton oder Mikrofon) in eine WAV-Datei auf und misst den Pegel."""

    def __init__(self, kind, device, path):
        super().__init__(daemon=True)
        self.kind, self.device, self.path = kind, device, path
        self.stop_evt, self.t0, self.level, self.error, self.frames = threading.Event(), None, -90.0, "", 0

    def run(self):
        keep = threading.Event()
        try:
            sc = recorder._audio()
            if self.kind == "sys":
                spk = sc.default_speaker()
                mic = recorder.loopback_for(sc, spk)
                if paths.IS_WIN:              # WASAPI-Loopback braucht bei Stille einen stummen Spieler
                    threading.Thread(target=recorder.Recorder._silence_player, args=(sc, spk.id, RATE, keep), daemon=True).start()
            else:
                mic = sc.get_microphone(self.device, include_loopback=False) if self.device else sc.default_microphone()
            with mic.recorder(samplerate=RATE, channels=2, blocksize=1024) as rec, wave.open(self.path, "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(RATE)
                while not self.stop_evt.is_set():
                    d = rec.record(numframes=1024)
                    if not len(d):
                        continue
                    d = np.ascontiguousarray(d, dtype="float32")
                    if d.ndim == 1:
                        d = np.stack([d, d], axis=1)
                    elif d.shape[1] == 1:
                        d = np.repeat(d, 2, axis=1)
                    elif d.shape[1] > 2:
                        d = d[:, :2]
                    if self.t0 is None:
                        self.t0 = time.time() - len(d) / RATE
                    pk = float(np.abs(d).max()) if len(d) else 0.0
                    self.level = max(self.level - 1.5, 20 * np.log10(pk + 1e-6))
                    w.writeframes((np.clip(d, -1, 1) * 32767).astype("<i2").tobytes())
                    self.frames += len(d)
        except Exception as e:
            self.error = str(e)[:200]
            paths.log.warning("Bildschirmaufnahme Ton (%s): %s", self.kind, e)
        finally:
            keep.set()


# ---------------------------------------------------------------- Aufnahme
class _Segment:
    def __init__(self, folder, n):
        self.folder, self.n = folder, n
        self.video = os.path.join(folder, f"teil{n:02d}.mkv")
        self.proc, self.t_video, self.audio, self.started, self.duration = None, None, [], 0.0, 0.0


class ScreenRec:
    def __init__(self):
        self.state, self.opts, self.segs, self.seg, self.folder = "idle", {}, [], None, ""
        self.error, self.result, self.lock, self.progress = "", None, threading.Lock(), 0.0

    # --- Steuerung
    def start(self, opts):
        with self.lock:
            if self.state in ("recording", "paused", "finishing"):
                raise RuntimeError("Es läuft schon eine Aufnahme.")
            if not paths.ffmpeg():
                raise RuntimeError("ffmpeg fehlt – ohne ffmpeg ist keine Bildschirmaufnahme möglich.")
            src = _find(opts["source"])
            self.opts = dict(opts, src=src)
            self.folder = os.path.join(paths.temp_dir(), "bildschirm_" + time.strftime("%Y%m%d_%H%M%S"))
            os.makedirs(self.folder, exist_ok=True)
            self.segs, self.error, self.result, self.progress = [], "", None, 0.0
            self._begin()
            self.state = "recording"
            return self.status()

    def pause(self):
        with self.lock:
            if self.state == "recording":
                self._end()
                self.state = "paused"
            return self.status()

    def resume(self):
        with self.lock:
            if self.state == "paused":
                self._begin()
                self.state = "recording"
            return self.status()

    def stop(self):
        with self.lock:
            if self.state not in ("recording", "paused"):
                return self.status()
            if self.state == "recording":
                self._end()
            self.state = "finishing"
        threading.Thread(target=self._finish, daemon=True).start()
        return self.status()

    def discard(self):
        with self.lock:
            if self.state == "recording":
                self._end()
            self.state = "idle"
        shutil.rmtree(self.folder, ignore_errors=True)
        return self.status()

    def status(self):
        segs = self.segs + ([self.seg] if self.seg else [])
        elapsed = sum(s.duration for s in self.segs) + (time.time() - self.seg.started if self.seg else 0)
        size = 0
        for s in segs:
            for f in [s.video] + [a.path for a in s.audio]:
                try:
                    size += os.path.getsize(f)
                except OSError:
                    pass
        lv = {}
        if self.seg:
            for a in self.seg.audio:
                lv[a.kind] = round(float(a.level), 1)
                if a.error:
                    lv[a.kind + "_error"] = a.error
        return {"state": self.state, "elapsed": round(elapsed, 1), "size": size, "levels": lv, "error": self.error,
                "result": self.result, "progress": round(self.progress, 2),
                "source": (self.opts.get("src") or {}).get("title") or (self.opts.get("src") or {}).get("name") or ""}

    def wait(self, timeout=120):
        """Wartet, bis das Fertigstellen durch ist."""
        end = time.time() + timeout
        while self.state == "finishing" and time.time() < end:
            time.sleep(0.2)

    def shutdown(self):
        """Beim Beenden des Programms: laufende Aufnahme sichern statt ffmpeg weiterlaufen zu lassen."""
        if self.state in ("recording", "paused"):
            try:
                self.stop()
            except Exception as e:
                paths.log.warning("Bildschirmaufnahme beim Beenden: %s", e)
        self.wait(120)

    # --- Abschnitte
    def _begin(self, by_title=False):
        o = self.opts
        seg = _Segment(self.folder, len(self.segs) + 1)
        if o.get("sys_audio"):
            seg.audio.append(_Audio("sys", "", os.path.join(self.folder, f"teil{seg.n:02d}_pc.wav")))
        if o.get("mic"):
            seg.audio.append(_Audio("mic", o.get("mic_device") or "", os.path.join(self.folder, f"teil{seg.n:02d}_mikro.wav")))
        for a in seg.audio:
            a.start()
        crf = QUALITY.get(o.get("quality") or "normal", 25)
        fps = int(o.get("fps") or 30)
        # ohne -nostdin: ffmpeg wird mit „q“ über die Eingabe sauber beendet (Datei bleibt vollständig)
        args = [paths.ffmpeg(), "-hide_banner", "-loglevel", "info", "-thread_queue_size", "512"] + \
               _video_input(o["src"], fps, o.get("cursor", True), by_title) + \
               ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-g", str(fps * 2), "-y", seg.video]
        seg.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    creationflags=paths.CREATE_NO_WINDOW)
        seg.log = []
        ready = threading.Event()

        def watch():
            for raw in seg.proc.stderr:
                line = raw.decode("utf-8", "replace")
                seg.log.append(line)
                del seg.log[:-40]
                if seg.t_video is None and ("Press [q]" in line or "frame=" in line):
                    seg.t_video = time.time()
                    ready.set()
            ready.set()
        threading.Thread(target=watch, daemon=True).start()
        ready.wait(15)
        if seg.proc.poll() is not None and seg.t_video is None:
            for a in seg.audio:
                a.stop_evt.set()
            if paths.IS_WIN and o["src"]["id"].startswith("win:") and not by_title:
                for a in seg.audio:
                    a.join(3)
                return self._begin(by_title=True)
            msg = next((x.strip() for x in reversed(seg.log) if x.strip()), "unbekannter Fehler")
            raise RuntimeError("Bildaufnahme startet nicht: " + msg[:200])
        seg.started = time.time()
        self.seg = seg

    def _end(self):
        seg, self.seg = self.seg, None
        if not seg:
            return
        try:
            seg.proc.stdin.write(b"q")
            seg.proc.stdin.flush()
        except Exception:
            pass
        try:
            seg.proc.wait(20)
        except subprocess.TimeoutExpired:
            seg.proc.kill()
        for a in seg.audio:
            a.stop_evt.set()
        for a in seg.audio:
            a.join(5)
        seg.duration = time.time() - seg.started
        self.segs.append(seg)

    # --- Zusammenfügen
    def _mux(self, seg, out):
        ff = paths.ffmpeg()
        args, filt, labels = [ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", seg.video], [], []
        for i, a in enumerate([a for a in seg.audio if a.t0 and a.frames > 0], 1):
            args += ["-i", a.path]
            d = (seg.t_video or a.t0) - a.t0                          # >0: Ton begann früher als das Bild
            filt.append(f"[{i}:a]atrim=start={d:.3f},asetpts=PTS-STARTPTS[a{i}]" if d >= 0 else
                        f"[{i}:a]adelay={int(-d * 1000)}|{int(-d * 1000)}[a{i}]")
            labels.append(f"[a{i}]")
        if labels:
            if len(labels) > 1:
                filt.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0[aout]")
                amap = "[aout]"
            else:
                amap = labels[0]
            args += ["-filter_complex", ";".join(filt), "-map", "0:v", "-map", amap, "-c:a", "aac", "-b:a", "160k", "-shortest"]
        else:
            args += ["-map", "0:v"]
        args += ["-c:v", "copy", "-movflags", "+faststart", "-y", out]
        r = paths.run(args, timeout=3600)
        if r.returncode != 0:
            raise RuntimeError("Zusammenfügen fehlgeschlagen: " + r.stderr.decode("utf-8", "replace").strip()[-300:])

    def _finish(self):
        try:
            o = self.opts
            parts = []
            for i, seg in enumerate(self.segs, 1):
                self.progress = (i - 1) / (len(self.segs) + 1)
                if not os.path.exists(seg.video) or os.path.getsize(seg.video) < 1000:
                    continue
                p = os.path.join(self.folder, f"teil{seg.n:02d}.mp4")
                self._mux(seg, p)
                parts.append(p)
            if not parts:
                raise RuntimeError("Es wurde nichts aufgenommen.")
            folder = os.path.join(paths.ensure_output(paths.settings()["output_dir"]), "Bildschirmaufnahmen")
            os.makedirs(folder, exist_ok=True)
            src = o["src"]
            label = src.get("title") or src.get("name") or "Bildschirm"
            label = paths.clean(re.sub(r"\s+", " ", label))[:60].strip() or "Bildschirm"
            dst = paths.unique(os.path.join(folder, time.strftime("%Y-%m-%d %H-%M ") + label + ".mp4"))
            if len(parts) == 1:
                shutil.move(parts[0], dst)
            else:
                lst = os.path.join(self.folder, "liste.txt")
                with open(lst, "w", encoding="utf-8") as f:
                    for p in parts:
                        f.write("file '" + p.replace("'", "'\\''") + "'\n")
                r = paths.run([paths.ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "concat", "-safe", "0",
                               "-i", lst, "-c", "copy", "-movflags", "+faststart", "-y", dst], timeout=3600)
                if r.returncode != 0:
                    raise RuntimeError("Abschnitte zusammenfügen fehlgeschlagen: " + r.stderr.decode("utf-8", "replace")[-300:])
            res = {"mp4": dst, "mp3": "", "duration": round(sum(s.duration for s in self.segs), 1),
                   "size": os.path.getsize(dst), "has_audio": any(a.frames for s in self.segs for a in s.audio)}
            if o.get("mp3") and res["has_audio"]:
                self.progress = .95
                mp3 = os.path.splitext(dst)[0] + ".mp3"
                r = paths.run([paths.ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", dst, "-vn",
                               "-c:a", "libmp3lame", "-q:a", "2", "-y", mp3], timeout=3600)
                if r.returncode == 0:
                    res["mp3"] = mp3
            self.result, self.state, self.progress = res, "done", 1.0
            shutil.rmtree(self.folder, ignore_errors=True)
        except Exception as e:
            paths.log.exception("Bildschirmaufnahme")
            self.error, self.state = str(e), "error"
