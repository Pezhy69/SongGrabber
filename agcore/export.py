"""Auf USB-Stick, SD-Karte oder Handy übertragen – optional autoradiotauglich umgewandelt."""
import ctypes
import os
import shutil

from . import encoder, library, paths

MODES = {
    "copy": "Unverändert kopieren",
    "car": "Autoradio-sicher: MP3 192 kbps, 44,1 kHz",
    "mp3_320": "MP3 320 kbps",
}


def drives():
    """Wechseldatenträger (USB-Sticks, SD-Karten) + per USB verbundene Handys mit Laufwerksbuchstaben."""
    if not paths.IS_WIN:
        from . import osint
        return osint.drives()
    k = ctypes.windll.kernel32
    out = []
    mask = k.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        if k.GetDriveTypeW(ctypes.c_wchar_p(root)) != 2:        # DRIVE_REMOVABLE
            continue
        label = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        if not k.GetVolumeInformationW(ctypes.c_wchar_p(root), label, 261, None, None, None, fs, 261):
            continue
        free = ctypes.c_ulonglong(0)
        total = ctypes.c_ulonglong(0)
        k.GetDiskFreeSpaceExW(ctypes.c_wchar_p(root), ctypes.byref(free), ctypes.byref(total), None)
        out.append({"root": root, "label": label.value or "Wechseldatenträger", "fs": fs.value,
                    "free": free.value, "total": total.value})
    return out


def _target_name(item, i, numbered, ext):
    t = library.read_tags(item) if isinstance(item, str) else item
    base = f"{t.get('artist') or 'Unbekannt'} - {t.get('title') or 'Unbenannt'}"
    if numbered:
        base = f"{i:03d} - {base}"
    return paths.clean(base)[:120] + "." + ext


def job(name, files, target, mode="copy", numbered=True, write_m3u=True):
    """files: Liste von Pfaden (in Wiedergabereihenfolge). Legt <Ziel>/<Name>/ an."""
    def run(j):
        folder = os.path.join(target, paths.clean(name)[:80])
        os.makedirs(folder, exist_ok=True)
        need = sum(os.path.getsize(f) for f in files if os.path.isfile(f))
        free = shutil.disk_usage(target).free
        if mode == "copy" and need > free:
            raise RuntimeError(f"Zu wenig Platz: {need / 1e9:.1f} GB nötig, {free / 1e9:.1f} GB frei.")
        written, skipped = [], 0
        n = len(files)
        for i, src in enumerate(files, 1):
            if j.cancel.is_set():
                raise encoder.Cancelled()
            if not os.path.isfile(src):
                continue
            ext = os.path.splitext(src)[1][1:].lower() if mode == "copy" else "mp3"
            dst = os.path.join(folder, _target_name(src, i, numbered, ext))
            j.set((i - 1) / n, f"Titel {i}/{n}: {os.path.basename(dst)}")
            if os.path.exists(dst) and (mode != "copy" or os.path.getsize(dst) == os.path.getsize(src)):
                skipped += 1
                written.append(dst)
                continue
            if mode == "copy":
                shutil.copyfile(src, dst + ".part")
                os.replace(dst + ".part", dst)
            else:
                preset = "mp3_320" if mode == "mp3_320" else "mp3_192"
                _encode_copy_tags(src, dst, preset, 44100 if mode == "car" else None, j, (i - 1) / n, i / n)
            written.append(dst)
        if write_m3u and written:
            with open(os.path.join(folder, paths.clean(name)[:80] + ".m3u"), "w", encoding="utf-8-sig") as f:
                f.write("#EXTM3U\n" + "".join(os.path.basename(w) + "\n" for w in written))
        j.outputs.append(folder)
        j.set(1.0, f"Fertig · {len(written)} Titel" + (f" ({skipped} schon vorhanden)" if skipped else ""))
    return run


def _encode_copy_tags(src, dst, preset, rate, j, p0, p1):
    """Neu kodieren, Tags + Cover übernehmen (Cover für Autoradios auf 500 px verkleinert)."""
    tmp = dst + ".part.mp3"
    encoder.encode(src, tmp, preset, None, None, keep_meta=True, src_info=encoder.probe(src), rate=rate,
                   progress=lambda f: j.set(p0 + (p1 - p0) * f), cancel=j.cancel)
    os.replace(tmp, dst)
    try:
        from . import tags
        data = tags.cover(src)
        if data:
            small = os.path.join(paths.temp_dir(), "export_cover.jpg")
            with open(small + ".src", "wb") as f:
                f.write(data)
            paths.run([paths.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", small + ".src",
                       "-vf", "scale='min(500,iw)':-2", "-q:v", "3", small], timeout=60)
            if os.path.exists(small):
                with open(small, "rb") as f:
                    tags.write(dst, cover_data=f.read())
    except Exception:
        pass
