"""Links: YouTube, SoundCloud, Bandcamp, Mixcloud, Vimeo … (über yt-dlp) und Live-Streams."""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from . import encoder, metadata, musicbrainz, paths, pipeline

NOISE = re.compile(r"\s*[\(\[](official\s*(music\s*)?(video|audio|lyric[s]?\s*video|visualizer)|"
                   r"lyrics?|audio|hd|hq|4k|music video|video oficial|offizielles video)[\)\]]",
                   re.IGNORECASE)
DIRECT_EXT = (".mp3", ".aac", ".m3u8", ".m3u", ".pls", ".ogg", ".opus", ".flac", ".wav", ".m4a")


# ---------------------------------------------------------------- Live-Erkennung

LIVE_RE = re.compile(r"\blive\b|\blive@|\bkonzert\b|\bconcert\b|\bunplugged\b|\bfestival\b|\btour\b|"
                     r"\blive lounge\b|\bsessions?\b|\bglastonbury\b|\bcoachella\b|\brock am ring\b|"
                     r"\btiny desk\b|\bauftritt\b|\bin concert\b", re.IGNORECASE)
NOT_ORIGINAL = re.compile(r"\b(cover|karaoke|remix|nightcore|sped ?up|slowed|8d|reverb|instrumental|"
                          r"reaction|tutorial|piano version|lesson|mashup|bass ?boost)", re.IGNORECASE)


STRONG_LIVE = re.compile(r"\blive\s+(at|from|in|aus|@|on|im|vom|beim|performance|version|session|lounge|"
                         r"recording|aufnahme|mitschnitt)\b|\bunplugged\b|\bkonzert\b|\bin concert\b|\btiny desk\b|"
                         r"\blive lounge\b|\blive@", re.IGNORECASE)


def live_reason(info, title, track=None):
    """Erkennt Live-Auftritte, ohne Songs wie „Live and Let Die“ fälschlich zu markieren."""
    if info.get("live_status") == "was_live" or info.get("was_live"):
        return "Aufzeichnung eines Livestreams"
    title = title or ""
    for b in re.findall(r"[\(\[]([^\)\]]*)[\)\]]", title):          # (Live at …), [Live]
        m = LIVE_RE.search(b)
        if m:
            return f"Titel enthält „{b.strip()}“"
    m = STRONG_LIVE.search(title)
    if m:
        return f"Titel enthält „{m.group(0)}“"
    parts = re.split(r"\s+[-–|/@]\s+", track if track is not None else title)
    for part in parts[1:]:                                        # Hello - Live at Glastonbury
        if LIVE_RE.search(part):
            return f"Titel enthält „{part.strip()}“"
    return ""


def strip_live(title):
    """„Rolling in the Deep (Live at the Royal Albert Hall)“ → „Rolling in the Deep“"""
    t = NOISE.sub("", title or "")
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", lambda m: "" if LIVE_RE.search(m.group(0)) else m.group(0), t)
    t = re.split(r"\s+[-–|/@]\s+(?=[^-–|]*(?:" + LIVE_RE.pattern + "))", t, flags=re.IGNORECASE)[0]
    t = re.split(r"\s+(?:live|unplugged)\b.*$", t, flags=re.IGNORECASE)[0]
    return re.sub(r"\s{2,}", " ", t).strip(" -–|") or (title or "")


