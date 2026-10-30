"""Erzeugt eine Test-Audio-CD als Abbild (CUE + BIN) – zum Ausprobieren ohne CD-Laufwerk.

  python tools\\make_test_cd.py               → Ordner "Test-CD" mit Test-CD.cue / Test-CD.bin
  python tools\\make_test_cd.py --wav         → Variante mit einer WAV-Datei pro Titel
In SongGrabber geht es auch ohne Skript: Audio-CD → „Test-CD erzeugen“.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agcore.testcd import make  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Test-CD")
    ap.add_argument("--wav", action="store_true", help="eine WAV-Datei pro Titel statt einer BIN")
    a = ap.parse_args()
    print("Fertig:", make(a.out, a.wav))
