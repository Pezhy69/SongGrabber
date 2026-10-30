"""Tags, Cover und Songtexte lesen/schreiben – MP3, WAV, AIFF (ID3), FLAC, OGG/Opus (Vorbis), M4A (MP4)."""
import base64
import os

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (APIC, ID3, SYLT, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, USLT,
                         ID3NoHeaderError, Encoding)
from mutagen.mp4 import MP4, MP4Cover

FIELDS = ("title", "artist", "album_artist", "album", "track", "disc", "date", "genre")
ID3_MAP = {"title": TIT2, "artist": TPE1, "album_artist": TPE2, "album": TALB, "track": TRCK,
           "disc": TPOS, "date": TDRC, "genre": TCON}
VORBIS_MAP = {"title": "title", "artist": "artist", "album_artist": "albumartist", "album": "album",
              "track": "tracknumber", "disc": "discnumber", "date": "date", "genre": "genre"}
MP4_MAP = {"title": "\xa9nam", "artist": "\xa9ART", "album_artist": "aART", "album": "\xa9alb",
           "date": "\xa9day", "genre": "\xa9gen"}


def _kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mp3", ".wav", ".aif", ".aiff"):
        return "id3"
    if ext == ".flac":
        return "flac"
    if ext in (".ogg", ".opus", ".oga"):
        return "vorbis"
    if ext in (".m4a", ".mp4", ".aac", ".alac"):
        return "mp4"
    return None