def find_original(artist, title, exclude_url="", ref_duration=0):
    """Sucht auf YouTube die Studio-/Originalversion. Liefert bis zu 3 Kandidaten, beste zuerst."""
    clean = strip_live(title)
    if not ref_duration:
        m = metadata.lookup(artist, clean)
        ref_duration = (m or {}).get("duration") or 0
    r = paths.run([_ytdlp(), "-J", "--flat-playlist", "--no-warnings", f"ytsearch12:{artist} {clean}"], timeout=60)
    if r.returncode != 0 or not r.stdout:
        return {"clean_title": clean, "candidates": []}
    entries = json.loads(r.stdout.decode("utf-8", "replace")).get("entries") or []
    excl = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", exclude_url or "")
    excl = excl.group(1) if excl else ""
    cands = []
    for e in entries:
        vid, et = e.get("id") or "", e.get("title") or ""
        up = (e.get("channel") or e.get("uploader") or "").strip()
        if not vid or vid == excl or LIVE_RE.search(et) or NOT_ORIGINAL.search(et):
            continue
        a2, t2 = guess_artist_title({"title": et, "uploader": up})
        st = max(metadata._similar(clean, t2), metadata._similar(clean, et) * 0.9)
        topic = up.endswith(" - Topic")
        sa = max(metadata._similar(artist, a2), metadata._similar(artist, up.replace(" - Topic", "").replace("VEVO", "")),
                 0.8 if metadata.norm(artist) in metadata.norm(et) else 0)
        if st < 0.6 or sa < 0.5:
            continue
        low = et.lower()
        score, kind = st * 2 + sa * 2, "Video"
        if topic:
            score, kind = score + 2.5, "Studioaufnahme (YouTube Music)"
        elif "official audio" in low or "offizielles audio" in low:
            score, kind = score + 3, "Offizielles Audio"
        elif re.search(r"official (music )?video|offizielles (musik)?video", low):
            score, kind = score + 2, "Offizielles Musikvideo"
        if "vevo" in up.lower() or metadata._similar(artist, up) >= 0.85:
            score += 1
            if kind == "Video":
                kind = "Offizieller Kanal"
        if "lyric" in low:
            score -= 0.5
        d = e.get("duration") or 0
        if ref_duration and d:
            diff = abs(d - ref_duration)
            score += 1 if diff <= 8 else (-1.5 if diff > 30 else 0)
        cands.append({"url": f"https://www.youtube.com/watch?v={vid}", "title": et, "uploader": up,
                      "duration": d, "kind": kind, "score": round(score, 2),
                      "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"})
    cands.sort(key=lambda c: -c["score"])
    return {"clean_title": clean, "candidates": cands[:3]}


# ---------------------------------------------------------------- Kapitel (Full-Album-Videos)

FULL_ALBUM = re.compile(r"[\(\[]?\s*(full album|complete album|album completo|komplettes album|ganzes album|"
                        r"full ep|full lp|álbum completo)\s*[\)\]]?", re.IGNORECASE)


def clean_chapter(title, artist=""):
    t = re.sub(r"^\s*(\d{1,2}[:.]\d{2}(:\d{2})?\s*[-–]?\s*)", "", title or "")     # Zeitstempel
    t = re.sub(r"^\s*(?:track\s*)?\d{1,3}\s*[.)\-–:]\s*", "", t, flags=re.IGNORECASE)  # 01. / 1) / 1 -
    if artist:
        t = re.sub(r"^\s*" + re.escape(artist) + r"\s*[-–:]\s*", "", t, flags=re.IGNORECASE)
    t = NOISE.sub("", t)
    return t.strip(" -–|") or (title or "").strip()


def chapters_of(info, artist):
    ch = info.get("chapters") or []
    out = []
    for i, c in enumerate(ch, 1):
        s, e = float(c.get("start_time") or 0), float(c.get("end_time") or 0)
        if e - s < 5:                                  # Mini-Kapitel (Intro-Marken) ignorieren
            continue
        out.append({"n": len(out) + 1, "start": round(s, 2), "end": round(e, 2),
                    "title": clean_chapter(c.get("title") or f"Titel {i}", artist)})
    return out if len(out) >= 2 else []


def album_from_title(title, artist):
    t = FULL_ALBUM.sub("", title or "")
    t = re.sub(r"^\s*" + re.escape(artist or "") + r"\s*[-–:|]\s*", "", t, flags=re.IGNORECASE) if artist else t
    t = NOISE.sub("", t)
    t = re.sub(r"[\(\[]\s*(19|20)\d\d\s*[\)\]]", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" -–|")


def _ytdlp():
    p = paths.ytdlp()
    if not p:
        raise RuntimeError("yt-dlp wurde nicht gefunden (bin\\yt-dlp.exe).")
    return p


