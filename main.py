"""SongGrabber by Pezhy – Audio von CD, Links, Aufnahme und Dateien in MP3 / WAV / FLAC.

Aufrufe (auch für den Multi Video Downloader):
  SongGrabber.exe                                   Fenster öffnen
  SongGrabber.exe "C:\\Videos\\clip.mp4" ...          Dateien umwandeln (an offenes Fenster übergeben)
  SongGrabber.exe --url https://youtu.be/...         Link herunterladen & umwandeln
  SongGrabber.exe --headless --preset mp3_320 --out "D:\\Musik" --report r.json clip.mp4
                                                     ohne Fenster umwandeln, danach beenden
"""
import argparse
import ctypes
import json
import logging
import os
import re
import sys
import threading
import time

from agcore import (bridge, cleanup, karaoke, loudness, screenrec, cdrip, encoder, export, files, identify, library, links, lyrics, mediaserver, metadata,
                    musicbrainz, paths, pipeline, podcasts, radio, recorder, streaming, subs, sysaudio, tags, trim)
from agcore.jobs import JobManager


class Api:
    def __init__(self):
        self._window = None
        self._jobs = JobManager(workers=1)
        self._streams = links.StreamRecorder(self._jobs)
        self._rec = recorder.Recorder(self._jobs)
        self._mon = recorder.Monitor()
        self._watch = files.WatchFolder(self._jobs)
        self._inbox = []          # Übergaben von außen, die die Oberfläche anzeigen soll
        self._versions = {}
        self._groups = {}         # Link-Playlists → nach dem letzten Titel automatisch .m3u8
        self._media = mediaserver.MediaServer()
        self._lib = library.Library()
        self._remote = streaming.Remote(self._media)
        self._sys = sysaudio.SystemAudio(self._media)
        self._np = sysaudio.NowPlaying(self._media)
        self._radio_meta = {}
        self._clean = cleanup.Cleanup()
        self._screen = screenrec.ScreenRec()
        self._kara = karaoke.Karaoke(self._media, self._jobs)
        self._krec = karaoke.KaraRec()
        self._close_ok = False
        self._ly_cache = {}
        self._jobs.listeners.append(self._job_done)
        self._subs = subs.Subscriptions(self._abo_download)
        threading.Thread(target=self._load_versions, daemon=True).start()
        self._lib.scan()

    def _job_done(self, job):
        for out in job.outputs:
            self._lib.add(out)
        for gid, g in list(self._groups.items()):
            if job.id not in g["ids"]:
                continue
            jobs = [self._jobs.jobs.get(i) for i in g["ids"]]
            if any(j and j.status in ("wartet", "läuft") for j in jobs):
                return
            files_ = [j.outputs[-1] for j in jobs if j and j.status == "fertig" and j.outputs]
            if len(files_) >= 2 and paths.settings().get("auto_playlist_links", True):
                pipeline.write_m3u(files_, g["title"], folder=paths.playlist_dir())
            del self._groups[gid]

    def _load_versions(self):
        self._versions = {"ffmpeg": paths.tool_version(paths.ffmpeg()),
                          "ytdlp": paths.tool_version(paths.ytdlp(), "--version")}

    # ------------------------------------------------------------ Allgemein
    def init(self):
        ff, yt = paths.ffmpeg(), paths.ytdlp()
        return {"version": paths.VERSION, "presets": encoder.preset_list(), "settings": paths.settings(),
                "media_control": self._np.available(),
                "tools": {"ffmpeg": bool(ff), "ffprobe": bool(paths.ffprobe()), "ytdlp": bool(yt),
                          "ffmpeg_version": self._versions.get("ffmpeg"),
                          "ytdlp_version": self._versions.get("ytdlp"),
                          "bin_dirs": paths.bin_dirs()},
                "windows": paths.IS_WIN, "data_dir": paths.data_dir(), "sys_lang": paths.system_lang()}

    def output_check(self):
        """Ist der Zielordner erreichbar? (läuft im Hintergrund – Netzlaufwerke können Sekunden brauchen)"""
        d = paths.settings()["output_dir"]
        try:
            paths.ensure_output(d)
            return {"ok": True, "dir": d}
        except RuntimeError as e:
            return {"ok": False, "dir": d, "error": str(e)}

    def update_check(self, force=False):
        """Gibt es eine neuere Version? (GitHub-Releases oder eigene JSON-Datei, siehe paths.UPDATE_URL)"""
        if not paths.UPDATE_URL:
            return {"enabled": False, "current": paths.VERSION}
        s = paths.settings()
        if not force and (not s.get("update_check", True) or time.time() - float(s.get("update_last") or 0) < 20 * 3600):
            return {"enabled": True, "skipped": True}
        try:
            import urllib.request
            req = urllib.request.Request(paths.UPDATE_URL, headers={"User-Agent": f"SongGrabber/{paths.VERSION}",
                                                                   "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            return {"enabled": True, "error": str(e)[:160], "current": paths.VERSION}
        paths.save_settings({"update_last": time.time()})
        ver = str(d.get("tag_name") or d.get("version") or "").lstrip("vV ").strip()
        url = d.get("url") if "tag_name" not in d else d.get("html_url")
        want = ".exe" if paths.IS_WIN else "-linux.tar.gz"   # GitHub: direkt die passende Datei verlinken
        for a in d.get("assets") or []:
            if str(a.get("name", "")).lower().endswith(want):
                url = a.get("browser_download_url") or url
                break

        def vt(v):
            return tuple(int(x) for x in re.findall(r"\d+", v)[:4])
        return {"enabled": True, "newer": bool(ver) and vt(ver) > vt(paths.VERSION), "version": ver, "url": url or "",
                "platform": "windows" if paths.IS_WIN else "linux",
                "notes": str(d.get("body") or d.get("notes") or "")[:2000], "current": paths.VERSION}

    def save_settings(self, s):
        return paths.save_settings(s)

    def _dialog(self, kind, multiple=False, types=()):
        import webview
        fd = getattr(webview, "FileDialog", None)
        k = {"folder": getattr(fd, "FOLDER", None) if fd else webview.FOLDER_DIALOG,
             "open": getattr(fd, "OPEN", None) if fd else webview.OPEN_DIALOG}[kind]
        res = self._window.create_file_dialog(k, allow_multiple=multiple, file_types=_safe_filters(types))
        return list(res) if res else []

    def choose_folder(self):
        r = self._dialog("folder")
        return r[0] if r else ""

    def choose_files(self):
        exts = ";".join("*" + e for e in sorted(files.MEDIA_EXT))
        return self._dialog("open", True, (f"Audio und Video ({exts})", "Alle Dateien (*.*)"))

    def choose_image(self):
        r = self._dialog("open", False, ("Bilder (*.jpg;*.jpeg;*.png)",))
        return r[0] if r else ""

    def open_file(self, p):
        """Datei mit dem Standardprogramm öffnen (z. B. fertige Bildschirmaufnahme abspielen)."""
        if not p or not os.path.isfile(p):
            return False
        if paths.IS_WIN:
            os.startfile(p)
        else:
            from agcore import osint
            osint.open_path(p)
        return True

    def open_path(self, p):
        if not p:
            p = paths.settings()["output_dir"]
        if not os.path.exists(p) and not os.path.splitext(p)[1]:
            os.makedirs(p, exist_ok=True)
        if paths.IS_WIN and os.path.exists(p):
            if os.path.isfile(p):
                paths.popen(["explorer", "/select,", os.path.normpath(p)])
            else:
                os.startfile(p)
        elif os.path.exists(p):
            from agcore import osint
            osint.open_path(p, reveal=os.path.isfile(p))
        return True

    def get_clipboard(self):
        if not paths.IS_WIN:
            from agcore import osint
            return osint.clipboard_get()
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalLock.argtypes = [ctypes.c_void_p]
        u.GetClipboardData.restype = ctypes.c_void_p
        if not u.OpenClipboard(None):
            return ""
        try:
            h = u.GetClipboardData(13)      # CF_UNICODETEXT
            if not h:
                return ""
            p = k.GlobalLock(h)
            text = ctypes.wstring_at(p)
            k.GlobalUnlock(ctypes.c_void_p(h))
            return text.strip()
        finally:
            u.CloseClipboard()

    def pop_inbox(self):
        items, self._inbox = self._inbox, []
        return items

    # ------------------------------------------------------------ Links
    def link_analyze(self, url):
        return links.analyze(url)

    def link_download(self, items, opts=None):
        opts = opts or {}
        ids = []
        pl = opts.get("playlist_title") if opts.get("as_album") else None
        total = len(items)
        single = opts.get("single") or {}
        for i, it in enumerate(items, 1):
            ov = {"artist": it.get("artist") or opts.get("artist"), "title": it.get("title_override"),
                  "album": opts.get("album") or pl, "genre": opts.get("genre"),
                  "album_mode": bool(pl)}
            if total == 1:
                ov.update({k: single.get(k) for k in ("date", "track", "disc", "album_artist",
                                                      "cover_url", "meta_source", "chapters") if single.get(k)})
            ids.append(self._jobs.add("link", it.get("title") or it["url"],
                                     links.download_job(it["url"], ov, pl, i if pl else None, total),
                                     it.get("uploader") or it["url"]))
        if total > 1 and opts.get("playlist_title"):
            self._groups[ids[0]] = {"ids": set(ids), "title": opts["playlist_title"]}
        return ids

    # ------------------------------------------------------------ Player & Bibliothek
    def media_url(self, path):
        return {"src": self._media.url(path), "art": self._media.url(path, "art"),
                **{k: v for k, v in library.read_tags(path).items()}, "path": path}

    def loudness(self, items):
        """Verstärkung je Titel für „Lautstärke angleichen“ (None = wird noch gemessen)."""
        return loudness.get(items)

    def media_urls(self, paths_):
        return [self.media_url(p) for p in paths_ if os.path.isfile(p)]

    def lib_list(self):
        return {"items": self._lib.list(), "status": self._lib.status()}

    def lib_scan(self, force=False):
        return self._lib.scan(bool(force))

    def lib_status(self):
        return self._lib.status()

    def lib_delete(self, paths_):
        done, errors = library.delete_files(paths_)
        for p in done:
            self._lib.remove(p)
        return {"deleted": len(done), "errors": errors, "recycle": True}

    def lib_reorganize(self, apply=False):
        r = library.reorganize(bool(apply))
        if apply:
            self._lib.scan(True)
        return r

    def set_layout(self, key):
        single, album = paths.LAYOUTS[key]
        return paths.save_settings({"name_single": single, "name_album": album})

    # ------------------------------------------------------------ Tag-Editor & Songtexte
    def tags_read(self, paths_):
        out = []
        for p in paths_:
            if os.path.isfile(p):
                t = tags.read(p)
                t["art"] = self._media.url(p, "art") if t["has_cover"] else ""
                lrc = os.path.splitext(p)[0] + ".lrc"
                if os.path.exists(lrc):
                    with open(lrc, encoding="utf-8", errors="replace") as f:
                        t["lyrics"] = f.read()
                out.append(t)
        return out

    def tags_online(self, artist, title):
        return metadata.lookup(artist, title) or {}

    def tags_save(self, paths_, fields, cover=None, lyrics_text=None, rename=True):
        """cover: {"mode": "keep"|"remove"|"file"|"url", "value": …}"""
        cover = cover or {"mode": "keep"}
        data = None
        if cover.get("mode") == "file" and os.path.isfile(cover.get("value", "")):
            with open(cover["value"], "rb") as f:
                data = f.read()
        elif cover.get("mode") == "url" and cover.get("value"):
            p = musicbrainz.download_cover(cover["value"], os.path.join(paths.temp_dir(), "editor_cover.jpg"))
            if p:
                with open(p, "rb") as f:
                    data = f.read()
        new_paths, errors = [], []
        for p in paths_:
            try:
                np_ = library.apply_tags(p, fields, cover_data=data, remove_cover=cover.get("mode") == "remove",
                                         lyrics=lyrics_text, rename=bool(rename))
                if lyrics_text is not None:
                    lrc = os.path.splitext(np_)[0] + ".lrc"
                    if tags.is_lrc(lyrics_text) and (paths.settings().get("lyrics_lrc") or os.path.exists(lrc)):
                        with open(lrc, "w", encoding="utf-8") as f:
                            f.write(lyrics_text)
                self._lib.remove(p)
                self._lib.add(np_)
                new_paths.append(np_)
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        return {"paths": new_paths, "errors": errors}

    def lyrics_fetch(self, artist, title, album="", duration=0):
        return lyrics.fetch(artist, title, album, duration) or {}

    def lyrics_smart(self, artist, title, album="", duration=0, raw=""):
        key = (artist, title, int(duration or 0), raw)
        if key not in self._ly_cache:
            self._ly_cache[key] = lyrics.smart(artist, title, album, duration, raw) or {}
        return self._ly_cache[key]

    def lyrics_for(self, path):
        lrc = os.path.splitext(path)[0] + ".lrc"
        if os.path.exists(lrc):
            with open(lrc, encoding="utf-8", errors="replace") as f:
                return f.read()
        return tags.read(path).get("lyrics", "")

    def _batch(self, kind, title, paths_, fn, verb):
        def run(job):
            n, ok, err = len(paths_), 0, []
            for i, p in enumerate(paths_, 1):
                if job.cancel.is_set():
                    raise encoder.Cancelled()
                job.set((i - 1) / n, f"{verb} {i}/{n}: {os.path.basename(p)}")
                try:
                    res = fn(p)
                    if res:
                        ok += 1
                        if isinstance(res, str):
                            self._lib.remove(p)
                            p = res
                        job.outputs.append(p)
                        self._lib.add(p)
                except Exception as e:
                    err.append(str(e))
                    if "Schlüssel" in str(e) or "fpcalc" in str(e):
                        raise
            job.set(1.0, f"Fertig · {ok} von {n}" + (f" · {len(err)} Fehler" if err else ""))
        return self._jobs.add(kind, title, run, f"{len(paths_)} Titel")

    # ------------------------------------------------------------ Bildschirmaufnahme
    def screen_sources(self):
        return screenrec.sources()

    def screen_preview(self, src_id, width=480):
        return screenrec.preview(src_id, int(width or 480))

    def screen_start(self, opts):
        self._mon.stop()                      # Pegel-Vorschau gibt die Geräte frei
        return self._screen.start(opts)

    def screen_pause(self):
        return self._screen.pause()

    def screen_resume(self):
        return self._screen.resume()

    def screen_mic(self, on):
        return self._screen.set_mic(on)

    def screen_stop(self):
        return self._screen.stop()

    def screen_discard(self):
        return self._screen.discard()

    def screen_status(self):
        return self._screen.status()

    def screen_bar(self, on):
        """Während der Bildschirmaufnahme: SongGrabber als schmale Leiste oben rechts (immer im Vordergrund).
        Unter Windows ist die Leiste im Video unsichtbar. Rückgabe: hidden = in der Aufnahme ausgeblendet."""
        hidden = False
        if paths.IS_WIN:
            from agcore import winwin
            hidden = winwin.exclude_from_capture(bool(on)) and bool(on)
        ok = self.mini(bool(on), W=440, H=130, top=True)
        return {"ok": ok, "hidden": hidden}

    # ------------------------------------------------------------ Karaoke
    def kara_state(self):
        return self._kara.state()

    def kara_search(self, q, long=False):
        return karaoke.search(q, long=bool(long))

    def kara_rec_start(self, meta):
        self._mon.stop()
        return self._krec.start(meta)

    def kara_rec_dirty(self):
        return self._krec.dirty()

    def kara_rec_status(self):
        return self._krec.status()

    def kara_rec_stop(self, keep=True):
        return self._krec.stop(bool(keep))

    def kara_rec_remix(self, rid, voice_db):
        return self._krec.remix(rid, voice_db)

    def kara_rec_delete(self, rid):
        return self._krec.delete(rid)

    def kara_playlists(self, q):
        return karaoke.playlists(q)

    def kara_playlist(self, url):
        return karaoke.playlist_items(url)

    def kara_play(self, song):
        return self._kara.play_url(song)

    def kara_prepare(self, song):
        return self._kara.prepare(song)

    def kara_fav(self, song, on=True):
        return self._kara.favorite(song, bool(on))

    def kara_remove(self, vid, delete_file=False):
        return self._kara.remove(vid, bool(delete_file))

    def kara_offline_all(self):
        return self._kara.download_all()

    def kara_download(self, vid):
        return self._kara.download(vid)

    def kara_queue(self, q, singers=None):
        return self._kara.save_queue(q, singers)

    def video_url(self, path):
        """Abspiel-Adresse für ein Video im eigenen Fenster (fertige Bildschirmaufnahme)."""
        return self._media.url(path)

    def screen_close(self, keep=True):
        """Fenster trotz laufender Bildschirmaufnahme schließen (keep=True: vorher speichern)."""
        if keep:
            self._screen.stop()
        else:
            self._screen.discard()
        self._close_ok = True
        threading.Thread(target=lambda: (self._screen.wait(120), self._window.destroy()), daemon=True).start()
        return True

    # ------------------------------------------------------------ Bibliothek aufräumen
    def cleanup_start(self):
        return self._clean.start(self._lib.list())

    def cleanup_status(self):
        return self._clean.status()

    def cleanup_fill(self, paths_):
        """Nur Lücken füllen: fehlendes Album, Genre, Jahr, Nummer und Cover – vorhandene Angaben bleiben."""
        def one(p):
            from agcore import tags as T
            t = T.read(p)
            artist, title = t.get("artist") or "", t.get("title") or ""
            if not artist or not title:
                return False
            m = metadata.lookup(artist, title) or {}
            if not m:
                return False
            fields = {}
            for k, src in (("album", "album"), ("genre", "genre"), ("date", "date"), ("album_artist", "album_artist"), ("track", "track")):
                if not (t.get(k) or "").strip() and m.get(src):
                    fields[k] = m[src]
            data = None
            if not t.get("has_cover") and m.get("cover_url"):
                c = musicbrainz.download_cover(m["cover_url"], os.path.join(paths.temp_dir(), "aufraeumen.jpg"))
                if c:
                    with open(c, "rb") as f:
                        data = f.read()
            if not fields and not data:
                return False
            return library.apply_tags(p, fields, cover_data=data)
        return self._batch("file", "Bibliothek ergänzen", paths_, one, "Ergänze")

    def cleanup_empty(self, dirs):
        return cleanup.remove_dirs(dirs)

    def lyrics_files(self, paths_):
        return self._batch("file", "Songtexte suchen", paths_, lambda p: lyrics.apply(p), "Songtext")

    def identify_files(self, paths_):
        def one(p):
            hit = identify.identify(p)
            if not hit:
                return False
            data = None
            if hit.get("cover_url"):
                c = musicbrainz.download_cover(hit["cover_url"], os.path.join(paths.temp_dir(), "erkannt.jpg"))
                if c:
                    with open(c, "rb") as f:
                        data = f.read()
            return library.apply_tags(p, recorder._hit_fields(hit, {}), cover_data=data)
        return self._batch("file", "Titel erkennen", paths_, one, "Erkenne")

    def identify_status(self):
        return {"available": identify.available(), "key": bool(paths.settings().get("acoustid_key"))}

    # ------------------------------------------------------------ Kürzen
    def trim_analyze(self, path):
        r = trim.analyze(path)
        r["src"] = self._media.url(path)
        return r

    def trim_apply(self, path, start, end, fade=False, keep_original=False):
        r = trim.apply(path, start, end, bool(fade), bool(keep_original))
        self._lib.add(path)
        return r

    # ------------------------------------------------------------ Übertragen
    def export_drives(self):
        return export.drives()

    def export_start(self, name, paths_, target, mode="copy", numbered=True):
        if not target or not os.path.isdir(target):
            raise RuntimeError("Bitte ein Ziel (USB-Stick oder Ordner) wählen.")
        return self._jobs.add("file", f"Übertragen: {name}", export.job(name, paths_, target, mode, bool(numbered)),
                              f"{len(paths_)} Titel → {target}")

    # ------------------------------------------------------------ Online abspielen (YouTube & Co., Radio, Podcasts)
    def items_resolve(self, entries):
        """Einträge (Dateipfade oder Beschreibungen von Online-Quellen) → abspielbare Player-Einträge."""
        out = []
        for e in entries or []:
            if isinstance(e, str):
                e = {"kind": "file", "path": e}
            k = e.get("kind") or "file"
            if k == "file":
                if os.path.isfile(e.get("path", "")):
                    out.append(dict(self.media_url(e["path"]), kind="file"))
            elif k == "stream":
                src, _ = self._remote.audio_url("page", e["url"])
                out.append({"kind": "stream", "src": src, "path": e["url"], "url": e["url"], "title": e.get("title") or e["url"],
                            "artist": e.get("artist") or "", "album": e.get("album") or "", "duration": e.get("duration") or 0,
                            "thumb": e.get("thumb") or "", "art": self._remote.img_url(e.get("thumb")), "year": ""})
            elif k == "radio":
                src, rid = self._remote.audio_url("live", e["url"])
                out.append({"kind": "radio", "src": src, "rid": rid, "path": "radio:" + (e.get("uuid") or e["url"]),
                            "uuid": e.get("uuid"), "url": e["url"], "title": e.get("name") or "Radio", "station": e.get("name") or "Radio",
                            "artist": " · ".join(e.get("tags") or [])[:60], "favicon": e.get("favicon") or "",
                            "art": self._remote.img_url(e.get("favicon")), "duration": 0, "live": True, "tags": e.get("tags") or []})
            elif k == "podcast":
                src, _ = self._remote.audio_url("direct", e["url"])
                out.append({"kind": "podcast", "src": src, "path": e["url"], "url": e["url"], "guid": e.get("guid"),
                            "title": e.get("title") or "Folge", "artist": e.get("show") or "", "album": e.get("show") or "",
                            "show": e.get("show") or "", "image": e.get("image") or "", "feed": e.get("feed") or "",
                            "art": self._remote.img_url(e.get("image")), "duration": e.get("duration") or 0})
        return out

    def online_search(self, query):
        return streaming.search(query)

    # Radio
    def radio_search(self, query="", tag="", country=""):
        return radio.search(query, tag, country)

    def radio_tags(self):
        return radio.tags()

    def radio_favorites(self):
        return {"favorites": radio.favorites(), "recent": radio.recent()}

    def radio_toggle_fav(self, st):
        return radio.toggle_favorite(st)

    def radio_played(self, st):
        radio.click(st.get("uuid"))
        radio.add_recent(st)
        return True

    def radio_now(self, rid):
        """Gerade gesendeter Titel → Interpret, Titel und (wenn gefunden) Cover."""
        text = self._remote.now_playing(rid)
        if not text:
            return {}
        meta = self._remote.now_meta(rid)
        timing = {"changed": meta.get("t", 0), "first": meta.get("n", 1) <= 1, "now": time.time()}
        c = self._radio_meta.get(text)
        if c is None:
            pairs = lyrics.split_text(text)
            artist, title = pairs[0] if pairs else ("", text)
            c = {"text": text, "artist": artist, "title": title, "art": "", "album": ""}
            for a, t in pairs[:3]:          # Reihenfolge prüfen: „Titel - Interpret“ gibt es auch
                m = metadata.lookup(a, t) or {}
                if m and metadata._similar(a, m.get("artist")) >= 0.6 and metadata._similar(t, m.get("title")) >= 0.6:
                    c.update(artist=m.get("artist") or a, title=t, album=m.get("album", ""), duration=m.get("duration") or 0)
                    if m.get("cover_url"):
                        c["art"] = self._remote.img_url(m["cover_url"].replace("1000x1000", "600x600"))
                    break
            self._radio_meta[text] = c
        return dict(c, **timing)

    def radio_quick(self, src, station, mode="song"):
        """Sofort mitschneiden, was gerade im Player läuft (src = Abspiel-Adresse …/r/<id>)."""
        rid = (src or "").rstrip("/").rsplit("/", 1)[-1]
        return self._remote.quick_start(rid, station or "Radio", mode)

    def radio_quick_stop(self, qid=None):
        return self._remote.quick_stop(qid)

    def radio_quick_status(self):
        return self._remote.quick_status()

    def radio_record(self, st, minutes=0):
        return self._streams.start(st["url"], st.get("name") or "Radio", minutes)

    # Podcasts
    def podcast_search(self, query):
        return podcasts.search(query)

    def podcast_open(self, feed, refresh=True):
        if not refresh:
            c = podcasts.cached(feed)
            if c:
                return c
        try:
            return podcasts.fetch(feed)
        except Exception:
            c = podcasts.cached(feed)
            if c:
                return c
            raise

    def podcast_subs(self):
        return podcasts.subscriptions()

    def podcast_subscribe(self, show):
        return podcasts.subscribe(show)

    def podcast_unsubscribe(self, feed):
        return podcasts.unsubscribe(feed)

    def podcast_progress(self):
        return podcasts.progress()

    def podcast_progress_set(self, guid, pos, dur):
        return podcasts.set_progress(guid, pos, dur)

    def podcast_download(self, show, ep):
        return self._jobs.add("link", ep.get("title") or "Podcast-Folge", podcasts.download_job(show, ep), show.get("title") or "")

    # Lichtshow für alles
    def sys_viz_url(self):
        return self._sys.url

    def now_playing(self):
        return dict(self._np.info(), device=self._sys.device, viz_error=self._sys.error)

    def media_control(self, cmd):
        return self._np.control(cmd)

    # ------------------------------------------------------------ Player
    def player_state_save(self, state):
        with open(os.path.join(paths.data_dir(), "player.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        return True

    def player_state_load(self):
        try:
            with open(os.path.join(paths.data_dir(), "player.json"), encoding="utf-8") as f:
                s = json.load(f)
            entries = s.get("items") or s.get("paths") or []
            s["items"] = self.items_resolve(entries)
            return s
        except Exception:
            return {}

    def files_expand_audio(self, items):
        return _expand_play(items)

    def playlist_save(self, name, paths_):
        p = pipeline.write_m3u([x for x in paths_ if os.path.isfile(x)], name, folder=paths.playlist_dir())
        return os.path.splitext(os.path.basename(p))[0] if p else name

    def mini(self, on, keep=False, W=460, H=150, top=False):
        """Mini-Player: kleines Fenster unten rechts, immer im Vordergrund – und wieder zurück.
        keep=True: Mini wurde durch Vergrößern von Hand verlassen → Größe lassen, nur Vordergrund aufheben."""
        try:
            if paths.IS_WIN:
                from agcore import winwin
                return winwin.forget() if (keep and not on) else winwin.mini(bool(on), W, H, top=top)
            w = self._window                    # Linux (GTK): Fensterbefehle sind hier sicher
            if not w:
                return False
            if on:
                if not getattr(self, "_normal", None):
                    self._normal = (w.width, w.height, w.x, w.y)
                w.resize(W, H)
                import webview
                sc = (webview.screens or [None])[0]
                if sc:
                    w.move(sc.x + sc.width - W - 16, sc.y + 40 if top else sc.y + sc.height - H - 56)
                w.on_top = True
            else:
                w.on_top = False
                n = getattr(self, "_normal", None)
                if n and not keep:
                    w.resize(n[0], n[1])
                    w.move(n[2], n[3])
                self._normal = None
            return True
        except Exception as e:
            paths.log.warning("Mini-Player: %s", e)
            return False

    def toggle_fullscreen(self):
        if self._window:
            self._window.toggle_fullscreen()
            self._fullscreen = not getattr(self, "_fullscreen", False)
        return getattr(self, "_fullscreen", False)

    def playlist_paths(self, path):
        return library.read_playlist(path)

    def playlist_create(self, mode, opts):
        made = library.generate(self._lib.list(), mode, opts or {})
        return [os.path.basename(m) for m in made]

    def playlist_list(self):
        return library.list_playlists()

    def playlist_items(self, path):
        return self.media_urls(library.read_playlist(path))

    def playlist_delete(self, path):
        if path.lower().endswith((".m3u8", ".m3u")) and os.path.isfile(path):
            os.remove(path)
        return True

    def open_url(self, url):
        if url.lower().startswith(("http://", "https://")):
            import webbrowser
            webbrowser.open(url)
        return True

    def set_clipboard(self, text):
        if not paths.IS_WIN:
            from agcore import osint
            return osint.clipboard_set(text)
        import subprocess
        p = paths.popen(["clip"], stdin=subprocess.PIPE)
        p.communicate(b"\xff\xfe" + text.encode("utf-16-le"))
        return True

    def link_find_original(self, artist, title, url="", duration=0):
        return links.find_original(artist, title, url, duration)

    # ------------------------------------------------------------ Abos
    def _abo_download(self, url, title, abo_name):
        return self._jobs.add("link", title, links.download_job(url, {}), f"Abo · {abo_name}")

    def abos_list(self):
        return {"items": self._subs.list(), "autostart": subs.autostart(),
                "hours": paths.settings().get("abo_hours", 6)}

    def abos_add(self, url, name="", backfill=0, skip_live=True):
        return self._subs.add(url, name, int(backfill or 0), bool(skip_live))

    def abos_check(self, abo_id=None):
        return self._subs.check(abo_id or None)

    def abos_update(self, abo_id, patch):
        return self._subs.update(abo_id, patch)

    def abos_remove(self, abo_id):
        return self._subs.remove(abo_id)

    def autostart_set(self, enable):
        return subs.autostart(bool(enable))

    def stream_start(self, url, name="", minutes=0):
        return self._streams.start(url, name, minutes)

    def stream_stop(self):
        return self._streams.stop()

    def stream_status(self):
        return self._streams.status()

    def ytdlp_update(self):
        r = links.update_ytdlp()
        self._load_versions()
        return r

    # ------------------------------------------------------------ Audio-CD
    def cd_drives(self):
        return cdrip.drives()

    def cd_read(self, letter):
        return cdrip.read_disc(letter)

    def cd_rip(self, letter, album, tracks):
        if not tracks:
            raise RuntimeError("Keine Titel ausgewählt.")
        return self._jobs.add("cd", album.get("album") or "Audio-CD", cdrip.rip_job(letter, album, tracks),
                             f"{album.get('artist') or 'Unbekannt'} · {len(tracks)} Titel")

    def cd_make_test(self):
        from agcore import testcd
        out = os.path.join(paths.data_dir(), "Test-CD")
        cue = os.path.join(out, "Test-CD.cue")
        return cue if os.path.exists(cue) and os.path.exists(os.path.join(out, "Test-CD.bin")) else testcd.make(out, log=lambda *_: None)

    def cd_open_image(self):
        r = self._dialog("open", False, ("CD Abbild (*.cue)", "Alle Dateien (*.*)"))
        return r[0] if r else ""

    def cd_eject(self, letter):
        return cdrip.eject(letter)

    # ------------------------------------------------------------ Aufnahme
    def rec_devices(self):
        return recorder.devices()

    def rec_monitor(self):
        """Live-Pegel aller Eingänge (nur solange keine Aufnahme läuft)."""
        if self._rec.state != "idle" or self._screen.status()["state"] in ("recording", "paused", "finishing"):
            self._mon.stop()
            return {"levels": {}, "privacy": "ok", "paused": True}
        return {"levels": self._mon.poll(), "privacy": recorder.mic_privacy(), "paused": False}

    def rec_privacy_settings(self):
        return recorder.open_privacy_settings()

    def rec_start(self, opts):
        self._mon.stop()
        s = paths.settings()
        opts.setdefault("samplerate", s["rec_samplerate"])
        opts.setdefault("bitdepth", s["rec_bitdepth"])
        return self._rec.start(opts)

    def rec_pause(self):
        return self._rec.pause()

    def rec_stop(self, meta=None):
        return self._rec.stop(meta)

    def rec_discard(self):
        return self._rec.discard()

    def rec_gain(self, db):
        return self._rec.set_gain(db)

    def rec_status(self):
        return self._rec.status()

    # ------------------------------------------------------------ Dateien & DVD
    def files_probe(self, items):
        out = []
        for p in files.expand(items):
            try:
                out.append(files.describe(p))
            except Exception as e:
                out.append({"path": p, "name": os.path.basename(p), "ok": False, "error": str(e)})
        return out

    def drop_sort(self, items):
        """Hereingezogene Dateien/Ordner nach Art sortieren, damit jeder Bereich das Passende übernimmt."""
        out = {k: [] for k in ("media", "audio", "folders", "dvd", "images", "cue", "playlists", "links", "other")}
        for p in items or []:
            if not p or not os.path.exists(p):
                continue
            ext = os.path.splitext(p)[1].lower()
            if os.path.isdir(p):
                is_dvd = os.path.basename(p.rstrip("\\/")).upper() == "VIDEO_TS" or os.path.isdir(os.path.join(p, "VIDEO_TS"))
                out["dvd" if is_dvd else "folders"].append(p)
            elif ext == ".cue":
                out["cue"].append(p)
            elif ext in (".m3u", ".m3u8"):
                out["playlists"].append(p)
            elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                out["images"].append(p)
            elif ext in files.MEDIA_EXT:
                out["media"].append(p)
                if ext in library.AUDIO_EXT:
                    out["audio"].append(p)
            elif ext in (".url", ".txt", ".webloc") and os.path.getsize(p) < 2_000_000:
                with open(p, encoding="utf-8", errors="replace") as f:
                    found = re.findall(r"https?://[^\s\"'<>]+", f.read())
                out["links"] += [u for u in dict.fromkeys(found)]
            else:
                out["other"].append(p)
        return out

    def dvd_from(self, folder):
        if os.path.basename(folder.rstrip("\\/")).upper() == "VIDEO_TS":
            folder = os.path.dirname(folder.rstrip("\\/"))
        return files.dvd_titles(folder)

    def dvd_open(self):
        folder = self.choose_folder()
        return files.dvd_titles(folder) if folder else []

    def files_convert(self, items):
        return [self._jobs.add("file", it.get("title") or it.get("name"), files.convert_job(it),
                              it.get("name", "")) for it in items]

    # ------------------------------------------------------------ Warteschlange
    def jobs_list(self):
        return {"jobs": self._jobs.snapshot(), "stream": self._streams.status(),
                "inbox": len(self._inbox)}

    def job_cancel(self, job_id):
        return self._jobs.cancel(job_id)

    def jobs_clear(self):
        return self._jobs.clear_finished()

    # ------------------------------------------------------------ Übergaben von außen
    def external(self, msg):
        if msg.get("play"):
            ps = _expand_play(msg["play"])
            if ps:
                now = time.time()
                kind = "play_add" if now - getattr(self, "_last_play", 0) < 2.0 else "play"
                self._last_play = now
                self._inbox.append({"kind": kind, "paths": ps})
        for f in msg.get("files") or []:
            if os.path.exists(f):
                for p in files.expand([f]):
                    self._watch.add(p)
                    self._inbox.append({"kind": "file", "value": os.path.basename(p)})
        for u in msg.get("urls") or []:
            self.link_download([{"url": u, "title": u}])
            self._inbox.append({"kind": "url", "value": u})
        if self._window:
            try:
                self._window.restore()
                self._window.show()
            except Exception:
                pass


    # ------------------------------------------------------------ Fehlerprotokoll & Diagnose
    def log_js(self, msg):
        paths.log.error("Oberfläche: %s", str(msg)[:2000])
        return True

    def open_licenses(self):
        for d in (paths.app_dir(), paths.res_dir()):
            p = os.path.join(d, "LIZENZEN.txt")
            if os.path.exists(p):
                if paths.IS_WIN:
                    os.startfile(p)
                else:
                    from agcore import osint
                    osint.open_path(p)
                return True
        return False

    def log_open(self):
        return self.open_path(paths.log_file())

    def diagnose(self):
        import platform
        t = self.init()["tools"]
        try:
            devs = recorder.devices()
            dev = f"{sum(1 for d in devs if not d['loopback'])} Eingänge, {sum(1 for d in devs if d['loopback'])} Ausgänge"
        except Exception as e:
            dev = f"Fehler: {e}"
        try:
            cds = ", ".join(d["letter"] + ":" for d in cdrip.drives()) or "keins"
        except Exception as e:
            cds = f"Fehler: {e}"
        lines = [f"{paths.APP_NAME} {paths.VERSION} – Diagnose",
                 f"Windows: {platform.platform()}",
                 f"ffmpeg: {t.get('ffmpeg_version') or ('gefunden' if t['ffmpeg'] else 'FEHLT')}",
                 f"yt-dlp: {t.get('ytdlp_version') or ('gefunden' if t['ytdlp'] else 'FEHLT')}",
                 f"Musikerkennung: {'ja' if identify.available() else 'nein'} · AcoustID-Schlüssel: {'ja' if paths.settings().get('acoustid_key') else 'nein'}",
                 f"Audio: {dev} · Mikrofon-Datenschutz: {recorder.mic_privacy()}",
                 f"CD-Laufwerke: {cds}",
                 f"Bibliothek: {self._lib.status().get('count', 0)} Titel · Aufträge: {len(self._jobs.jobs)}",
                 "", "Letzte Protokollzeilen:", paths.log_tail(40) or "(leer)"]
        return "\n".join(lines)


_FILTER_RE = re.compile(r'^([\w ]+)\((\*(?:\.(?:\w+|\*))*(?:;\*(?:\.(?:\w+|\*))*)*)\)$')


def _safe_filters(types):
    """Dateityp-Filter so umbauen, dass pywebview sie akzeptiert (nur Buchstaben/Leerzeichen in der Beschreibung)."""
    out = []
    for t in types or ():
        m = re.match(r"^(.*?)\s*\((.*)\)\s*$", t)
        if not m:
            continue
        desc = re.sub(r"[^\w ]+", " ", m.group(1)).strip() or "Dateien"
        desc = re.sub(r" +", " ", desc)
        f = f"{desc} ({m.group(2)})"
        if _FILTER_RE.match(f):
            out.append(f)
        else:
            logging.getLogger("songgrabber").warning("Dateifilter verworfen: %s", t)
    return tuple(out)


def _bind_drop(window):
    """Dateien aus dem Explorer hereinziehen: WebView2 liefert die echten Pfade nur an Python-Handler."""
    if getattr(window, "_sg_drop", False):
        return
    try:
        from webview.dom import DOMEventHandler
    except Exception:
        return

    def on_drop(e):
        fs = [f.get("pywebviewFullPath") for f in (e.get("dataTransfer") or {}).get("files", [])]
        fs = [f for f in fs if f]
        if fs:
            window.evaluate_js(f"window.sgDrop && window.sgDrop({json.dumps(fs)})")
    try:
        doc = window.dom.document
        doc.events.dragover += DOMEventHandler(lambda e: None, True, False, debounce=500)
        doc.events.drop += DOMEventHandler(on_drop, True, False)
        window._sg_drop = True
    except Exception as e:
        logging.getLogger("songgrabber").warning("Drag & Drop nicht verfügbar: %s", e)


def _expand_play(items):
    """Dateien, Ordner und Playlists (.m3u/.m3u8) → abspielbare Audiodateien."""
    out = []
    for it in items or []:
        if os.path.isdir(it):
            out += [p for p in files.expand([it]) if os.path.splitext(p)[1].lower() in library.AUDIO_EXT]
        elif it.lower().endswith((".m3u", ".m3u8")):
            out += library.read_playlist(it)
        elif os.path.isfile(it) and os.path.splitext(it)[1].lower() in library.AUDIO_EXT:
            out.append(it)
    return out


def _log_api_errors(cls):
    """Jede Fehlermeldung, die die Oberfläche sieht, landet auch im Protokoll."""
    import functools

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:
                paths.log.warning("%s: %s", fn.__name__, e, exc_info=not isinstance(e, RuntimeError))
                raise
        return inner
    for name, fn in list(vars(cls).items()):
        if callable(fn) and not name.startswith("_") and name not in ("log_js",):
            setattr(cls, name, wrap(fn))
    return cls


_log_api_errors(Api)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="SongGrabber", add_help=True)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--preset", choices=list(encoder.PRESETS))
    ap.add_argument("--out", help="Zielordner")
    ap.add_argument("--headless", action="store_true", help="ohne Fenster arbeiten und danach beenden")
    ap.add_argument("--report", help="JSON-Ergebnisdatei (für Headless-Aufrufe)")
    ap.add_argument("--minimized", action="store_true", help="minimiert starten (Autostart)")
    ap.add_argument("--play", action="store_true", help="Dateien im Player abspielen statt umwandeln")
    args, _ = ap.parse_known_args(argv)
    return args


def run_headless(args):
    """Für Automatisierung: arbeitet alles ab, schreibt optional einen Bericht, Exitcode 0/1."""
    if args.preset or args.out:
        s = paths.settings()
        paths._settings = dict(s, preset=args.preset or s["preset"], output_dir=args.out or s["output_dir"])
    jm = JobManager(workers=1)
    for p in files.expand(args.files):
        jm.add("file", os.path.basename(p), files.convert_job(files.describe(p)), p)
    for u in args.url:
        jm.add("link", u, links.download_job(u), u)
    while jm.active_count():
        time.sleep(0.5)
    result = jm.snapshot()
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    try:
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        pass
    return 0 if all(j["status"] == "fertig" for j in result) else 1


def _single_instance():
    """Gibt das Mutex-Handle zurück oder None, wenn SongGrabber schon startet/läuft."""
    if not paths.IS_WIN:
        from agcore import osint
        return True if osint.single_instance() else None
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = ctypes.c_void_p
    h = k.CreateMutexW(None, False, "SongGrabber_by_Pezhy")
    return None if k.GetLastError() == 183 else h      # 183 = ERROR_ALREADY_EXISTS


def main():
    args = parse_args(sys.argv[1:])
    paths.setup_logging()
    sys.excepthook = lambda t, v, tb: paths.log.critical("Unbehandelter Fehler", exc_info=(t, v, tb))
    threading.excepthook = lambda a: paths.log.error("Fehler im Hintergrund (%s)", a.thread.name if a.thread else "?",
                                                     exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    if args.headless:
        sys.exit(run_headless(args))

    if args.play:
        msg = {"play": [os.path.abspath(f) for f in args.files]}
    else:
        msg = {"files": [os.path.abspath(f) for f in args.files], "urls": args.url} \
            if (args.files or args.url) else {"show": True}
    if bridge.send_to_running(msg):
        return
    # Instanz-Sperre: Setup erkennt das laufende Programm; bei Mehrfachauswahl im Explorer
    # (eine .exe je Datei) übergeben alle weiteren an das erste Fenster statt eigene zu öffnen.
    mutex = _single_instance()
    if mutex is None:
        for _ in range(40):
            time.sleep(0.25)
            if bridge.send_to_running(msg):
                return

    import webview
    api = Api()
    srv = bridge.serve(api.external)
    index = os.path.join(paths.res_dir(), "ui", "index.html")
    window = webview.create_window(f"SongGrabber {paths.VERSION}", index, js_api=api, width=1320,
                                   height=860, min_size=(340, 130), background_color="#0B0D11",
                                   minimized=args.minimized)
    api._window = window
    window.events.loaded += lambda: _bind_drop(window)

    def _closing():
        # Läuft eine Bildschirmaufnahme, nicht einfach schließen – erst fragen (sonst wäre das Video weg).
        if api._screen.status()["state"] in ("recording", "paused") and not api._close_ok:
            threading.Thread(target=lambda: window.evaluate_js("window.Scr && Scr.closeAsk()"), daemon=True).start()
            return False
        return True
    window.events.closing += _closing
    if args.files or args.url:
        window.events.loaded += lambda: api.external(msg)
    try:
        webview.start(debug="--debug" in sys.argv, private_mode=False,
                      storage_path=os.path.join(paths.data_dir(), "webview"))
    finally:
        api._screen.shutdown()
        bridge.shutdown(srv)


if __name__ == "__main__":
    main()