def _id3_open(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mp3":
        try:
            return ID3(path), None
        except ID3NoHeaderError:
            return ID3(), None
    f = mutagen.File(path)                     # WAVE / AIFF tragen ID3 in einem Chunk
    if f.tags is None:
        f.add_tags()
    return f.tags, f


def _id3_save(path, tags, container):
    if container is not None:
        container.save()
    else:
        tags.save(path, v2_version=3, v1=1)


def _pair(v):
    """'3/12' → (3, 12)"""
    s = str(v or "").strip()
    if not s:
        return 0, 0
    a, _, b = s.partition("/")
    try:
        return int(a or 0), int(b or 0)
    except ValueError:
        return 0, 0


# ---------------------------------------------------------------- Lesen

def read(path):
    out = {k: "" for k in FIELDS}
    out.update({"lyrics": "", "has_cover": False, "format": os.path.splitext(path)[1][1:].upper(),
                "duration": 0.0, "path": path})
    kind = _kind(path)
    try:
        f = mutagen.File(path)
        out["duration"] = round(float(getattr(getattr(f, "info", None), "length", 0) or 0), 2)
        if kind == "id3":
            t, _ = _id3_open(path)
            for k, cls in ID3_MAP.items():
                fr = t.getall(cls.__name__)
                if fr:
                    out[k] = str(fr[0].text[0]) if fr[0].text else ""
            us = t.getall("USLT")
            out["lyrics"] = us[0].text if us else ""
            out["has_cover"] = bool(t.getall("APIC"))
        elif kind in ("flac", "vorbis"):
            t = f.tags or {}
            for k, vk in VORBIS_MAP.items():
                v = t.get(vk)
                out[k] = v[0] if v else ""
            ly = t.get("lyrics") or t.get("unsyncedlyrics")
            out["lyrics"] = ly[0] if ly else ""
            out["has_cover"] = bool(getattr(f, "pictures", None)) or bool(t.get("metadata_block_picture"))
        elif kind == "mp4":
            t = f.tags or {}
            for k, mk in MP4_MAP.items():
                v = t.get(mk)
                out[k] = str(v[0]) if v else ""
            tr = t.get("trkn")
            if tr:
                out["track"] = f"{tr[0][0]}/{tr[0][1]}" if tr[0][1] else str(tr[0][0])
            dk = t.get("disk")
            if dk:
                out["disc"] = f"{dk[0][0]}/{dk[0][1]}" if dk[0][1] else str(dk[0][0])
            ly = t.get("\xa9lyr")
            out["lyrics"] = ly[0] if ly else ""
            out["has_cover"] = bool(t.get("covr"))
    except Exception:
        pass
    if out["date"]:
        out["date"] = str(out["date"])[:10]
    return out


def cover(path):
    """Rohdaten des eingebetteten Covers oder None."""
    kind = _kind(path)
    try:
        if kind == "id3":
            t, _ = _id3_open(path)
            a = t.getall("APIC")
            return a[0].data if a else None
        f = mutagen.File(path)
        if kind == "flac":
            return f.pictures[0].data if f.pictures else None
        if kind == "vorbis":
            b = (f.tags or {}).get("metadata_block_picture")
            return Picture(base64.b64decode(b[0])).data if b else None
        if kind == "mp4":
            c = (f.tags or {}).get("covr")
            return bytes(c[0]) if c else None
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- Schreiben

def _mime(data):
    return "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"


def write(path, fields=None, cover_data=None, remove_cover=False, lyrics=None):
    """fields: nur übergebene Schlüssel werden geändert ('' löscht). cover_data: Bytes eines Bildes.
    lyrics: Text (bei LRC mit Zeitmarken wird zusätzlich SYLT geschrieben); '' löscht."""
    fields = {k: v for k, v in (fields or {}).items() if k in FIELDS}
    kind = _kind(path)
    if kind is None:
        raise RuntimeError(f"Tags für {os.path.splitext(path)[1]} werden nicht unterstützt.")

    if kind == "id3":
        t, cont = _id3_open(path)
        for k, v in fields.items():
            cls = ID3_MAP[k]
            t.delall(cls.__name__)
            if str(v).strip():
                t.add(cls(encoding=Encoding.UTF16, text=str(v).strip()))
        if remove_cover or cover_data:
            t.delall("APIC")
        if cover_data:
            t.add(APIC(encoding=Encoding.UTF16, mime=_mime(cover_data), type=3, desc="Cover", data=cover_data))
        if lyrics is not None:
            t.delall("USLT")
            t.delall("SYLT")
            if lyrics.strip():
                plain = lrc_to_plain(lyrics) if is_lrc(lyrics) else lyrics
                t.add(USLT(encoding=Encoding.UTF16, lang="und", desc="", text=plain))
                if is_lrc(lyrics):
                    t.add(SYLT(encoding=Encoding.UTF16, lang="und", format=2, type=1, desc="",
                               text=[(txt, ms) for ms, txt in parse_lrc(lyrics)]))
        _id3_save(path, t, cont)
        return True

    f = mutagen.File(path)
    if f.tags is None:
        f.add_tags()
    if kind in ("flac", "vorbis"):
        for k, v in fields.items():
            vk = VORBIS_MAP[k]
            if str(v).strip():
                f.tags[vk] = [str(v).strip()]
            elif vk in f.tags:
                del f.tags[vk]
        if lyrics is not None:
            for key in ("lyrics", "unsyncedlyrics"):
                if key in f.tags:
                    del f.tags[key]
            if lyrics.strip():
                f.tags["lyrics"] = [lyrics]
        if kind == "flac":
            if remove_cover or cover_data:
                f.clear_pictures()
            if cover_data:
                p = Picture()
                p.type, p.mime, p.desc, p.data = 3, _mime(cover_data), "Cover", cover_data
                f.add_picture(p)
        else:
            if (remove_cover or cover_data) and "metadata_block_picture" in f.tags:
                del f.tags["metadata_block_picture"]
            if cover_data:
                p = Picture()
                p.type, p.mime, p.desc, p.data = 3, _mime(cover_data), "Cover", cover_data
                f.tags["metadata_block_picture"] = [base64.b64encode(p.write()).decode("ascii")]
        f.save()
        return True

    if kind == "mp4":
        for k, v in fields.items():
            if k == "track":
                a, b = _pair(v)
                f.tags.pop("trkn", None)
                if a:
                    f.tags["trkn"] = [(a, b)]
            elif k == "disc":
                a, b = _pair(v)
                f.tags.pop("disk", None)
                if a:
                    f.tags["disk"] = [(a, b)]
            else:
                mk = MP4_MAP[k]
                if str(v).strip():
                    f.tags[mk] = [str(v).strip()]
                else:
                    f.tags.pop(mk, None)
        if remove_cover or cover_data:
            f.tags.pop("covr", None)
        if cover_data:
            fmt = MP4Cover.FORMAT_PNG if _mime(cover_data) == "image/png" else MP4Cover.FORMAT_JPEG
            f.tags["covr"] = [MP4Cover(cover_data, imageformat=fmt)]
        if lyrics is not None:
            f.tags.pop("\xa9lyr", None)
            if lyrics.strip():
                f.tags["\xa9lyr"] = [lyrics]
        f.save()
        return True
    return False


# ---------------------------------------------------------------- LRC (synchronisierte Songtexte)
import re  # noqa: E402

_LRC = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def is_lrc(text):
    return bool(text) and len(_LRC.findall(text)) >= 3


def parse_lrc(text):
    """→ [(millisekunden, zeile), …] sortiert."""
    out = []
    for line in (text or "").splitlines():
        stamps = _LRC.findall(line)
        words = _LRC.sub("", line).strip()
        for m, s, frac in stamps:
            ms = (int(m) * 60 + int(s)) * 1000 + (int(frac.ljust(3, "0")[:3]) if frac else 0)
            out.append((ms, words))
    return sorted(out)


def lrc_to_plain(text):
    return "\n".join(t for _, t in parse_lrc(text))