def analyze(url):
    url = url.strip()
    r = paths.run([_ytdlp(), "-J", "--flat-playlist", "--no-warnings", "--ignore-no-formats-error", url],
                  timeout=120)
    if r.returncode != 0 or not r.stdout:
        if url.lower().split("?")[0].endswith(DIRECT_EXT) or url.lower().startswith(("icy://", "rtmp")):
            return {"type": "stream", "title": url.rsplit("/", 1)[-1], "url": url, "is_live": True}
        msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError((msg[-1] if msg else "Link konnte nicht gelesen werden").replace("ERROR: ", ""))
    info = json.loads(r.stdout.decode("utf-8", "replace"))
    if info.get("_type") == "playlist" or info.get("entries") is not None:
        entries = []
        for e in info.get("entries") or []:
            if not e:
                continue
            u = e.get("url") or e.get("webpage_url") or ""
            if u and not u.startswith("http") and e.get("ie_key", "").lower() == "youtube":
                u = "https://www.youtube.com/watch?v=" + u
            entries.append({"id": e.get("id"), "title": e.get("title") or u, "url": u,
                            "duration": e.get("duration") or 0, "uploader": e.get("uploader") or ""})
        return {"type": "playlist", "title": info.get("title") or "Playlist",
                "uploader": info.get("uploader") or info.get("channel") or "",
                "thumb": _thumb(info), "count": len(entries), "entries": entries, "url": url}
    artist, title = guess_artist_title(info)
    live = "" if info.get("is_live") or not paths.settings().get("live_check", True) else \
        live_reason(info, info.get("title") or "", title)
    out = {"type": "single", "live": live, "can_search": (info.get("extractor_key") or "").lower().startswith("youtube"), "title": info.get("title") or url, "uploader": info.get("uploader") or "",
           "duration": info.get("duration") or 0, "thumb": _thumb(info),
           "url": info.get("webpage_url") or url, "is_live": bool(info.get("is_live")),
           "artist": artist, "track": title, "album": info.get("album") or "",
           "genre": info.get("genre") or "", "date": str(info.get("release_year") or ""),
           "track_no": "", "cover_url": "", "meta_source": ""}
    chapters = [] if out["is_live"] else chapters_of(info, artist)
    if chapters:
        full = bool(FULL_ALBUM.search(info.get("title") or "")) or (len(chapters) >= 4 and (info.get("duration") or 0) >= 900)
        alb = album_from_title(info.get("title") or "", artist)
        am = metadata.album_lookup(artist, alb) if full else None
        out.update({"chapters": chapters, "full_album": full, "live": "" if full else out["live"],
                    "chapter_album": (am or {}).get("album") or alb, "chapter_meta": am or {}})
        if full:
            out.update({"album": (am or {}).get("album") or alb, "genre": (am or {}).get("genre", ""),
                        "date": (am or {}).get("date", "") or out["date"], "cover_url": (am or {}).get("cover_url", ""),
                        "meta_source": (am or {}).get("source", "")})
            return out
    if not out["is_live"]:
        m = metadata.lookup(artist, title)
        if m:
            out.update({"album": out["album"] or m["album"], "genre": out["genre"] or m["genre"],
                        "date": out["date"] or m["date"], "track_no": m["track"], "disc": m.get("disc", ""),
                        "album_artist": m.get("album_artist", ""), "cover_url": m["cover_url"],
                        "meta_source": m["source"]})
    return out


def _thumb(info):
    if info.get("thumbnail"):
        return info["thumbnail"]
    th = info.get("thumbnails") or []
    return th[-1].get("url") if th else ""


def guess_artist_title(info):
    if info.get("track") and (info.get("artist") or info.get("creator")):
        return (info.get("artist") or info.get("creator")).split(",")[0].strip(), info["track"]
    title = NOISE.sub("", info.get("title") or "").strip()
    for sep in (" - ", " – ", " — ", " | "):
        if sep in title:
            a, t = title.split(sep, 1)
            return a.strip(), t.strip()
    up = (info.get("uploader") or info.get("channel") or "Unbekannt").replace(" - Topic", "")
    return up.replace("VEVO", "").strip() or "Unbekannt", title or "Unbenannt"


