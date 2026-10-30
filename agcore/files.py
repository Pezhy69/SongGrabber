"""Dateien & DVD: lokale Audio-/Videodateien und DVD-Video (VIDEO_TS) umwandeln."""
import glob
import os
import re
import threading
import time

from . import encoder, paths, pipeline

MEDIA_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".ape",
             ".wv", ".mka", ".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv", ".m4v", ".ts",
             ".mpg", ".mpeg", ".vob", ".3gp", ".ac3", ".dts", ".amr"}


def expand(paths_in):
    out = []
    for p in paths_in:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                out += [os.path.join(root, n) for n in sorted(names)
                        if os.path.splitext(n)[1].lower() in MEDIA_EXT]
        elif os.path.isfile(p):
            out.append(p)
    return out


def describe(path):
    info = encoder.probe(path)
    t = info["tags"]
    name = os.path.splitext(os.path.basename(path))[0]
    artist, title = t.get("artist", ""), t.get("title", "")
    if not title:
        m = re.match(r"^\s*(?:\d{1,3}[\s.\-_]+)?(.+?)\s+[-–]\s+(.+)$", name)
        if m and not artist:
            artist, title = m.group(1), m.group(2)
        else:
            title = name
    a = info["audio"][0] if info["audio"] else {}
    return {"path": path, "name": os.path.basename(path), "duration": info["duration"],
            "artist": artist, "title": title, "album": t.get("album", ""), "track": t.get("track", ""),
            "date": t.get("date", "")[:10], "genre": t.get("genre", ""),
            "codec": a.get("codec", ""), "rate": a.get("rate", 0), "channels": a.get("channels", 0),
            "streams": info["audio"], "video": info["video"], "chapters": len(info["chapters"]),
            "ok": bool(info["audio"])}


def dvd_titles(folder):
    vts = folder
    if os.path.isdir(os.path.join(folder, "VIDEO_TS")):
        vts = os.path.join(folder, "VIDEO_TS")
    groups = {}
    for f in glob.glob(os.path.join(vts, "VTS_*_*.VOB")) + glob.glob(os.path.join(vts, "vts_*_*.vob")):
        m = re.match(r"VTS_(\d\d)_(\d)\.VOB", os.path.basename(f), re.IGNORECASE)
        if m and m.group(2) != "0":
            groups.setdefault(int(m.group(1)), []).append(f)
    if not groups:
        raise RuntimeError("Kein DVD-Video gefunden (Ordner VIDEO_TS mit VTS_xx_x.VOB).")
    out = []
    for n, files in sorted(groups.items()):
        files.sort()
        size = sum(os.path.getsize(x) for x in files)
        if size < 20 * 1024 * 1024:
            continue
        src = "concat:" + "|".join(files)
        try:
            info = encoder.probe(src)
        except Exception:
            info = {"duration": 0, "audio": []}
        out.append({"path": src, "name": f"DVD-Titel {n:02d}", "duration": info["duration"],
                    "artist": "", "title": f"DVD-Titel {n:02d}", "album": os.path.basename(
                        os.path.dirname(vts.rstrip("\\/"))) or "DVD", "track": str(n), "date": "", "genre": "",
                    "codec": (info["audio"][0]["codec"] if info["audio"] else ""),
                    "rate": (info["audio"][0]["rate"] if info["audio"] else 0), "channels": 2,
                    "streams": info["audio"], "video": True, "chapters": 0, "ok": bool(info["audio"]),
                    "size": size})
    return out


def convert_job(item):
    def run(job):
        src = item["path"]
        job.set(0, "Analysiere …")
        info = encoder.probe(src)
        if not info["audio"]:
            raise RuntimeError("Die Datei enthält keine Tonspur.")
        tags = {"title": item.get("title"), "artist": item.get("artist"), "album": item.get("album"),
                "track": item.get("track"), "date": item.get("date"), "genre": item.get("genre")}
        pipeline.output(job, src, tags, album=bool(item.get("album") and item.get("track")),
                        stream=int(item.get("stream", 0)), keep_meta=not src.startswith("concat:"),
                        src_info=info, out_dir=item.get("out_dir"))
        job.set(1.0, "Fertig")
        if item.get("delete_source") and os.path.isfile(src):
            try:
                os.remove(src)
            except OSError:
                pass
    return run


# ---------------------------------------------------------------- Übergabe-Ordner

class WatchFolder:
    """Alles, was z. B. der Multi Video Downloader hier ablegt, wird automatisch umgewandelt."""

    def __init__(self, jobs):
        self.jobs = jobs
        self.seen = {}
        self.queued = set()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            time.sleep(3)
            s = paths.settings()
            if not s["watch_enabled"] or not s["watch_dir"]:
                continue
            try:
                os.makedirs(s["watch_dir"], exist_ok=True)
                for f in os.listdir(s["watch_dir"]):
                    p = os.path.join(s["watch_dir"], f)
                    if p in self.queued or not os.path.isfile(p):
                        continue
                    if os.path.splitext(f)[1].lower() not in MEDIA_EXT or f.endswith((".part", ".ytdl")):
                        continue
                    st = os.stat(p)
                    sig = (st.st_size, st.st_mtime)
                    if self.seen.get(p) != sig:          # erst umwandeln, wenn die Datei fertig geschrieben ist
                        self.seen[p] = sig
                        continue
                    if time.time() - st.st_mtime < 4:
                        continue
                    self.queued.add(p)
                    self.add(p, delete=s["watch_delete_source"], kind="watch")
            except Exception:
                pass

    def add(self, path, delete=False, kind="file"):
        try:
            item = describe(path)
        except Exception:
            item = {"path": path, "title": os.path.splitext(os.path.basename(path))[0]}
        item["delete_source"] = delete
        return self.jobs.add(kind, item.get("title") or os.path.basename(path), convert_job(item),
                             "Übergabe-Ordner" if kind == "watch" else os.path.basename(path))
