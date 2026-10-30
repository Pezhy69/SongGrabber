"""Anfang/Ende kürzen: Wellenform, automatischer Vorschlag, verlustfreier Schnitt."""
import os
import shutil
import subprocess

import numpy as np

from . import encoder, paths

RATE = 4000          # Analyse-Abtastrate (reicht für Pegel/Spektrum)
HOP = 0.05           # 50-ms-Fenster


def _decode(path):
    r = paths.run([paths.ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-i", path, "-vn",
                   "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"], timeout=600)
    if r.returncode != 0:
        raise RuntimeError("Datei konnte nicht gelesen werden.")
    return np.frombuffer(r.stdout, dtype="<f4")


def _frames(x):
    n = int(RATE * HOP)
    m = len(x) // n
    return x[: m * n].reshape(m, n)


def analyze(path, width=1200):
    """Wellenform (Spitzenwerte für die Anzeige) + Vorschlag für Start/Ende."""
    x = _decode(path)
    dur = len(x) / RATE
    if dur < 1:
        raise RuntimeError("Datei ist zu kurz.")
    fr = _frames(x)
    rms = np.sqrt((fr ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    # Spektrale Flachheit: hoch bei Rauschen/Applaus, niedrig bei Musik (tonal)
    spec = np.abs(np.fft.rfft(fr * np.hanning(fr.shape[1]), axis=1)) + 1e-9
    flat = np.exp(np.log(spec).mean(axis=1)) / spec.mean(axis=1)
    start, end, why = suggest(db, flat, dur)
    # Spitzen für die Anzeige
    w = max(100, min(int(width), 4000))
    edges = np.linspace(0, len(x), w + 1).astype(int)
    peaks = [float(np.abs(x[a:b]).max()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]
    top = max(peaks) or 1.0
    return {"duration": round(dur, 3), "peaks": [round(p / top, 3) for p in peaks],
            "start": round(start, 2), "end": round(end, 2), "why": why}


def _smooth(a, k):
    k = max(1, int(k))
    return np.convolve(a, np.ones(k) / k, mode="same")


def suggest(db, flat, dur):
    """Heuristik – bewusst vorsichtig: lieber zu wenig als in den Song schneiden."""
    n = len(db)
    ref = np.percentile(db, 90)                         # „laute Musik“-Bezugspegel
    loud = _smooth(db, 1.0 / HOP) > ref - 24            # ±1 s geglättet
    musical = _smooth(flat, 2.0 / HOP) < 0.30           # tonal (Musik) statt Rauschen/Applaus
    music = loud & musical
    why = []
    # Anfang: erste Stelle, ab der 2 s am Stück Musik läuft
    run, start_i = int(2.0 / HOP), 0
    for i in range(n - run):
        if music[i:i + run].all():
            start_i = i
            break
    # Ende: letzte Stelle mit 2 s Musik davor
    end_i = n
    for i in range(n, run, -1):
        if music[i - run:i].all():
            end_i = i
            break
    start = max(0.0, start_i * HOP - 0.25)                # kleiner Sicherheitsabstand
    end = min(dur, end_i * HOP + 0.6)                     # Ausklang nicht abschneiden
    # Ausklang/Fade: solange der Pegel nur langsam fällt, gehört es noch zum Song
    j = int(end / HOP)
    while j < n - 1 and db[j] > ref - 40 and flat[min(j, n - 1)] < 0.4:
        j += 1
    end = min(dur, max(end, j * HOP + 0.3))
    if start < 0.5:
        start = 0.0
    if dur - end < 0.5:
        end = dur
    if start > 0:
        why.append(f"{start:.1f} s am Anfang (Stille, Rauschen oder Ansage)")
    if end < dur:
        why.append(f"{dur - end:.1f} s am Ende (Applaus, Stille oder Rauschen)")
    if end - start < min(30.0, dur * 0.5):               # Sicherheitsnetz
        return 0.0, dur, "Kein sicherer Vorschlag – bitte von Hand setzen."
    return start, end, ("Vorschlag: " + " und ".join(why)) if why else "Nichts zu kürzen gefunden."


def apply(path, start, end, fade=False, keep_original=False):
    """Schneidet ohne Neukodierung (MP3 auf ~26 ms genau). fade=True kodiert mit Ein-/Ausblendung neu."""
    info = encoder.probe(path)
    dur = info["duration"]
    start, end = max(0.0, float(start)), min(dur, float(end))
    if end - start < 1:
        raise RuntimeError("Der verbleibende Teil ist zu kurz.")
    root, ext = os.path.splitext(path)
    tmp = root + ".kuerzen" + ext
    args = [paths.ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-y"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", path, "-t", f"{end - start:.3f}", "-map", "0", "-map_metadata", "0"]
    if fade:
        f_in, f_out = min(0.8, (end - start) / 4), min(2.0, (end - start) / 4)
        codec = {".mp3": ["-c:a", "libmp3lame", "-q:a", "0"], ".flac": ["-c:a", "flac"],
                 ".wav": ["-c:a", "pcm_s24le"] if "24" in str(info.get("audio")) else ["-c:a", "pcm_s16le"],
                 ".m4a": ["-c:a", "aac", "-b:a", "256k"], ".ogg": ["-c:a", "libvorbis", "-q:a", "8"],
                 ".opus": ["-c:a", "libopus", "-b:a", "192k"]}.get(ext.lower(), ["-c:a", "copy"])
        args += ["-c:v", "copy"] + codec + ["-af", f"afade=t=in:d={f_in:.2f},afade=t=out:st={end - start - f_out:.2f}:d={f_out:.2f}"]
    else:
        args += ["-c", "copy"]
    if ext.lower() == ".mp3":
        args += ["-id3v2_version", "3", "-write_id3v1", "1"]
    args.append(tmp)
    r = paths.run(args, timeout=600)
    if r.returncode != 0 or not os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError("Schneiden fehlgeschlagen: " + r.stderr.decode("utf-8", "replace")[-200:])
    if keep_original:
        shutil.copy2(path, paths.unique(root + " (Original)" + ext))
    os.replace(tmp, path)
    # Songtext-Zeitmarken verschieben (.lrc daneben)
    lrc = root + ".lrc"
    if start > 0 and os.path.exists(lrc):
        _shift_lrc(lrc, -start)
    return {"duration": round(end - start, 2)}


def _shift_lrc(path, delta):
    from . import tags
    with open(path, encoding="utf-8") as f:
        items = tags.parse_lrc(f.read())
    out = []
    for ms, t in items:
        ms = ms + int(delta * 1000)
        if ms >= 0:
            out.append(f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}]{t}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
