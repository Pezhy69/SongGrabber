"""CD-Abbilder (CUE + BIN/WAV) wie eine echte Audio-CD lesen – zum Testen ohne Laufwerk
und für vorhandene Abbilder. Liefert dieselbe Schnittstelle wie cdrip.Drive (toc/read/eject)."""
import os
import re
import shlex

from . import paths

SECTOR = 2352


def _msf(s):
    m, sec, f = (int(x) for x in s.split(":"))
    return (m * 60 + sec) * 75 + f


def _cue_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def parse_cue(path):
    """→ files: [{path, type}], tracks: [{n, file, mode, index01, title, performer}], album: {title, performer}"""
    base = os.path.dirname(os.path.abspath(path))
    files, tracks, album = [], [], {"title": "", "performer": "", "date": "", "genre": ""}
    cur_file, cur_track = None, None
    for line in _cue_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parts = shlex.split(line, posix=True)
        except ValueError:
            parts = line.split()
        key = parts[0].upper()
        if key == "FILE" and len(parts) >= 2:
            name = parts[1]
            ftype = parts[2].upper() if len(parts) > 2 else "BINARY"
            p = name if os.path.isabs(name) else os.path.join(base, name)
            if not os.path.exists(p):                    # oft stimmt nur die Endung nicht (.wav ↔ .flac)
                stem = os.path.splitext(os.path.basename(p))[0]
                alt = [f for f in os.listdir(base) if os.path.splitext(f)[0] == stem]
                if alt:
                    p = os.path.join(base, alt[0])
            cur_file = {"path": p, "type": ftype}
            files.append(cur_file)
        elif key == "TRACK" and len(parts) >= 3:
            cur_track = {"n": int(parts[1]), "file": len(files) - 1, "mode": parts[2].upper(),
                         "index01": None, "title": "", "performer": ""}
            tracks.append(cur_track)
        elif key == "INDEX" and len(parts) >= 3 and cur_track is not None and int(parts[1]) == 1:
            cur_track["index01"] = _msf(parts[2])
        elif key == "REM" and len(parts) >= 3 and parts[1].upper() in ("DATE", "GENRE") and cur_track is None:
            album[parts[1].lower()] = parts[2]
        elif key in ("TITLE", "PERFORMER") and len(parts) >= 2:
            (cur_track if cur_track is not None else album)[key.lower()] = parts[1]
    if not tracks:
        raise RuntimeError("Die CUE-Datei enthält keine Titel.")
    for f in files:
        if not os.path.exists(f["path"]):
            raise RuntimeError(f"Datei zum Abbild fehlt: {os.path.basename(f['path'])}")
    return files, tracks, album


class ImageReader:
    """Verhält sich wie ein CD-Laufwerk mit eingelegter CD."""

    def __init__(self, cue):
        self.cue = cue
        self.files, self.tracks, self.album = parse_cue(cue)
        self.segments = []            # (start_lba, sectors, path, sector_size, byteswap)
        lba = 0
        for i, f in enumerate(self.files):
            src = f["path"]
            if f["type"] not in ("BINARY", "MOTOROLA"):
                src = self._to_raw(src)
            modes = [t["mode"] for t in self.tracks if t["file"] == i]
            size = 2048 if modes and all(m.endswith("/2048") for m in modes) else SECTOR
            sectors = os.path.getsize(src) // size
            self.segments.append((lba, sectors, src, size, f["type"] == "MOTOROLA"))
            for t in self.tracks:
                if t["file"] == i:
                    t["lba"] = lba + (t["index01"] or 0)
            lba += sectors
        self.leadout = lba

    def _to_raw(self, src):
        """WAV/FLAC/MP3 im CUE → rohes 16-Bit-Stereo-PCM 44,1 kHz (wie auf der CD)."""
        st = os.stat(src)
        dst = os.path.join(paths.temp_dir(), f"cdimg_{abs(hash((src, st.st_size, st.st_mtime))) % 10**10}.raw")
        if not os.path.exists(dst):
            r = paths.run([paths.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", src, "-f", "s16le",
                           "-ac", "2", "-ar", "44100", dst + ".part"], timeout=1800)
            if r.returncode != 0:
                raise RuntimeError(f"Abbild-Datei nicht lesbar: {os.path.basename(src)}")
            os.replace(dst + ".part", dst)
        return dst

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def toc(self):
        out = [{"number": t["n"], "lba": t["lba"], "data": t["mode"] != "AUDIO"} for t in self.tracks]
        out.append({"number": 0xAA, "lba": self.leadout, "data": False})
        return out

    def read(self, lba, count):
        out = bytearray()
        want_end = lba + count
        for start, sectors, path, size, swap in self.segments:
            end = start + sectors
            if want_end <= start or lba >= end:
                continue
            a, b = max(lba, start), min(want_end, end)
            with open(path, "rb") as f:
                f.seek((a - start) * size)
                chunk = f.read((b - a) * size)
            if size != SECTOR:                              # Datentrack: auf Rohsektorgröße auffüllen
                chunk = b"".join(chunk[i:i + size].ljust(SECTOR, b"\0") for i in range(0, len(chunk), size))
            if swap:
                import numpy as np
                chunk = np.frombuffer(chunk, dtype=">i2").astype("<i2").tobytes()
            out += chunk
        out = bytes(out)
        return out.ljust(count * SECTOR, b"\0") if len(out) < count * SECTOR else out

    def eject(self):
        return True

    def cdtext(self):
        return {"album": self.album.get("title", ""), "artist": self.album.get("performer", ""),
                "date": self.album.get("date", ""), "genre": self.album.get("genre", ""),
                "tracks": {t["n"]: {"title": t["title"], "artist": t["performer"]} for t in self.tracks}}


def is_image(source):
    return isinstance(source, str) and source.lower().endswith(".cue")
