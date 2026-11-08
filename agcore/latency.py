"""Ton-Verzögerung messen: Wie lange braucht ein Ton vom Programm bis aus dem Lautsprecher (z. B. Fernseher über HDMI)?

Ablauf: Kurze „Zwitscher“-Klicks werden über den gewählten Lautsprecher gespielt und gleichzeitig mit einem Mikrofon
am Rechner aufgenommen (Laptop- oder Webcam-Mikro). Der Abstand zwischen Abspielen und Hören ist die Verzögerung.
Die Mikrofon-Verzögerung steckt mit drin – sie ist bei beiden Lautsprechern gleich. Der Unterschied zwischen
Fernseher und PC-Lautsprechern zeigt daher genau, wie viel der Fernseher zusätzlich kostet.
"""
import threading
import time

import numpy as np

from . import recorder

FS = 48000
N_CLICKS = 7
LEAD = 0.35            # Stille vor dem ersten Klick (s)
TAIL = 0.9             # Nachlauf, damit späte Klicks noch aufgenommen werden (s)
MAX_LAG = 0.7          # länger als 700 ms wird nicht gesucht


def _chirp():
    """20 ms Ton, der von 1,2 auf 6 kHz gleitet – lässt sich in Raumgeräuschen sehr genau wiederfinden."""
    n = int(FS * 0.02)
    t = np.arange(n) / FS
    f0, f1 = 1200.0, 6000.0
    ph = 2 * np.pi * (f0 * t + (f1 - f0) / (2 * t[-1]) * t * t)
    return (np.sin(ph) * np.hanning(n)).astype(np.float32)


def _schedule(seed=None):
    """Abstände zwischen den Klicks leicht zufällig, damit nichts mit einem Echo verwechselt wird."""
    rng = np.random.default_rng(seed)
    gaps = rng.uniform(0.8, 1.05, N_CLICKS - 1)   # länger als die größte gesuchte Verzögerung
    return np.concatenate([[LEAD], LEAD + np.cumsum(gaps)])


def build_signal(sched, channels=2):
    ch = _chirp()
    total = int(FS * (sched[-1] + TAIL))
    sig = np.zeros(total, np.float32)
    for s in sched:
        i = int(s * FS)
        sig[i:i + len(ch)] += ch * 0.8
    return np.repeat(sig[:, None], max(1, channels), axis=1)


def analyze(rec, sched, offset):
    """rec: Mono-Aufnahme. sched: Klick-Zeiten im Abspielsignal (s). offset: Aufnahme-Sample, an dem das Abspielen begann.
    Gibt pro Klick die gemessene Verzögerung in ms zurück (None = nicht gehört)."""
    ch = _chirp()
    rec = np.asarray(rec, np.float32).ravel()
    if not len(rec):
        return []
    # Abgleich mit dem Klick (Kreuzkorrelation über FFT)
    n = len(rec) + len(ch)
    size = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(rec, size) * np.conj(np.fft.rfft(ch, size)), size)[:len(rec)]
    env = np.abs(corr)
    noise = float(np.median(env)) + 1e-9
    out = []
    for s in sched:
        a = int(offset + s * FS)
        b = int(a + MAX_LAG * FS)
        if a < 0 or a >= len(env):
            out.append(None)
            continue
        win = env[a:min(b, len(env))]
        if not len(win):
            out.append(None)
            continue
        top = float(win.max())
        if top / noise <= 12:
            out.append(None)
            continue
        # frühester kräftiger Treffer – spätere Spitzen sind Raumechos
        i = int(np.argmax(win >= top * 0.5))
        j = min(len(win), i + int(0.003 * FS))
        i += int(np.argmax(win[i:j]))
        out.append(round(i / FS * 1000, 1))
    return out


def summary(lags):
    good = [x for x in lags if x is not None]
    if len(good) < 3:
        return {"ok": False, "heard": len(good), "of": len(lags)}
    good.sort()
    med = float(np.median(good))
    return {"ok": True, "ms": round(med), "min": round(good[0]), "max": round(good[-1]),
            "spread": round(float(np.percentile(good, 90) - np.percentile(good, 10))), "heard": len(good), "of": len(lags)}


def speakers():
    def f(sc):
        try:
            d = sc.default_speaker().id
        except Exception:
            d = None
        return [{"id": s.id, "name": s.name, "default": s.id == d} for s in sc.all_speakers()]
    return recorder._in_audio_thread(f)


def measure(speaker_id=None, mic_id=None):
    """Eine Messung (≈ 8 s). Ergebnis: {"ok", "ms", "min", "max", "spread", "heard", "of", "speaker", "mic"}."""
    box = {}

    def run():
        try:
            sc = recorder._audio()
            spk = sc.get_speaker(speaker_id) if speaker_id else sc.default_speaker()
            mic = sc.get_microphone(mic_id) if mic_id else sc.default_microphone()
            sched = _schedule()
            sig = build_signal(sched, getattr(spk, "channels", 2) or 2)
            frames, started, stop = [], threading.Event(), threading.Event()
            t0 = {}

            def rec():
                recorder._audio()
                with mic.recorder(samplerate=FS, channels=1, blocksize=480) as r:
                    r.record(480)                                # Anlaufen lassen
                    t0["t"] = time.perf_counter()
                    started.set()
                    while not stop.is_set():
                        frames.append(r.record(480))
            th = threading.Thread(target=rec, daemon=True)
            th.start()
            if not started.wait(5):
                raise RuntimeError("Das Mikrofon startet nicht.")
            time.sleep(0.25)
            with spk.player(samplerate=FS, channels=sig.shape[1], blocksize=480) as p:
                tp = time.perf_counter()
                p.play(sig)
            time.sleep(TAIL)
            stop.set()
            th.join(3)
            data = np.concatenate(frames)[:, 0] if frames else np.zeros(0, np.float32)
            offset = (tp - t0["t"]) * FS
            res = summary(analyze(data, sched, offset))
            res.update(speaker=spk.name, mic=mic.name)
            box["v"] = res
        except Exception as e:  # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(30)
    if "e" in box:
        raise box["e"]
    if "v" not in box:
        raise RuntimeError("Messung hat zu lange gedauert.")
    return box["v"]
