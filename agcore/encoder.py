"""Encoder: ffmpeg mit eingebautem LAME (MP3), PCM (WAV) und FLAC."""
import json
import os
import re
import subprocess
import threading

from . import paths

MP3_TAG_ARGS = ["-id3v2_version", "3", "-write_id3v1", "1"]

PRESETS = {
    "mp3_v0":   {"fmt": "MP3",  "label": "VBR V0 · ≈245 kbps (empfohlen)", "ext": "mp3",
                 "args": ["-c:a", "libmp3lame", "-q:a", "0", "-compression_level", "0"]},
    "mp3_320":  {"fmt": "MP3",  "label": "CBR 320 kbps · maximal", "ext": "mp3",
                 "args": ["-c:a", "libmp3lame", "-b:a", "320k", "-compression_level", "0"]},
    "mp3_256":  {"fmt": "MP3",  "label": "CBR 256 kbps", "ext": "mp3",
                 "args": ["-c:a", "libmp3lame", "-b:a", "256k", "-compression_level", "0"]},
    "mp3_v2":   {"fmt": "MP3",  "label": "VBR V2 · ≈190 kbps", "ext": "mp3",
                 "args": ["-c:a", "libmp3lame", "-q:a", "2", "-compression_level", "0"]},
    "mp3_192":  {"fmt": "MP3",  "label": "CBR 192 kbps", "ext": "mp3",
                 "args": ["-c:a", "libmp3lame", "-b:a", "192k", "-compression_level", "0"]},
    "mp3_128":  {"fmt": "MP3",  "label": "CBR 128 kbps · klein", "ext": "mp3",
                 "args": ["-c:a", "libmp3lame", "-b:a", "128k", "-compression_level", "0"]},
    "wav_16_44": {"fmt": "WAV", "label": "16 Bit · 44,1 kHz (CD-Qualität)", "ext": "wav",
                  "args": ["-c:a", "pcm_s16le", "-ar", "44100"]},
    "wav_24_48": {"fmt": "WAV", "label": "24 Bit · 48 kHz (Studio)", "ext": "wav",
                  "args": ["-c:a", "pcm_s24le", "-ar", "48000"]},
    "wav_24_96": {"fmt": "WAV", "label": "24 Bit · 96 kHz (Hi-Res)", "ext": "wav",
                  "args": ["-c:a", "pcm_s24le", "-ar", "96000"]},
    "wav_24_src": {"fmt": "WAV", "label": "24 Bit · Abtastrate wie Quelle", "ext": "wav",
                   "args": ["-c:a", "pcm_s24le"]},
    "flac_16":  {"fmt": "FLAC", "label": "16 Bit · verlustfrei", "ext": "flac",
                 "args": ["-c:a", "flac", "-compression_level", "8", "-sample_fmt", "s16"]},
    "flac_24":  {"fmt": "FLAC", "label": "24 Bit · verlustfrei", "ext": "flac",
                 "args": ["-c:a", "flac", "-compression_level", "8", "-sample_fmt", "s32",
                          "-bits_per_raw_sample", "24"]},
}


def preset_list():
    return [{"id": k, "fmt": v["fmt"], "label": v["label"], "ext": v["ext"]} for k, v in PRESETS.items()]


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- Analyse

def probe(path):
    """Liefert Dauer, Audiostreams, Tags und ob ein Cover enthalten ist."""
    r = paths.run([paths.ffprobe(), "-v", "error", "-show_format", "-show_streams",
                   "-show_chapters", "-of", "json", path], timeout=60)
    data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    cover = any(s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic")
                for s in streams)
    video = any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
                for s in streams)
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    if audio:
        tags.update({k.lower(): v for k, v in (audio[0].get("tags") or {}).items()
                     if k.lower() in ("title", "artist", "album") and k.lower() not in tags})
    try:
        duration = float(fmt.get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {
        "duration": duration,
        "audio": [{"index": i, "codec": s.get("codec_name"), "rate": int(s.get("sample_rate") or 0),
                   "channels": s.get("channels"), "lang": (s.get("tags") or {}).get("language", "")}
                  for i, s in enumerate(audio)],
        "tags": tags,
        "cover": cover,
        "video": video,
        "format": fmt.get("format_long_name") or fmt.get("format_name", ""),
        "chapters": [{"start": float(c.get("start_time", 0)), "end": float(c.get("end_time", 0)),
                      "title": (c.get("tags") or {}).get("title", "")} for c in data.get("chapters", [])],
    }


def max_volume(path, start=None, end=None):
    args = [paths.ffmpeg(), "-hide_banner", "-nostdin"] + _seek(start, end) + \
           ["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"]
    r = paths.run(args, timeout=3600)
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr.decode("utf-8", "replace"))
    return float(m.group(1)) if m else None


