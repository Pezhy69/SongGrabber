"""Audio-CD: Inhaltsverzeichnis lesen, Disc-ID berechnen, Tracks digital auslesen (Windows)."""
import base64
import ctypes
import hashlib
import os
import shutil
import tempfile
import wave

from . import encoder, musicbrainz, paths, pipeline

SECTOR = 2352            # Bytes pro Audio-Sektor (1/75 s, 16 Bit Stereo 44,1 kHz)
CHUNK = 20               # Sektoren pro Lesebefehl
IOCTL_CDROM_READ_TOC = 0x00024000
IOCTL_CDROM_RAW_READ = 0x0002403E
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808
IOCTL_STORAGE_LOAD_MEDIA = 0x002D480C
GENERIC_READ = 0x80000000
FILE_SHARE_RW = 0x1 | 0x2
OPEN_EXISTING = 3
CDDA = 2


class TRACK_DATA(ctypes.Structure):
    _fields_ = [("Reserved", ctypes.c_ubyte), ("ControlAdr", ctypes.c_ubyte),
                ("TrackNumber", ctypes.c_ubyte), ("Reserved1", ctypes.c_ubyte),
                ("Address", ctypes.c_ubyte * 4)]


class CDROM_TOC(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ubyte * 2), ("FirstTrack", ctypes.c_ubyte),
                ("LastTrack", ctypes.c_ubyte), ("TrackData", TRACK_DATA * 100)]


class RAW_READ_INFO(ctypes.Structure):
    _fields_ = [("DiskOffset", ctypes.c_longlong), ("SectorCount", ctypes.c_ulong),
                ("TrackMode", ctypes.c_int)]


def _k32():
    if not paths.IS_WIN:
        raise RuntimeError("CD-Auslesen ist nur unter Windows verfügbar.")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = ctypes.c_void_p
    k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                              ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    k.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                  ctypes.c_void_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


class Drive:
    def __init__(self, letter):
        self.k = _k32()
        self.letter = letter.strip(":\\ ").upper()
        self.h = self.k.CreateFileW(f"\\\\.\\{self.letter}:", GENERIC_READ, FILE_SHARE_RW, None,
                                    OPEN_EXISTING, 0, None)
        if self.h in (None, ctypes.c_void_p(-1).value):
            raise RuntimeError(f"Laufwerk {self.letter}: kann nicht geöffnet werden.")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.k.CloseHandle(self.h)

    def ioctl(self, code, inbuf=None, insize=0, outbuf=None, outsize=0):
        ret = ctypes.c_uint32(0)
        ok = self.k.DeviceIoControl(self.h, code, inbuf, insize, outbuf, outsize, ctypes.byref(ret), None)
        return bool(ok), ret.value

    def toc(self):
        t = CDROM_TOC()
        ok, _ = self.ioctl(IOCTL_CDROM_READ_TOC, None, 0, ctypes.byref(t), ctypes.sizeof(t))
        if not ok:
            raise RuntimeError("Keine Audio-CD gefunden – bitte CD einlegen.")
        entries = []
        for i in range(t.LastTrack - t.FirstTrack + 2):
            td = t.TrackData[i]
            m, s, f = td.Address[1], td.Address[2], td.Address[3]
            entries.append({"number": td.TrackNumber, "lba": (m * 60 + s) * 75 + f - 150,
                            "data": bool((td.ControlAdr & 0x0F) & 0x04)})
        return entries

    def read(self, lba, count):
        info = RAW_READ_INFO(lba * 2048, count, CDDA)
        buf = ctypes.create_string_buffer(count * SECTOR)
        ok, n = self.ioctl(IOCTL_CDROM_RAW_READ, ctypes.byref(info), ctypes.sizeof(info), buf, len(buf))
        return buf.raw[:n] if ok and n == len(buf) else None

    def eject(self):
        return self.ioctl(IOCTL_STORAGE_EJECT_MEDIA)[0]


def drives():
    if not paths.IS_WIN:
        return []
    k = ctypes.WinDLL("kernel32")
    mask = k.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if k.GetDriveTypeW(ctypes.c_wchar_p(root)) == 5:
                label = ctypes.create_unicode_buffer(261)
                k.GetVolumeInformationW(ctypes.c_wchar_p(root), label, 261, None, None, None, None, 0)
                out.append({"letter": chr(65 + i), "label": label.value})
    return out


def layout(entries):
    """Leitet Tracks, Längen und die MusicBrainz-Disc-ID aus dem Inhaltsverzeichnis ab."""
    leadout = entries[-1]["lba"]
    raw = entries[:-1]
    tracks = []
    for i, e in enumerate(raw):
        end = raw[i + 1]["lba"] if i + 1 < len(raw) else leadout
        if i + 1 < len(raw) and raw[i + 1]["data"] and not e["data"]:
            end -= 11400                  # Enhanced CD: Lücke vor der Datensession
        tracks.append({"n": e["number"], "start": e["lba"], "end": end, "audio": not e["data"],
                       "seconds": round((end - e["lba"]) / 75, 2)})
    audio = [t for t in tracks if t["audio"]]
    if not audio:
        raise RuntimeError("Diese CD enthält keine Audiotitel.")
    first, last = audio[0]["n"], audio[-1]["n"]
    id_leadout = leadout
    after = [t for t in tracks if not t["audio"] and t["n"] > last]
    if after:
        id_leadout = after[0]["start"] - 11400
    offs = {t["n"]: t["start"] + 150 for t in audio}
    return {"tracks": audio, "first": first, "last": last, "leadout": id_leadout + 150,
            "discid": disc_id(first, last, id_leadout + 150, offs),
            "toc": " ".join(str(x) for x in [first, last, id_leadout + 150] + [offs[n] for n in sorted(offs)])}


def disc_id(first, last, leadout, offsets):
    s = "%02X%02X%08X" % (first, last, leadout)
    for i in range(1, 100):
        s += "%08X" % offsets.get(i, 0)
    d = base64.b64encode(hashlib.sha1(s.encode("ascii")).digest()).decode("ascii")
    return d.replace("+", ".").replace("/", "_").replace("=", "-")


def open_source(source):
    """Laufwerksbuchstabe → echtes Laufwerk, Pfad zu .cue → CD-Abbild."""
    from . import cdimage
    return cdimage.ImageReader(source) if cdimage.is_image(source) else Drive(source)


def read_disc(letter, lookup=True):
    with open_source(letter) as d:
        info = layout(d.toc())
        cdtext = d.cdtext() if hasattr(d, "cdtext") else None
    info["letter"] = letter
    info["image"] = bool(cdtext is not None)
    info["cdtext"] = cdtext or {}
    info["releases"] = []
    info["lookup_error"] = ""
    if lookup and paths.settings()["musicbrainz"]:
        try:
            info["releases"] = musicbrainz.lookup(info["discid"], info["toc"], len(info["tracks"]))
        except Exception as e:
            info["lookup_error"] = str(e)
    return info


def eject(letter):
    with open_source(letter) as d:
        return d.eject()


# ---------------------------------------------------------------- Rippen

def _read_verified(d, lba, n, verify, stats):
    """Liest Sektoren; bei Fehlern kleinere Blöcke + Wiederholungen, optional doppelt prüfen."""
    for attempt in range(4):
        a = d.read(lba, n)
        if a is not None and (not verify or d.read(lba, n) == a):
            return a
        stats["retries"] += 1
    if n > 1:
        return b"".join(_read_verified(d, lba + i, 1, verify, stats) for i in range(n))
    stats["errors"] += 1
    return b"\x00" * SECTOR


def rip_job(letter, album, tracks):
    """album: artist, album, date, genre, mbid, cover_url; tracks: [{n,start,end,title,artist}]"""
    def run(job):
        s = paths.settings()
        tmp = tempfile.mkdtemp(prefix="cd_", dir=paths.temp_dir())
        files, stats = [], {"retries": 0, "errors": 0}
        try:
            cover = None
            if album.get("cover_file") and os.path.exists(album["cover_file"]):
                cover = encoder.to_jpeg(album["cover_file"], os.path.join(tmp, "cover.jpg"))
            elif album.get("cover_url"):
                job.set(0, "Lade Cover …")
                cover = musicbrainz.download_cover(album["cover_url"], os.path.join(tmp, "cover.jpg"))
            total = sum(t["end"] - t["start"] for t in tracks) or 1
            done = 0
            count = album.get("track_total") or len(tracks)
            for t in tracks:
                if job.cancel.is_set():
                    raise encoder.Cancelled()
                wav = os.path.join(tmp, f"t{t['n']:02d}.wav")
                span = t["end"] - t["start"]
                with open_source(letter) as d, wave.open(wav, "wb") as w:
                    w.setnchannels(2)
                    w.setsampwidth(2)
                    w.setframerate(44100)
                    lba = t["start"]
                    while lba < t["end"]:
                        if job.cancel.is_set():
                            raise encoder.Cancelled()
                        n = min(CHUNK, t["end"] - lba)
                        w.writeframes(_read_verified(d, lba, n, s["cd_verify"], stats))
                        lba += n
                        frac = (done + (lba - t["start"]) * 0.8) / total
                        job.set(frac, f"Lese Titel {t['n']} von CD …")
                tags = {"title": t.get("title") or f"Titel {t['n']:02d}",
                        "artist": t.get("artist") or album.get("artist"),
                        "album_artist": album.get("artist"), "album": album.get("album"),
                        "track": f"{t['n']}/{count}", "date": album.get("date", "")[:10],
                        "genre": album.get("genre"),
                        "disc": album.get("disc") or ""}
                p0 = (done + span * 0.8) / total
                done += span
                pipeline.output(job, wav, tags, album=True, cover=cover, p0=p0, p1=done / total,
                                src_info={"audio": [{"rate": 44100}], "duration": span / 75},
                                stage=f"Titel {t['n']} umwandeln")
                os.remove(wav)
                files.append(job.outputs[-1])
            pipeline.write_m3u(files, album.get("album") or "Audio-CD")
            msg = "Fertig"
            if stats["errors"]:
                msg += f" · {stats['errors']} unlesbare Sektoren (stumm ersetzt)"
            elif stats["retries"]:
                msg += f" · {stats['retries']} Lesewiederholungen, alles korrigiert"
            job.set(1.0, msg)
            if s["cd_eject"]:
                try:
                    eject(letter)
                except Exception:
                    pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return run