def download_job(url, overrides=None, playlist_title=None, index=None, total=None):
    overrides = overrides or {}

    def run(job):
        tmp = tempfile.mkdtemp(prefix="dl_", dir=paths.temp_dir())
        try:
            job.set(0.0, "Lädt herunter …")
            args = [_ytdlp(), "-f", "bestaudio/best", "--no-playlist", "--newline", "--no-warnings",
                    "--no-part", "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "jpg",
                    "-o", os.path.join(tmp, "media.%(ext)s"),
                    "--progress-template",
                    "download:AG %(progress.downloaded_bytes)s %(progress.total_bytes)s "
                    "%(progress.total_bytes_estimate)s"]
            ff = paths.ffmpeg()
            if ff:
                args += ["--ffmpeg-location", os.path.dirname(ff)]
            proc = paths.popen(args + [url], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            last = []
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
                        job.set(0.65 * done / tot, f"Lädt herunter … {done / 1048576:.1f} MB")
                    except (ValueError, ZeroDivisionError, IndexError):
                        pass
                elif line:
                    last = (last + [line])[-4:]
            proc.wait()
            if proc.returncode != 0:
                err = [l for l in last if "ERROR" in l] or last
                raise RuntimeError((err[-1] if err else "Download fehlgeschlagen").replace("ERROR: ", ""))

            media = [f for f in glob.glob(os.path.join(tmp, "media.*"))
                     if not f.endswith((".json", ".jpg", ".webp", ".png"))]
            if not media:
                raise RuntimeError("Keine Audiodatei erhalten.")
            info = {}
            for j in glob.glob(os.path.join(tmp, "*.info.json")):
                with open(j, encoding="utf-8") as f:
                    info = json.load(f)
            artist, title = guess_artist_title(info)
            tags = {"artist": overrides.get("artist") or artist,
                    "title": overrides.get("title") or title,
                    "album": overrides.get("album") or info.get("album") or playlist_title or "",
                    "date": str(info.get("release_year") or (info.get("upload_date") or "")[:4]),
                    "comment": info.get("webpage_url") or url,
                    "genre": overrides.get("genre") or ""}
            s = paths.settings()
            album_mode = bool(playlist_title and overrides.get("album_mode"))
            meta = None
            if overrides.get("cover_url") or overrides.get("meta_source"):
                meta = {"cover_url": overrides.get("cover_url", "")}
            elif not overrides.get("no_lookup"):
                job.set(0.65, "Suche Album, Genre & Cover …")
                meta = metadata.lookup(tags["artist"], tags["title"])
                if meta:
                    if not album_mode:
                        tags["album"] = overrides.get("album") or info.get("album") or meta["album"]
                        tags["album_artist"] = meta.get("album_artist", "")
                        tags["track"] = meta.get("track", "")
                        tags["disc"] = meta.get("disc", "")
                    tags["genre"] = tags["genre"] or meta["genre"]
                    tags["date"] = meta["date"] or tags["date"]
            for k in ("date", "track", "disc", "album_artist"):
                if overrides.get(k):
                    tags[k] = overrides[k]
            if index and playlist_title and album_mode:
                tags["track"] = f"{index}/{total}" if total else str(index)
            cover = None
            if meta and meta.get("cover_url") and s.get("prefer_album_cover", True):
                cover = musicbrainz.download_cover(meta["cover_url"], os.path.join(tmp, "album.jpg"))
            jpg = os.path.join(tmp, "media.jpg")
            if not cover and os.path.exists(jpg):
                cover = encoder.make_square_cover(jpg, os.path.join(tmp, "cover.jpg")) \
                    if s["square_cover"] else jpg
            src_info = encoder.probe(media[0])
            chapters = overrides.get("chapters") or []
            if chapters:
                n = len(chapters)
                album = overrides.get("album") or tags["album"] or tags["title"]
                job.title = f"{tags['artist']} – {album} ({n} Titel)"
                files = []
                for i, c in enumerate(chapters, 1):
                    if job.cancel.is_set():
                        raise encoder.Cancelled()
                    ct = {"artist": c.get("artist") or tags["artist"], "album_artist": tags["artist"],
                          "title": c.get("title") or f"Titel {i}", "album": album, "track": f"{i}/{n}",
                          "date": tags.get("date"), "genre": tags.get("genre"), "comment": tags.get("comment")}
                    pipeline.output(job, media[0], ct, album=True, cover=cover, src_info=src_info,
                                    start=float(c["start"]), end=float(c["end"]),
                                    p0=0.7 + 0.3 * (i - 1) / n, p1=0.7 + 0.3 * i / n, stage=f"Titel {i}/{n}")
                    files.append(job.outputs[-1])
                pipeline.write_m3u(files, album)
                job.set(1.0, f"Fertig · {n} Titel")
                return
            job.title = f"{tags['artist']} – {tags['title']}"
            pipeline.output(job, media[0], tags, cover=cover, src_info=src_info, p0=0.7, p1=1.0,
                            album=album_mode)
            job.set(1.0, "Fertig")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return run


# ---------------------------------------------------------------- Live-Mitschnitt

class StreamRecorder:
    """Schneidet Internetradio / Live-Streams mit; nach Stopp wird umgewandelt."""

    def __init__(self, jobs):
        self.jobs = jobs
        self.proc = None
        self.info = None

    def start(self, url, name="", minutes=0):
        if self.proc and self.proc.poll() is None:
            raise RuntimeError("Es läuft bereits ein Mitschnitt.")
        src = url.strip()
        low = src.lower().split("?")[0]
        if not low.endswith(DIRECT_EXT):
            r = paths.run([_ytdlp(), "-g", "-f", "bestaudio/best", "--no-warnings", src], timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                src = r.stdout.decode().strip().splitlines()[0]
        out = os.path.join(paths.temp_dir(), f"stream_{int(time.time())}.mka")
        args = [paths.ffmpeg(), "-hide_banner", "-nostats", "-y", "-reconnect", "1",
                "-reconnect_streamed", "1", "-reconnect_delay_max", "10", "-i", src,
                "-vn", "-map", "0:a:0", "-c:a", "copy"]
        if minutes and float(minutes) > 0:
            args += ["-t", str(int(float(minutes) * 60))]
        self.proc = paths.popen(args + [out], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.info = {"url": url, "name": name or "Stream-Mitschnitt", "file": out, "start": time.time()}
        threading.Thread(target=self._watch, daemon=True).start()
        return self.status()

    def _watch(self):
        proc, info = self.proc, self.info
        proc.wait()
        if info and not info.get("handed"):
            self._finish(info)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
            except Exception:
                self.proc.terminate()
        return True

    def _finish(self, info):
        info["handed"] = True
        f = info["file"]
        if not os.path.exists(f) or os.path.getsize(f) < 4096:
            return

        def run(job):
            try:
                src_info = encoder.probe(f)
                stamp = time.strftime("%Y-%m-%d %H-%M", time.localtime(info["start"]))
                tags = {"artist": info["name"], "title": f"Mitschnitt {stamp}", "comment": info["url"]}
                pipeline.output(job, f, tags, src_info=src_info)
                job.set(1.0, "Fertig")
            finally:
                try:
                    os.remove(f)
                except OSError:
                    pass
        self.jobs.add("stream", info["name"], run, "Live-Mitschnitt")

    def status(self):
        running = bool(self.proc and self.proc.poll() is None)
        if not self.info:
            return {"running": False}
        size = os.path.getsize(self.info["file"]) if os.path.exists(self.info["file"]) else 0
        return {"running": running, "name": self.info["name"], "elapsed": time.time() - self.info["start"],
                "size": size}


def update_ytdlp():
    """Unter C:\\Programme fehlt das Schreibrecht – dann wird eine Kopie im Benutzerordner aktualisiert."""
    exe = _ytdlp()
    if not paths.writable(os.path.dirname(exe)):
        own = os.path.join(paths.data_dir(), "bin")
        os.makedirs(own, exist_ok=True)
        dst = os.path.join(own, os.path.basename(exe))
        shutil.copy2(exe, dst)
        exe = dst
    r = paths.run([exe, "-U"], timeout=300)
    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
    return out[-1] if out else "Fertig"
