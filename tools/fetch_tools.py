"""Einmalig vor dem Build: ffmpeg/ffprobe (mit LAME) und yt-dlp in den Ordner bin legen.

  python tools\\fetch_tools.py                       lädt die offiziellen Builds von GitHub
  python tools\\fetch_tools.py --from "D:\\Tools\\MultiVideoDownloader\\bin"
                                                     kopiert sie aus dem Video Downloader
"""
import argparse
import io
import os
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
FFMPEG_ZIP = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
YTDLP_EXE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FPCALC_ZIP = "https://github.com/acoustid/chromaprint/releases/download/v1.5.1/chromaprint-fpcalc-1.5.1-windows-x86_64.zip"
NEEDED = ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe")
OPTIONAL = ("fpcalc.exe",)          # Musikerkennung (AcoustID)


def download(url):
    print("Lade", url)
    req = urllib.request.Request(url, headers={"User-Agent": "SongGrabber-Setup"})
    with urllib.request.urlopen(req, timeout=600) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            if total:
                sys.stdout.write(f"\r  {buf.tell() / 1048576:.0f} / {total / 1048576:.0f} MB")
                sys.stdout.flush()
        print()
        return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", help="vorhandenen bin-Ordner (z. B. vom Video Downloader) kopieren")
    a = ap.parse_args()
    os.makedirs(BIN, exist_ok=True)
    if a.src:
        for n in NEEDED + OPTIONAL:
            p = os.path.join(a.src, n)
            if os.path.exists(p):
                shutil.copy2(p, BIN)
                print("kopiert:", n)
            else:
                print("fehlt im Quellordner:", n)
    if not os.path.exists(os.path.join(BIN, "ffmpeg.exe")) or not os.path.exists(os.path.join(BIN, "ffprobe.exe")):
        z = zipfile.ZipFile(io.BytesIO(download(FFMPEG_ZIP)))
        for name in z.namelist():
            base = os.path.basename(name)
            if base in ("ffmpeg.exe", "ffprobe.exe"):
                with z.open(name) as s, open(os.path.join(BIN, base), "wb") as d:
                    shutil.copyfileobj(s, d)
                print("entpackt:", base)
    if not os.path.exists(os.path.join(BIN, "yt-dlp.exe")):
        with open(os.path.join(BIN, "yt-dlp.exe"), "wb") as f:
            f.write(download(YTDLP_EXE))
        print("gespeichert: yt-dlp.exe")
    if not os.path.exists(os.path.join(BIN, "fpcalc.exe")):
        try:
            z = zipfile.ZipFile(io.BytesIO(download(FPCALC_ZIP)))
            for name in z.namelist():
                if os.path.basename(name) == "fpcalc.exe":
                    with z.open(name) as s_, open(os.path.join(BIN, "fpcalc.exe"), "wb") as d:
                        shutil.copyfileobj(s_, d)
                    print("entpackt: fpcalc.exe")
        except Exception as e:
            print("Hinweis: fpcalc.exe konnte nicht geladen werden (Musikerkennung):", e)
    missing = [n for n in NEEDED if not os.path.exists(os.path.join(BIN, n))]
    print("Fertig." if not missing else "Es fehlen noch: " + ", ".join(missing))


if __name__ == "__main__":
    main()
