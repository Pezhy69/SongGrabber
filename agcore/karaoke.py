"""Karaoke: Karaoke-Videos von YouTube suchen, werbefrei abspielen und als Favoriten offline speichern.

Abspielen: yt-dlp ermittelt die Bild- und Tonadresse, ffmpeg setzt beides ohne Umrechnen zu einem
fortlaufenden MP4 zusammen, das der eingebaute Medienserver an die Oberfläche weiterreicht.
Favoriten werden als MP4 (bis 720p) im Musik-Ordner unter „Karaoke“ gespeichert – dann geht's auch ohne Internet.
"""
import glob
import json
import os
import re
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


def _score(s):
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
    if d and (d < 60 or d > 900):
        sc -= 5
    return sc


def search(query, limit=30):
    """Karaoke-Videos zu einem Titel/Interpreten – Karaoke-Kanäle zuerst, Musikvideos ohne Text aussortiert."""
    q = (query or "").strip()
    if not q:
        return []
    if "karaoke" not in q.lower():
        q += " karaoke"
    info = _run_json([f"ytsearch{int(limit)}:{q}"])
    out = [_song(e) for e in info.get("entries") or [] if e and e.get("id")]
    for s in out:
        s["score"] = _score(s)
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


# ---------------------------------------------------------------- Favoriten & Offline
class Karaoke:
    def __init__(self, media, jobs):
        self.media, self.jobs = media, jobs
        self.path = os.path.join(paths.data_dir(), "karaoke.json")
        self.lock = threading.Lock()
        self.data = {"favorites": [], "singers": [], "queue": []}
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass
        self.dl = {}                  # id → {progress, error}
        self.cache = {}               # id → (zeit, video, audio, headers)
        media.handlers["kv"] = self._stream

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
                    "folder": self.folder(), "starters": [{"name": n, "query": q} for n, q in STARTERS]}

    def save_queue(self, q, singers=None):
        with self.lock:
            self.data["queue"] = list(q or [])[:200]
            if singers is not None:
                self.data["singers"] = [s for s in dict.fromkeys(singers) if s][:30]
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
            args = [links._ytdlp(), "-f", "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b",
                    "--merge-output-format", "mp4", "--no-playlist", "--newline", "--no-warnings", "--no-part",
                    "--write-thumbnail", "--convert-thumbnails", "jpg", "-o", base + ".%(ext)s",
                    "--progress-template", "download:AG %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s"]
            ff = paths.ffmpeg()
            if ff:
                args += ["--ffmpeg-location", os.path.dirname(ff)]
            proc = paths.popen(args + ["https://www.youtube.com/watch?v=" + vid], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            last, part, parts = [], 0, 2
            for raw in proc.stdout:
                if job.cancel.is_set():
                    proc.kill()
                    raise encoder.Cancelled()
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("AG "):
                    p = line.split()
                    try:
                        done = float(p[1])
                        tot = float(p[2]) if p[2] not in ("NA", "None") else float(p[3])
                        pr = min(.98, (part + done / tot) / parts)
                        if done >= tot:
                            part = min(parts - 1, part + 1)
                        self.dl[vid]["progress"] = pr
                        job.set(pr, f"Lädt … {done / 1048576:.1f} MB")
                    except (ValueError, ZeroDivisionError, IndexError, KeyError):
                        pass
                elif line:
                    last = (last + [line])[-4:]
            proc.wait()
            files = [p for p in glob.glob(glob.escape(base) + ".*") if p.lower().endswith((".mp4", ".mkv", ".webm"))]
            if proc.returncode != 0 or not files:
                err = [l for l in last if "ERROR" in l] or last
                raise RuntimeError((err[-1] if err else "Download fehlgeschlagen").replace("ERROR: ", ""))
            thumb = next(iter(glob.glob(glob.escape(base) + ".jpg")), "")
            with self.lock:
                for x in self.data["favorites"]:
                    if x["id"] == vid:
                        x["file"], x["thumb_file"] = files[0], thumb
                self._save()
                self.dl.pop(vid, None)
            job.outputs.append(files[0])
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