def silences(path, noise_db=-45, min_len=1.5):
    """Erkennt Pausen (für das automatische Teilen von Platten-/Kassettenaufnahmen)."""
    r = paths.run([paths.ffmpeg(), "-hide_banner", "-nostdin", "-i", path, "-af",
                   f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"], timeout=7200)
    out = r.stderr.decode("utf-8", "replace")
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", out)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def split_points(path, duration, noise_db=-45, min_pause=1.5, min_track=20):
    segs, cursor = [], 0.0
    for s, e in silences(path, noise_db, min_pause):
        if s - cursor >= min_track:
            segs.append((cursor, s))
        cursor = e if e is not None else duration
    if duration - cursor >= min_track:
        segs.append((cursor, duration))
    return segs or [(0.0, duration)]


def make_square_cover(src, dst):
    r = paths.run([paths.ffmpeg(), "-hide_banner", "-nostdin", "-y", "-i", src, "-vf",
                   "crop='min(iw,ih)':'min(iw,ih)',scale='min(800,iw)':-2", "-q:v", "2", dst], timeout=60)
    return dst if r.returncode == 0 and os.path.exists(dst) else src


def to_jpeg(src, dst):
    r = paths.run([paths.ffmpeg(), "-hide_banner", "-nostdin", "-y", "-i", src, "-q:v", "2", dst],
                  timeout=60)
    return dst if r.returncode == 0 and os.path.exists(dst) else None


# ---------------------------------------------------------------- Umwandeln

def _seek(start, end):
    a = []
    if start:
        a += ["-ss", f"{start:.3f}"]
    if end:
        a += ["-to", f"{end:.3f}"]
    return a


def encode(src, dst, preset_id, tags=None, cover=None, *, start=None, end=None, stream=0,
           normalize="off", trim=False, vinyl=False, keep_meta=False, src_info=None,
           duration=None, progress=None, cancel=None, extra_input=None, rate=None):
    """Wandelt eine Quelle in das Zielformat um. progress(0..1) wird laufend aufgerufen."""
    preset = PRESETS[preset_id]
    ext = preset["ext"]
    info = src_info or {}
    src_rate = 0
    if info.get("audio"):
        a = info["audio"][min(stream, len(info["audio"]) - 1)]
        src_rate = a.get("rate") or 0

    filters = []
    if vinyl:
        filters += ["highpass=f=18", "adeclick"]
    if trim:
        t = "silenceremove=start_periods=1:start_threshold=-60dB:start_silence=0.1"
        filters += [t, "areverse", t, "areverse"]
    if normalize == "peak":
        mv = max_volume(src, start, end)
        if mv is not None and abs(-1.0 - mv) > 0.1:
            filters.append(f"volume={-1.0 - mv:.2f}dB")
    elif normalize == "loud":
        filters.append("loudnorm=I=-14:TP=-1.0:LRA=11")

    args = [paths.ffmpeg(), "-hide_banner", "-nostdin", "-y"]
    args += extra_input or []
    args += _seek(start, end) + ["-i", src]
    use_cover = bool(cover) and ext in ("mp3", "flac") and os.path.exists(cover)
    keep_cover = (not use_cover) and keep_meta and info.get("cover") and ext in ("mp3", "flac")
    if use_cover:
        args += ["-i", cover]
    args += ["-map", f"0:a:{stream}"]
    if use_cover:
        args += ["-map", "1:v:0"]
    elif keep_cover:
        args += ["-map", "0:v?"]
    if use_cover or keep_cover:
        args += ["-c:v", "copy", "-disposition:v:0", "attached_pic",
                 "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        args += ["-vn"]
    args += ["-sn", "-dn"]
    args += preset["args"]

    # Abtastrate: LAME kann max. 48 kHz; loudnorm würde sonst auf 192 kHz hochrechnen.
    has_ar = "-ar" in preset["args"]
    if rate:
        args += ["-ar", str(int(rate))]
    elif not has_ar:
        need = None
        if ext == "mp3" and src_rate > 48000:
            need = 48000 if src_rate % 48000 == 0 else 44100
        elif normalize == "loud":
            need = src_rate or 44100
        if need:
            args += ["-ar", str(need)]
    if filters:
        args += ["-af", ",".join(filters)]
    args += ["-map_metadata", "0" if keep_meta else "-1"]
    for k, v in (tags or {}).items():
        if v not in (None, ""):
            args += ["-metadata", f"{k}={v}"]
    if ext == "mp3":
        args += MP3_TAG_ARGS
    args += ["-progress", "pipe:1", "-nostats", dst]

    total = duration or ((end or info.get("duration") or 0) - (start or 0))
    proc = paths.popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err_tail = []

    def _drain():
        for line in proc.stderr:
            err_tail.append(line.decode("utf-8", "replace").rstrip())
            del err_tail[:-15]
    threading.Thread(target=_drain, daemon=True).start()

    for raw in proc.stdout:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            _rm(dst)
            raise Cancelled()
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith(("out_time_us=", "out_time_ms=")) and total and progress:
            try:
                us = int(line.split("=", 1)[1])
                progress(max(0.0, min(1.0, us / 1e6 / total)))
            except ValueError:
                pass
    proc.wait()
    if proc.returncode != 0:
        _rm(dst)
        raise RuntimeError("ffmpeg: " + (" | ".join(err_tail[-3:]) or f"Fehlercode {proc.returncode}"))
    if progress:
        progress(1.0)
    return dst


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass
