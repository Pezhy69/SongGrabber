"""Gemeinsamer letzter Schritt aller Quellen: Zielpfad bauen, umwandeln, taggen."""
import os

from . import encoder, paths


def output(job, src, tags, *, album=False, cover=None, start=None, end=None, stream=0,
           vinyl=False, keep_meta=False, src_info=None, p0=0.0, p1=1.0, stage="Umwandeln",
           preset=None, out_dir=None):
    s = paths.settings()
    preset = preset or s["preset"]
    ext = encoder.PRESETS[preset]["ext"]
    tags = {k: v for k, v in tags.items() if v not in (None, "")}
    tags.setdefault("title", "Unbenannt")
    tags.setdefault("artist", "Unbekannt")
    path_tags = dict(tags)
    path_tags["albumartist"] = tags.get("album_artist") or tags.get("artist")
    template = s["name_album"] if album else s["name_single"]
    plain = paths.build_path(paths.ensure_output(out_dir or s["output_dir"]), template, path_tags, ext, make_unique=False)
    if s.get("skip_existing") and os.path.exists(plain) and os.path.getsize(plain) > 0:
        job.outputs.append(plain)
        job.skipped = getattr(job, "skipped", 0) + 1
        job.set(p1, "Schon vorhanden – übersprungen")
        return plain
    dst = paths.unique(plain)
    job.set(p0, f"{stage} → {encoder.PRESETS[preset]['fmt']}")
    encoder.encode(src, dst, preset, tags, cover if s["embed_cover"] else None,
                   start=start, end=end, stream=stream, normalize=s["normalize"],
                   trim=s["trim_silence"], vinyl=vinyl, keep_meta=keep_meta, src_info=src_info,
                   progress=lambda f: job.set(p0 + (p1 - p0) * f), cancel=job.cancel)
    job.outputs.append(dst)
    if s.get("lyrics_auto") and tags.get("artist") not in ("Unbekannt", "Aufnahme") and \
            not tags.get("title", "").startswith(("Titel ", "Aufnahme ", "Mitschnitt ")):
        job.set(p1, "Suche Songtext …")
        try:
            from . import lyrics
            lyrics.apply(dst)
        except Exception:
            pass
    return dst


def write_m3u(files, title, folder=None):
    """Album-Playlist neben die Dateien oder (folder) in den Playlist-Ordner – mit relativen Pfaden."""
    if not files:
        return None
    if folder:
        os.makedirs(folder, exist_ok=True)
        p = paths.unique(os.path.join(folder, paths.clean(title) + ".m3u8"))
        with open(p, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for x in files:
                try:
                    rel = os.path.relpath(x, folder)
                except ValueError:          # anderes Laufwerk
                    rel = x
                f.write(f"#EXTINF:-1,{os.path.splitext(os.path.basename(x))[0]}\n{rel}\n")
        return p
    if not paths.settings()["playlist_m3u"]:
        return None
    folder = os.path.dirname(files[0])
    if any(os.path.dirname(f) != folder for f in files):
        return None
    p = os.path.join(folder, paths.clean(title) + ".m3u8")
    with open(p, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for x in files:
            f.write(os.path.basename(x) + "\n")
    return p
