"""SongGrabber – englische Übersetzung bauen und prüfen.

    python tools/i18n/build.py          schreibt ui/i18n.js aus en.txt + patterns.txt + engine.js
    python tools/i18n/build.py --check  listet deutsche Oberflächentexte ohne Übersetzung

Deutsch bleibt die Quelle: neue Texte einfach deutsch in index.html/app.js schreiben,
dann die Übersetzung in en.txt ergänzen (Deutsch|English) und build.py starten.
Die englische Hilfe steht als <template id="helpEn"> direkt in ui/index.html.
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
UI = os.path.join(ROOT, "ui")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def table(same=False):
    d = {}
    for line in _read(HERE, "en.txt").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        k, v = line.split("|", 1)
        if same or k != v:
            d[k] = v
    return d


def patterns():
    out = []
    for line in _read(HERE, "patterns.txt").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        a, b = line.rsplit("|", 1)
        out.append([a, b])
    return out


def build():
    js = _read(HERE, "engine.js")
    js = js.replace("/*PATS*/[]", json.dumps(patterns(), ensure_ascii=False))
    js = js.replace("/*DICT*/{}", json.dumps(table(), ensure_ascii=False, indent=0, sort_keys=True))
    with open(os.path.join(UI, "i18n.js"), "w", encoding="utf-8", newline="\n") as f:
        f.write(js)
    return len(table())


# ------------------------------------------------------------------ Prüfen
GER = re.compile(r"[äöüÄÖÜß]|\b(der|die|das|und|oder|nicht|mit|für|von|zu|ist|wird|ein|eine|kein|keine|im|in|auf|bei|aus|nach|auch|als|dein\w*|mein\w*|sich|wie|wenn|dann|nur|jetzt|hier|schon|mehr|beim|vom|zum|zur|unter|ohne|bis|ab|an|neue\w*|alle\w*|Songs?\b|Video\w*|Bild\w*|Punkte|Tonart|Verlauf|Hall|Titel|bitte|noch|alle|neu|Neu|Aufnahme|Ordner|Datei|Sender|Musik|Fehler|Fertig|Abbrechen|Speichern|Löschen|Suchen|Weiter|Zurück|Schließen|Öffnen|Einstellungen|Hilfe|Bildschirm|Fenster|Mikro\w*|Ton|Stopp|Lautstärke|Warteschlange|Bibliothek|Favorit\w*|Abspielen|Laden|lädt|läuft|Sekunden|Minuten|Stunde\w*|Interpret|Jahr|Songtext|Lichtshow|Farben|Einfügen|Analysieren|Kapitel|aufnehmen|gespeichert|Vorschau|Stimme|Singen|Abos|Kürzen|Übertragen)\b")


def german_strings():
    H, J = _read(UI, "index.html"), _read(UI, "app.js")
    H = H[:H.index('<template id="helpEn">')] if '<template id="helpEn">' in H else H
    a, b = H.index("<article"), H.rindex("</article>") + 10
    H = H[:a] + H[b:]
    for tag in ("symbol", "script", "style"):
        H = re.sub(rf"<{tag}.*?</{tag}>", "", H, flags=re.S)
    J = J[:J.index("const Mock = (() => {")] if "const Mock = (() => {" in J else J
    ca = J.index("const CHANGES = ["); cb = J.index("function renderChanges", ca)
    J = J[:ca] + J[cb:]
    # Fernseher- und Handy-Seite: Text im HTML und Texte im Skript
    for extra in ("tv.html", "party.html"):
        X = _read(UI, extra)
        J += "\n" + "\n".join(re.findall(r"<script>(.*?)</script>", X, flags=re.S))
        H += re.sub(r"<(script|style|svg)\b.*?</\1>", "", X, flags=re.S)
    out = []

    def add(t):
        t = re.sub(r"\s+", " ", html.unescape(t)).strip()
        if len(t) < 2 or not re.search(r"[A-Za-zÄÖÜäöü]{2}", t) or not GER.search(t):
            return
        if re.search(r"\$\{|[=;{}]|=>|\?\s*$|^:|\|\||&&", t):
            return
        out.append(t)
    for m in re.finditer(r">([^<>]+)<", H):
        add(m.group(1))
    for m in re.finditer(r'(?:title|placeholder|aria-label)="([^"]+)"', H):
        add(m.group(1))
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', J):
        s = m.group(1) or m.group(2) or ""
        s = re.sub(r"\$\{[^{}]*(\{[^{}]*\}[^{}]*)*\}", "\u0001", s)
        for part in re.split(r"<[^>]*>|\u0001|\"", s):
            add(part.replace("\\n", " "))
    return list(dict.fromkeys(out))


def translate(t, d, pats, frags):
    if t in d:
        return d[t]
    m = re.match(r'^([\s\d.,:;·()\[\]+\-–—%/×✓★…!?"„“”»«]*)(.*?)([\s\d.,:;·()\[\]+\-–—%/×✓…!?"„“”»«]*)$', t, re.S)
    if m and m.group(2) in d:
        return m.group(1) + d[m.group(2)] + m.group(3)
    x = t
    for a, b in pats:
        x = re.sub(a, re.sub(r"\$(\d)", r"\\\1", b), x)
    for k in frags:
        x = x.replace(k, d[k])
    return x if x != t else None


def missing():
    d, pats = table(same=True), patterns()
    frags = sorted((k for k in d if len(k) >= 8 and " " in k.strip()), key=len, reverse=True)
    return [t for t in german_strings() if translate(t, d, pats, frags) is None]


if __name__ == "__main__":
    if "--check" in sys.argv:
        miss = missing()
        print("\n".join(miss) or "Alles übersetzt.")
        sys.exit(1 if miss else 0)
    print(f"ui/i18n.js geschrieben · {build()} Übersetzungen")
