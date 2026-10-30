"""In den Multi Video Downloader kopieren – übergibt Dateien oder Links an SongGrabber.

Beispiele:
    from songgrabber_bridge import to_songgrabber
    to_songgrabber(files=[r"D:\\Downloads\\clip.mp4"])                 # im offenen Fenster umwandeln
    to_songgrabber(urls=["https://youtu.be/..."])                     # Link als Audio holen
    ok, report = to_songgrabber(files=[p], headless=True, preset="mp3_320",
                                 out=r"D:\\Musik", wait=True)          # unsichtbar, wartet aufs Ergebnis

Presets: mp3_v0, mp3_320, mp3_256, mp3_v2, mp3_192, mp3_128,
         wav_16_44, wav_24_48, wav_24_96, wav_24_src, flac_16, flac_24
"""
import json
import os
import subprocess
import sys
import tempfile

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_songgrabber():
    """Sucht SongGrabber.exe: Umgebungsvariable, Nachbarordner, Programmordner."""
    cands = [os.environ.get("SONGGRABBER_EXE", "")]
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    for up in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        cands += [os.path.join(up, "SongGrabber", "SongGrabber.exe"), os.path.join(up, "SongGrabber.exe")]
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
        if base:
            cands.append(os.path.join(base, "SongGrabber", "SongGrabber.exe"))
    return next((c for c in cands if c and os.path.isfile(c)), None)


def to_songgrabber(files=(), urls=(), headless=False, preset=None, out=None, wait=False, exe=None):
    exe = exe or find_songgrabber()
    if not exe:
        raise FileNotFoundError("SongGrabber.exe nicht gefunden (Umgebungsvariable SONGGRABBER_EXE setzen).")
    args = [exe] + [os.path.abspath(f) for f in files]
    for u in urls:
        args += ["--url", u]
    report = None
    if headless:
        args.append("--headless")
        if preset:
            args += ["--preset", preset]
        if out:
            args += ["--out", out]
        report = os.path.join(tempfile.gettempdir(), f"songgrabber_{os.getpid()}.json")
        args += ["--report", report]
    proc = subprocess.Popen(args, creationflags=CREATE_NO_WINDOW, close_fds=True)
    if not (headless and wait):
        return True, None
    proc.wait()
    data = []
    try:
        with open(report, encoding="utf-8") as f:
            data = json.load(f)
        os.remove(report)
    except OSError:
        pass
    return proc.returncode == 0, data
