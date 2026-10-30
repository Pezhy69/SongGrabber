"""Test-Audio-CD als Abbild (CUE + BIN/WAV) erzeugen – zum Ausprobieren ohne CD-Laufwerk.

  python tools\\make_test_cd.py               → Ordner "Test-CD" mit Test-CD.cue / Test-CD.bin
  python tools\\make_test_cd.py --wav         → Variante mit einer WAV-Datei pro Titel
In SongGrabber: Audio-CD → „CD-Abbild öffnen“ → Test-CD.cue wählen.
"""
import math
import os
import struct
import wave

RATE = 44100
TRACKS = [  # Titel, Sekunden, Grundton (Hz), Melodie (Halbtöne)
    ("Morgensonne", 22, 262, [0, 4, 7, 12, 7, 4]),
    ("Regentropfen", 18, 330, [0, 3, 7, 10, 7, 3]),
    ("Nachtfahrt", 25, 196, [0, 7, 5, 3, 0, -2]),
    ("Abschied (Live)", 15, 294, [0, 2, 4, 5, 7, 9]),
]


def tone(seconds, base, melody):
    n = int(seconds * RATE)
    step = n // len(melody)
    out = bytearray()
    for i in range(n):
        note = melody[min(i // step, len(melody) - 1)]
        f = base * 2 ** (note / 12)
        t = i / RATE
        env = min(1.0, t * 4, (seconds - t) * 2)            # weich ein- und ausblenden
        v = env * (0.35 * math.sin(2 * math.pi * f * t) + 0.12 * math.sin(2 * math.pi * f * 2 * t))
        l, r = int(v * 32767 * 0.9), int(v * 32767 * (0.6 + 0.3 * math.sin(t)))   # leichtes Stereo
        out += struct.pack("<hh", l, r)
    return bytes(out)


def silence(seconds):
    return b"\0" * (int(seconds * RATE) * 4)


def pad(data):
    return data + b"\0" * ((-len(data)) % 2352)


def msf(sectors):
    return f"{sectors // 4500:02d}:{sectors // 75 % 60:02d}:{sectors % 75:02d}"


def make(out, wav=False, log=print):

    class a:  # noqa: N801
        pass
    a.out, a.wav = out, wav
    os.makedirs(a.out, exist_ok=True)
    cue = ['PERFORMER "SongGrabber Testband"', 'TITLE "Testalbum ohne Laufwerk"', 'REM DATE 2026', 'REM GENRE "Pop"']
    if not a.wav:
        cue.append('FILE "Test-CD.bin" BINARY')
        binf = open(os.path.join(a.out, "Test-CD.bin"), "wb")
        pos = 0
    for i, (title, sec, base, mel) in enumerate(TRACKS, 1):
        log(f"Titel {i}: {title} ({sec} s)")
        gap = b"" if i == 1 else pad(silence(2))          # 2 s Pause vor jedem Titel (wie auf echten CDs)
        audio = pad(tone(sec, base, mel))
        if a.wav:
            name = f"{i:02d} - {title}.wav"
            with wave.open(os.path.join(a.out, name), "wb") as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
                w.writeframes(gap + audio)
            cue += [f'FILE "{name}" WAVE', f"  TRACK {i:02d} AUDIO", f'    TITLE "{title}"',
                    '    PERFORMER "SongGrabber Testband"']
            if gap:
                cue.append("    INDEX 00 00:00:00")
            cue.append(f"    INDEX 01 {msf(len(gap) // 2352)}")
        else:
            cue += [f"  TRACK {i:02d} AUDIO", f'    TITLE "{title}"', '    PERFORMER "SongGrabber Testband"']
            if gap:
                cue.append(f"    INDEX 00 {msf(pos)}")
            binf.write(gap)
            pos += len(gap) // 2352
            cue.append(f"    INDEX 01 {msf(pos)}")
            binf.write(audio)
            pos += len(audio) // 2352
    if not a.wav:
        binf.close()
    with open(os.path.join(a.out, "Test-CD.cue"), "w", encoding="utf-8") as f:
        f.write("\n".join(cue) + "\n")
    return os.path.abspath(os.path.join(a.out, "Test-CD.cue"))
