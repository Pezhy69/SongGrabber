"""Karaoke: Karaoke-Videos von YouTube suchen, werbefrei abspielen und als Favoriten offline speichern.

Abspielen: yt-dlp ermittelt die Bild- und Tonadresse, ffmpeg setzt beides ohne Umrechnen zu einem
fortlaufenden MP4 zusammen, das der eingebaute Medienserver an die Oberfläche weiterreicht.
Favoriten werden als MP4 (bis 720p) im Musik-Ordner unter „Karaoke“ gespeichert – dann geht's auch ohne Internet.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse

from . import encoder, links, paths

# Bekannte Karaoke-Kanäle kommen in der Suche nach oben
CHANNELS = ("sing king", "karafun", "zoom karaoke", "karaoke version", "singsong", "party tyme", "stingray karaoke",
            "karaoke hits", "songjam", "atomic karaoke", "karaoke deutsch", "deutsche karaoke", "kb karaoke",
            "lugn karaoke", "singer's edge", "musisi karaoke", "sing2music", "karaokey", "the karaoke channel")
GOOD = re.compile(r"karaoke|instrumental with lyrics|sing ?along|mitsing", re.I)
BAD = re.compile(r"reaction|tutorial|how to sing|live|cover by|vocal coach|react|lesson|gesangsunterricht", re.I)

# Fertige Playlists zum Losstarten (YouTube-Suchen nach Playlists)
STARTERS = [
    ("Party-Hits", "party hits karaoke playlist"), ("Schlager", "schlager karaoke playlist"),
    ("Deutsche Hits", "deutsche hits karaoke playlist"), ("80er", "80s karaoke playlist"),
    ("90er", "90s karaoke playlist"), ("2000er", "2000s karaoke playlist"), ("Rock-Klassiker", "rock classics karaoke playlist"),
    ("Pop aktuell", "pop hits karaoke playlist 2026"), ("Disney", "disney karaoke playlist"),
    ("Kinderlieder", "kinderlieder karaoke playlist"), ("Balladen", "ballads karaoke playlist"),
    ("Weihnachten", "christmas karaoke playlist"),
]


def _run_json(args, timeout=90):
    r = paths.run([links._ytdlp(), "-J", "--flat-playlist", "--no-warnings"] + args, timeout=timeout)
    if r.returncode != 0 or not r.stdout:
        msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError((msg[-1] if msg else "Keine Antwort von YouTube – Internetverbindung prüfen.").replace("ERROR: ", ""))
    return json.loads(r.stdout.decode("utf-8", "replace"))


def _thumb(e):
    if e.get("id") and (e.get("ie_key") or "").lower() in ("youtube", "") and len(str(e["id"])) == 11:
        return f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg"
    th = e.get("thumbnails") or []
    return th[-1]["url"] if th and th[-1].get("url") else ""


def _song(e):
    return {"id": e["id"], "title": (e.get("title") or "").strip(), "channel": e.get("channel") or e.get("uploader") or "",
            "duration": int(e.get("duration") or 0), "thumb": _thumb(e)}


LONG = re.compile(r"best of|mix|medley|non ?stop|compilation|playlist|hits|1 ?(std|stunde|hour)|vol\.? ?\d", re.I)


def _score(s, long=False):
    t, ch = s["title"].lower(), s["channel"].lower()
    sc = 0
    if any(c in ch for c in CHANNELS):
        sc += 4
    if GOOD.search(t):
        sc += 3
    if "karaoke" in ch:
        sc += 2
    if BAD.search(t):
        sc -= 4
    d = s["duration"]
    if long:                                    # Best-of/Mixe: je länger, desto besser
        sc += 4 if d >= 1200 else (-2 if d and d < 600 else 0)
        sc += 2 if LONG.search(t) else 0
    elif d and (d < 60 or d > 900):
        sc -= 5
    return sc


def search(query, limit=30, long=False):
    """Karaoke-Videos zu einem Titel/Interpreten – Karaoke-Kanäle zuerst, Musikvideos ohne Text aussortiert.
    long=True: Best-of-/Mix-Videos (oft 1 Stunde und mehr, mit Songliste)."""
    q = (query or "").strip()
    if not q:
        return []
    if "karaoke" not in q.lower():
        q += " karaoke"
    if long and not LONG.search(q):
        q += " best of mix"
    info = _run_json([f"ytsearch{int(limit)}:{q}"])
    out = [_song(e) for e in info.get("entries") or [] if e and e.get("id")]
    for s in out:
        s["score"] = _score(s, long)
    keep = [s for s in out if s["score"] > 0] or out
    keep.sort(key=lambda s: -s["score"])
    return keep


def playlists(query):
    """YouTube-Playlists zu einer Suche (z. B. „schlager karaoke playlist“)."""
    q = (query or "").strip()
    if "karaoke" not in q.lower():
        q += " karaoke"
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q) + "&sp=EgIQAw%3D%3D"
    info = _run_json([url, "--playlist-end", "20"])
    out = []
    for e in info.get("entries") or []:
        if not e:
            continue
        pid = e.get("id") or ""
        u = e.get("url") or ""
        if not u.startswith("http"):
            u = "https://www.youtube.com/playlist?list=" + pid
        if "list=" not in u:
            continue
        out.append({"url": u, "title": e.get("title") or "Playlist", "channel": e.get("channel") or e.get("uploader") or "",
                    "count": e.get("playlist_count") or e.get("n_entries") or 0, "thumb": _thumb(e)})
    return out


def playlist_items(url):
    info = _run_json([url], timeout=120)
    return [_song(e) for e in info.get("entries") or [] if e and e.get("id")]


FORMAT = "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b"


def fetch(vid, base, progress=None, cancel=None):
    """Video mit yt-dlp nach base.mp4 (+ base.jpg) holen. progress(0..1). Gibt den Dateipfad zurück."""
    args = [links._ytdlp(), "-f", FORMAT, "--merge-output-format", "mp4", "--no-playlist", "--newline", "--no-warnings",
            "--no-part", "--write-thumbnail", "--convert-thumbnails", "jpg", "--write-info-json", "-o", base + ".%(ext)s",
            "--progress-template", "download:AG %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s"]
    ff = paths.ffmpeg()
    if ff:
        args += ["--ffmpeg-location", os.path.dirname(ff)]
    proc = paths.popen(args + ["https://www.youtube.com/watch?v=" + vid], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    last, part, parts = [], 0, 2
    for raw in proc.stdout:
        if cancel is not None and cancel():
            proc.kill()
            raise encoder.Cancelled()
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("AG "):
            p = line.split()
            try:
                done = float(p[1])
                tot = float(p[2]) if p[2] not in ("NA", "None") else float(p[3])
                if progress:
                    progress(min(.98, (part + done / tot) / parts), done)
                if done >= tot:
                    part = min(parts - 1, part + 1)
            except (ValueError, ZeroDivisionError, IndexError):
                pass
        elif line:
            last = (last + [line])[-6:]
    proc.wait()
    files = [p for p in glob.glob(glob.escape(base) + ".*") if p.lower().endswith((".mp4", ".mkv", ".webm"))]
    if proc.returncode != 0 or not files:
        paths.log.warning("Karaoke-Download %s fehlgeschlagen:\n  %s", vid, "\n  ".join(last))
        err = [l for l in last if "ERROR" in l] or last
        raise RuntimeError((err[-1] if err else "Download fehlgeschlagen").replace("ERROR: ", "")[:200])
    return files[0]


def chapters(video):
    """Songliste (Kapitel) eines Videos aus der mitgespeicherten .info.json."""
    for j in (os.path.splitext(video)[0] + ".info.json",):
        try:
            with open(j, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        out = [{"start": float(c.get("start_time") or 0), "end": float(c.get("end_time") or 0), "title": (c.get("title") or "").strip()}
               for c in info.get("chapters") or []]
        return [c for c in out if c["end"] > c["start"]]
    return []


# ---------------------------------------------------------------- Favoriten & Offline
class Karaoke:
    def __init__(self, media, jobs):
        self.media, self.jobs = media, jobs
        self.path = os.path.join(paths.data_dir(), "karaoke.json")
        self.lock = threading.Lock()
        self.data = {"favorites": [], "singers": [], "queue": [], "history": []}
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass
        self.dl = {}                  # id → {progress, error}
        self.cache = {}               # id → (zeit, video, audio, headers)
        self.prep = {}                # id → {progress, file, error}  (vorgeladene Songs zum Abspielen)
        self.cdir = os.path.join(paths.temp_dir(), "karaoke")
        os.makedirs(self.cdir, exist_ok=True)
        self._tidy()
        media.handlers["kv"] = self._stream

    def _tidy(self):
        """Zwischenspeicher klein halten: höchstens 25 Songs und nichts älter als 3 Tage."""
        try:
            fs = sorted((os.path.join(self.cdir, f) for f in os.listdir(self.cdir)), key=os.path.getmtime, reverse=True)
            for i, f in enumerate(fs):
                if i >= 50 or time.time() - os.path.getmtime(f) > 3 * 86400:
                    os.remove(f)
        except OSError:
            pass

    # --- Abspielen: Song vorladen (zuverlässiger als direkt streamen, Spulen geht, der nächste lädt schon im Hintergrund)
    def prepare(self, song):
        vid = song["id"]
        f = next((x for x in self.data["favorites"] if x["id"] == vid), None)
        if f and f.get("file") and os.path.isfile(f["file"]):
            return {"ready": True, "src": self.media.url(f["file"]), "offline": True, "file": f["file"], "chapters": chapters(f["file"])}
        cached = os.path.join(self.cdir, vid + ".mp4")
        if os.path.isfile(cached) and vid not in self.prep:
            return {"ready": True, "src": self.media.url(cached), "offline": False, "file": cached, "chapters": chapters(cached)}
        st = self.prep.get(vid)
        if st is None or st.get("error"):
            st = self.prep[vid] = {"progress": 0.0, "file": "", "error": "", "mb": 0}

            def run():
                try:
                    def prog(p, done):
                        st["progress"], st["mb"] = p, round(done / 1048576, 1)
                    st["file"] = fetch(vid, os.path.join(self.cdir, vid), prog)
                    st["progress"] = 1.0
                except Exception as e:
                    st["error"] = str(e) or "Download fehlgeschlagen"
                finally:
                    if st.get("file"):
                        self.prep.pop(vid, None)
            threading.Thread(target=run, daemon=True).start()
        if st.get("file"):
            return {"ready": True, "src": self.media.url(st["file"]), "offline": False, "file": st["file"], "chapters": chapters(st["file"])}
        return {"ready": False, "progress": round(st["progress"], 3), "mb": st.get("mb", 0), "error": st.get("error", "")}

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def folder(self):
        return os.path.join(paths.ensure_output(paths.settings()["output_dir"]), "Karaoke")

    # --- Zustand für die Oberfläche
    def state(self):
        with self.lock:
            favs = []
            for f in self.data["favorites"]:
                f = dict(f)
                ok = bool(f.get("file")) and os.path.isfile(f["file"])
                f["offline"] = ok
                if f.get("file") and not ok:
                    f["file"] = ""
                d = self.dl.get(f["id"])
                f["loading"] = round(d["progress"], 3) if d and not d.get("error") else None
                f["error"] = d.get("error", "") if d else ""
                if ok and f.get("thumb_file") and os.path.isfile(f["thumb_file"]):
                    f["thumb"] = self.media.url(f["thumb_file"])
                favs.append(f)
            return {"favorites": favs, "singers": self.data.get("singers", []), "queue": self.data.get("queue", []),
                    "history": self.data.get("history", [])[:300],
                    "folder": self.folder(), "starters": [{"name": n, "query": q} for n, q in STARTERS]}

    # --- für die Party (Handy-Seite)
    def party_thumb(self, vid):
        with self.lock:
            for f in self.data["favorites"]:
                if f.get("id") == vid and f.get("thumb_file") and os.path.isfile(f["thumb_file"]):
                    return f["thumb_file"]
        return None

    def party_favorites(self):
        with self.lock:
            return [dict(f, file=f.get("file") if f.get("file") and os.path.isfile(f["file"]) else "") for f in self.data["favorites"]]

    def save_queue(self, q, singers=None):
        with self.lock:
            self.data["queue"] = list(q or [])[:200]
            if singers is not None:
                self.data["singers"] = [s for s in dict.fromkeys(singers) if s][:30]
            self._save()
        return True

    # --- Verlauf: was wurde gesungen (mit Punkten, falls gewertet)
    def history_add(self, entry):
        song = entry.get("song") or {}
        if not song.get("id"):
            return False
        e = {"song": {k: song.get(k) for k in ("id", "title", "channel", "duration", "thumb")},
             "singer": (entry.get("singer") or "").strip()[:60], "at": int(time.time())}
        if entry.get("score") is not None:
            e["score"] = int(entry["score"])
        with self.lock:
            h = self.data.setdefault("history", [])
            h.insert(0, e)
            del h[500:]
            self._save()
        return True

    def history_clear(self):
        with self.lock:
            self.data["history"] = []
            self._save()
        return True

    # --- Favoriten
    def favorite(self, song, on=True, offline=True):
        with self.lock:
            favs = self.data["favorites"]
            have = next((f for f in favs if f["id"] == song["id"]), None)
            if on and not have:
                favs.insert(0, {k: song.get(k) for k in ("id", "title", "channel", "duration", "thumb")} | {"added": int(time.time()), "file": ""})
            elif not on and have:
                favs.remove(have)
            self._save()
        if on and offline:
            self.download(song["id"])
        return self.state()

    def remove(self, vid, delete_file=False):
        with self.lock:
            f = next((x for x in self.data["favorites"] if x["id"] == vid), None)
            if f:
                self.data["favorites"].remove(f)
                if delete_file:
                    for p in (f.get("file"), f.get("thumb_file")):
                        try:
                            if p:
                                os.remove(p)
                        except OSError:
                            pass
                self._save()
        return self.state()

    def download(self, vid):
        """Favorit offline speichern (läuft in der Warteschlange)."""
        with self.lock:
            f = next((x for x in self.data["favorites"] if x["id"] == vid), None)
            if not f or (f.get("file") and os.path.isfile(f["file"])) or (vid in self.dl and not self.dl[vid].get("error")):
                return False
            self.dl[vid] = {"progress": 0.0}
            title = f["title"]

        def run(job):
            folder = self.folder()
            os.makedirs(folder, exist_ok=True)
            name = paths.clean(re.sub(r"\s+", " ", re.sub(r"[^\w\s\-.,()&'!]", " ", title)).strip())[:90] or vid
            base = os.path.join(folder, name)
            cached = os.path.join(self.cdir, vid + ".mp4")
            if os.path.isfile(cached):                      # gerade gesungen → nur noch umkopieren
                import shutil
                file = paths.unique(base + ".mp4")
                shutil.copy2(cached, file)
                for ext in (".jpg", ".info.json"):
                    if os.path.isfile(os.path.join(self.cdir, vid + ext)):
                        shutil.copy2(os.path.join(self.cdir, vid + ext), os.path.splitext(file)[0] + ext)
            else:
                def prog(p, done):
                    self.dl[vid]["progress"] = p
                    job.set(p, f"Lädt … {done / 1048576:.1f} MB")
                file = fetch(vid, base, prog, job.cancel.is_set)
            thumb = os.path.splitext(file)[0] + ".jpg"
            with self.lock:
                for x in self.data["favorites"]:
                    if x["id"] == vid:
                        x["file"], x["thumb_file"] = file, thumb if os.path.isfile(thumb) else ""
                self._save()
                self.dl.pop(vid, None)
            job.outputs.append(file)
            job.set(1.0, "Offline gespeichert")

        def wrap(job):
            try:
                run(job)
            except Exception as e:
                self.dl[vid] = {"progress": 0, "error": str(e)[:200]}
                raise
        self.jobs.add("karaoke", "Karaoke: " + title, wrap, "für unterwegs speichern")
        return True

    def download_all(self):
        n = 0
        for f in list(self.data["favorites"]):
            n += bool(self.download(f["id"]))
        return n

    # --- Abspielen
    def play_url(self, song):
        """Adresse zum Abspielen: offline gespeicherte Datei, sonst Live-Strom über den Medienserver."""
        f = next((x for x in self.data["favorites"] if x["id"] == song["id"]), None)
        if f and f.get("file") and os.path.isfile(f["file"]):
            return {"src": self.media.url(f["file"]), "offline": True}
        return {"src": self.media.route("kv", song["id"]), "offline": False}

    def _resolve(self, vid):
        c = self.cache.get(vid)
        if c and time.time() - c[0] < 1800:
            return c[1:]
        r = paths.run([links._ytdlp(), "-J", "--no-playlist", "--no-warnings", "-f",
                       "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b",
                       "https://www.youtube.com/watch?v=" + vid], timeout=60)
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("Video nicht abspielbar")
        info = json.loads(r.stdout.decode("utf-8", "replace"))
        req = info.get("requested_formats") or [info]
        v = req[0]
        a = req[1] if len(req) > 1 else None
        hdr = v.get("http_headers") or info.get("http_headers") or {}
        res = (v["url"], a["url"] if a else "", hdr)
        self.cache[vid] = (time.time(),) + res
        return res

    def _stream(self, h, vid):
        if not re.fullmatch(r"[\w-]{6,20}", vid or ""):
            h.send_error(404)
            return
        try:
            vurl, aurl, hdr = self._resolve(vid)
        except Exception as e:
            paths.log.warning("Karaoke %s: %s", vid, e)
            h.send_error(502)
            return
        hs = "".join(f"{k}: {v}\r\n" for k, v in hdr.items())
        args = [paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-reconnect", "1", "-reconnect_streamed", "1"]
        args += (["-headers", hs] if hs else []) + ["-i", vurl]
        if aurl:
            args += ["-reconnect", "1", "-reconnect_streamed", "1"] + (["-headers", hs] if hs else []) + ["-i", aurl, "-map", "0:v:0", "-map", "1:a:0"]
        args += ["-c", "copy", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "pipe:1"]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                creationflags=paths.CREATE_NO_WINDOW)
        try:
            h.send_response(200)
            h.send_header("Content-Type", "video/mp4")
            h.send_header("Cache-Control", "no-store")
            h.send_header("Access-Control-Allow-Origin", "*")
            h.end_headers()
            if h.command == "HEAD":
                return
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                h.wfile.write(chunk)
        except (ConnectionError, BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------- Sich selbst aufnehmen (Stimme + Musik)
# Hall auf der Stimme: eigener „nasser“ Zweig (nur Echos, ohne Höhen/Tiefen) wird zur trockenen Stimme gemischt.
# Viele dichte, leise Echos klingen weich – wenige laute knacken bei Konsonanten.
HALL = {
    "off": None,
    "room": ("23|37|53|71|89", "0.42|0.36|0.30|0.24|0.18", 0.30),
    "stage": ("41|67|97|131|167|211", "0.44|0.38|0.32|0.26|0.20|0.14", 0.34),
    "hall": ("61|97|139|181|229|283|347|419", "0.42|0.37|0.32|0.27|0.22|0.17|0.12|0.08", 0.36),
}


class KaraRec:
    """Nimmt während des Singens den Ton vom PC (die Karaoke-Musik) und das Mikrofon auf und mischt beides
    zu einer MP3 – auf Wunsch zusätzlich als MP4 mit dem Karaoke-Video."""

    def __init__(self):
        self.cur, self.done, self.lock = None, {}, threading.Lock()
        self.base = os.path.join(paths.temp_dir(), "karaoke_rec")
        os.makedirs(self.base, exist_ok=True)

    def start(self, meta):
        from .screenrec import _Audio
        with self.lock:
            if self.cur:
                self._stop_threads(self.cur)
            rid = time.strftime("%Y%m%d_%H%M%S")
            folder = os.path.join(self.base, rid)
            os.makedirs(folder, exist_ok=True)
            mic_dev = (paths.settings().get("screen_opts") or {}).get("mic_device") or ""
            r = dict(meta, id=rid, folder=folder, t_start=time.time(), dirty=False, hall=meta.get("hall") if meta.get("hall") in HALL else "stage",
                     sys=_Audio("sys", "", os.path.join(folder, "musik.wav")),
                     mic=_Audio("mic", mic_dev, os.path.join(folder, "stimme.wav")))
            r["sys"].start()
            r["mic"].start()
            self.cur = r
            return {"id": rid}

    def dirty(self):
        if self.cur:
            self.cur["dirty"] = True
        return True

    def status(self):
        r = self.cur
        if not r:
            return {"on": False}
        return {"on": True, "elapsed": round(time.time() - r["t_start"], 1), "mic": round(float(r["mic"].level), 1),
                "mic_error": r["mic"].error, "sys_error": r["sys"].error}

    @staticmethod
    def _stop_threads(r):
        for a in (r["sys"], r["mic"]):
            a.stop_evt.set()
        for a in (r["sys"], r["mic"]):
            a.join(5)

    def stop(self, keep=True):
        with self.lock:
            r, self.cur = self.cur, None
        if not r:
            return None
        self._stop_threads(r)
        if not keep or (time.time() - r["t_start"]) < 8 or not (r["sys"].frames or r["mic"].frames):
            shutil.rmtree(r["folder"], ignore_errors=True)
            return None
        r["voice"] = 0.0
        r["duration"] = round(time.time() - r["t_start"], 1)
        self.done[r["id"]] = r
        try:
            return self._render(r)
        except Exception as e:
            paths.log.exception("Karaoke-Aufnahme")
            return {"id": r["id"], "error": str(e)[:200]}

    def remix(self, rid, voice_db=None, hall=None):
        r = self.done.get(rid)
        if not r:
            raise RuntimeError("Diese Aufnahme kann nicht mehr angepasst werden.")
        if voice_db is not None:
            r["voice"] = max(-12.0, min(15.0, float(voice_db)))
        if hall in HALL:
            r["hall"] = hall
        return self._render(r)

    def delete(self, rid):
        r = self.done.pop(rid, None)
        if r:
            for k in ("mp3", "mp4"):
                try:
                    if r.get(k):
                        os.remove(r[k])
                except OSError:
                    pass
            shutil.rmtree(r["folder"], ignore_errors=True)
        return True

    def _render(self, r):
        ff = paths.ffmpeg()
        sysw, micw = r["sys"], r["mic"]
        out_dir = os.path.join(paths.ensure_output(paths.settings()["output_dir"]), "Karaoke-Aufnahmen")
        os.makedirs(out_dir, exist_ok=True)
        if not r.get("name"):
            who = (r.get("singer") or "").strip()
            title = re.sub(r"\((karaoke|official|hd|lyrics)[^)]*\)|\[[^\]]*\]|karaoke version|karaoke", "", r.get("title") or "", flags=re.I)
            label = paths.clean(re.sub(r"\s+", " ", re.sub(r"[^\w\s\-–.,()&'!]", " ", (who + " – " if who else "") + title)).strip(" -–"))[:90]
            r["name"] = paths.unique(os.path.join(out_dir, time.strftime("%Y-%m-%d %H-%M ") + (label or "Karaoke") + ".mp3"))[:-4]
        mp3 = r["name"] + ".mp3"
        mix = os.path.join(r["folder"], "mix.wav")
        ins, filt, lab = [], [], []
        t_ref = sysw.t0 or micw.t0 or r["t_start"]
        for i, (a, gain, extra) in enumerate([(sysw, 0.0, ""), (micw, r["voice"], "highpass=f=90,dynaudnorm=f=150:g=15:p=0.9:m=30,acompressor=threshold=-22dB:ratio=3:attack=5:release=150:makeup=3,")]):
            if not (a.t0 and a.frames and os.path.isfile(a.path)):
                continue
            ins += ["-i", a.path]
            d = a.t0 - t_ref                                   # >0: diese Spur begann später
            sync = f"adelay={int(d * 1000)}|{int(d * 1000)}," if d > 0.005 else (f"atrim=start={-d:.3f},asetpts=PTS-STARTPTS," if d < -0.005 else "")
            n = len(lab)
            hall = HALL.get(r.get("hall") or "off") if a is micw else None
            if hall:
                taps, decays, wet = hall
                filt.append(f"[{n}:a]{sync}{extra}aformat=sample_fmts=fltp,asplit=2[d{n}][w{n}]")
                filt.append(f"[w{n}]highpass=f=220,lowpass=f=4200,aecho=0:1:{taps}:{decays},volume={wet}[e{n}]")
                filt.append(f"[d{n}][e{n}]amix=inputs=2:duration=first:normalize=0,volume={gain}dB[a{n}]")
            else:
                filt.append(f"[{n}:a]{sync}{extra}volume={gain}dB[a{n}]")
            lab.append(f"[a{n}]")
        if not lab:
            raise RuntimeError("Es kam kein Ton an – Mikrofon und Ton vom PC prüfen.")
        mixf = ("".join(lab) + f"amix=inputs={len(lab)}:duration=longest:normalize=0," if len(lab) > 1 else lab[0] + "") + "volume=-2dB,alimiter=limit=0.94:attack=4:release=120:level=disabled[out]"
        rr = paths.run([ff, "-hide_banner", "-nostdin", "-loglevel", "error"] + ins +
                       ["-filter_complex", ";".join(filt) + ";" + mixf, "-map", "[out]", "-ar", "48000", "-y", mix], timeout=900)
        if rr.returncode != 0:
            raise RuntimeError("Mischen fehlgeschlagen: " + rr.stderr.decode("utf-8", "replace")[-200:])
        rr = paths.run([ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", mix, "-c:a", "libmp3lame", "-q:a", "2",
                        "-metadata", f"title={r.get('title') or 'Karaoke'}", "-metadata", f"artist={r.get('singer') or 'Karaoke'}",
                        "-metadata", "album=Karaoke-Aufnahmen", "-y", mp3], timeout=900)
        if rr.returncode != 0:
            raise RuntimeError("MP3 fehlgeschlagen: " + rr.stderr.decode("utf-8", "replace")[-200:])
        r["mp3"], note = mp3, ""
        if r.get("mp4") and r.get("video") and os.path.isfile(r["video"]):
            if r["dirty"]:
                note = "Kein Video: Während der Aufnahme wurde pausiert oder gespult."
            else:
                mp4 = r["name"] + ".mp4"
                pos = max(0.0, float(r.get("pos") or 0) + (t_ref - r["t_start"]))
                vin = ["-i", r["video"]] if pos < 0.3 else ["-ss", f"{pos:.3f}", "-i", r["video"]]
                vc = ["-c:v", "copy"] if pos < 0.3 else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"]
                rr = paths.run([ff, "-hide_banner", "-nostdin", "-loglevel", "error"] + vin + ["-i", mix, "-map", "0:v:0", "-map", "1:a:0"]
                               + vc + ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", "-y", mp4], timeout=1800)
                if rr.returncode == 0:
                    r["mp4"] = mp4
                else:
                    note = "Video konnte nicht erstellt werden."
                    paths.log.warning("Karaoke-Video: %s", rr.stderr.decode("utf-8", "replace")[-300:])
        if r.get("mp4") is True:
            r["mp4"] = ""
        return {"id": r["id"], "singer": r.get("singer") or "", "title": r.get("title") or "", "mp3": mp3,
                "mp4": r.get("mp4") or "", "duration": r["duration"], "voice": r["voice"], "hall": r.get("hall") or "off", "note": note,
                "mic_silent": not micw.frames}


# ---------------------------------------------------------------- Punkte (Spaß-Wertung)
def score_wav(path):
    """Bewertet eine Mikrofon-Aufnahme ohne Vergleichsmelodie:
    Treffsicherheit = wie nah die gesungenen Töne an echten Halbtönen liegen (bezogen auf die eigene Stimmung),
    Dabei = wie viel gesungen wurde, Ruhige Töne = wie gleichmäßig gehaltene Töne sind.
    Gibt None zurück, wenn (fast) nichts gesungen wurde."""
    import wave
    import numpy as np
    try:
        with wave.open(path, "rb") as w:
            sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
            x = np.frombuffer(w.readframes(n), dtype="<i2").astype("float32") / 32768.0
    except (OSError, EOFError, wave.Error):
        return None
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    f = max(1, sr // 16000)                                    # auf ~16 kHz verkleinern – reicht für Stimmen
    x = x[: len(x) // f * f].reshape(-1, f).mean(axis=1)
    sr //= f
    N, hop = 1024, 512
    if len(x) < sr * 8:
        return None
    nfr = (len(x) - N) // hop
    fr = np.lib.stride_tricks.as_strided(x, (nfr, N), (x.strides[0] * hop, x.strides[0]))
    fr = fr - fr.mean(axis=1, keepdims=True)
    rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    floor = np.percentile(db, 15)
    loud = db > max(floor + 12, -50)
    # Autokorrelation über FFT, Tonhöhe 80–1000 Hz
    spec = np.fft.rfft(fr * np.hanning(N), 2 * N)
    ac = np.fft.irfft(np.abs(spec) ** 2)[:, :N]
    ac /= ac[:, :1] + 1e-12
    lo, hi = int(sr / 1000), int(sr / 80)
    seg = ac[:, lo:hi]
    lag = seg.argmax(axis=1) + lo
    clar = seg.max(axis=1)
    voiced = loud & (clar > 0.6)
    if voiced.sum() < 40:
        return None
    # Feiner: Parabel um das Maximum
    i = np.clip(lag, 1, N - 2)
    a, b, c = ac[np.arange(nfr), i - 1], ac[np.arange(nfr), i], ac[np.arange(nfr), i + 1]
    den = a - 2 * b + c
    off = np.where(np.abs(den) > 1e-9, 0.5 * (a - c) / den, 0)
    f0 = sr / (i + off)
    cents = 1200 * np.log2(f0[voiced] / 440.0)
    # Eigene Stimmung herausrechnen (Karaoke-Tracks sind nicht immer auf 440 Hz)
    ang = cents / 100 * 2 * np.pi
    tune = np.angle(np.exp(1j * ang).mean()) / (2 * np.pi) * 100
    dev = np.abs(((cents - tune) + 50) % 100 - 50)            # 0 … 50 Cent neben dem nächsten Halbton
    inton = float(np.clip((1 - dev / 50).mean() * 2 - 1, 0, 1)) ** 0.8   # Zufall ≈ 0, perfekt = 1
    steady = np.abs(np.diff(cents)) < 40
    stable = float(steady.mean()) if len(steady) else 0.0
    presence = float(min(1.0, voiced.mean() / 0.45))
    score = 30 + 70 * (0.55 * inton + 0.3 * presence + 0.15 * stable)
    return {"score": int(round(min(100, score))), "inton": round(inton * 100), "presence": round(presence * 100),
            "stable": round(stable * 100)}


class KaraScore:
    """Hört während eines Songs auf das Mikrofon und vergibt am Ende Punkte."""

    def __init__(self):
        self.cur, self.lock = None, threading.Lock()
        self.base = os.path.join(paths.temp_dir(), "karaoke_score")
        os.makedirs(self.base, exist_ok=True)

    def start(self):
        from .screenrec import _Audio
        self.stop(False)
        with self.lock:
            mic_dev = (paths.settings().get("screen_opts") or {}).get("mic_device") or ""
            a = _Audio("mic", mic_dev, os.path.join(self.base, time.strftime("%H%M%S") + ".wav"))
            a.start()
            self.cur = a
        return True

    def stop(self, rate=True):
        with self.lock:
            a, self.cur = self.cur, None
        if not a:
            return None
        a.stop_evt.set()
        a.join(5)
        try:
            res = score_wav(a.path) if rate and a.frames else None
            if rate and a.error:
                res = {"error": a.error}
            return res
        finally:
            try:
                os.remove(a.path)
            except OSError:
                pass
